"""Run: python3 server.py. Persistent shared polls, no third-party dependencies."""
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('SKST_DB', str(ROOT / '.local/polls.sqlite3')))
MSK = timezone(timedelta(hours=3))


def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS options (
          id INTEGER PRIMARY KEY, starts_at TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS votes (
          option_id INTEGER NOT NULL REFERENCES options(id),
          voter TEXT NOT NULL, PRIMARY KEY(option_id, voter));
        ''')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def identity(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
        except cookies.CookieError:
            pass
        token = jar.get('skst_voter')
        value = token.value if token else ''
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            value = secrets.token_hex(32)
        return value, hashlib.sha256(value.encode()).hexdigest()

    def respond(self, status, payload, token=None):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if token:
            secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
            self.send_header('Set-Cookie', f'skst_voter={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000{secure}')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/options':
            token, voter = self.identity()
            now = datetime.now(MSK).isoformat(timespec='minutes')
            with connect() as db:
                rows = db.execute('''SELECT o.id, o.starts_at, COUNT(v.voter),
                  MAX(CASE WHEN v.voter = ? THEN 1 ELSE 0 END)
                  FROM options o LEFT JOIN votes v ON v.option_id = o.id
                  WHERE o.starts_at > ? GROUP BY o.id ORDER BY o.starts_at''', (voter, now)).fetchall()
            self.respond(200, {'options': [dict(id=r[0], starts_at=r[1], votes=r[2], voted=bool(r[3])) for r in rows]}, token)
        elif path in ('/', '/index.html', '/style.css', '/planner.js'):
            super().do_GET()
        else:
            self.send_error(404)

    def do_HEAD(self):
        if self.path.split('?', 1)[0] in ('/', '/index.html', '/style.css', '/planner.js'):
            super().do_HEAD()
        else:
            self.send_error(404)

    def do_POST(self):
        # Browser requests must come from this application's own origin.
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            return self.respond(403, {'error': 'Запрос с другого сайта запрещён.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            return self.respond(400, {'error': 'Некорректный запрос.'})
        token, voter = self.identity()
        if self.path == '/api/options':
            try:
                when = datetime.fromisoformat(data['starts_at'])
                if when.tzinfo is None:
                    raise ValueError()
                when = when.astimezone(MSK).replace(second=0, microsecond=0)
                now = datetime.now(MSK)
                if not now < when <= now + timedelta(days=366):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                return self.respond(400, {'error': 'Выберите будущее время в пределах года.'})
            with connect() as db:
                if db.execute('SELECT COUNT(*) FROM options WHERE starts_at > ?', (now.isoformat(timespec='minutes'),)).fetchone()[0] >= 100:
                    return self.respond(409, {'error': 'Уже предложено 100 вариантов.'})
                try:
                    db.execute('INSERT INTO options(starts_at) VALUES (?)', (when.isoformat(timespec='minutes'),))
                except sqlite3.IntegrityError:
                    return self.respond(409, {'error': 'Такие дата и время уже предложены.'})
            self.respond(201, {'ok': True}, token)
        elif self.path == '/api/vote':
            option_id = data.get('option_id')
            if type(option_id) is not int:
                return self.respond(400, {'error': 'Некорректный вариант.'})
            with connect() as db:
                row = db.execute('SELECT starts_at FROM options WHERE id = ?', (option_id,)).fetchone()
                if not row or datetime.fromisoformat(row[0]) <= datetime.now(MSK):
                    return self.respond(404, {'error': 'Этот вариант больше не доступен.'})
                db.execute('BEGIN IMMEDIATE')
                if data.get('voted') is True:
                    db.execute('INSERT OR IGNORE INTO votes VALUES (?, ?)', (option_id, voter))
                elif data.get('voted') is False:
                    db.execute('DELETE FROM votes WHERE option_id = ? AND voter = ?', (option_id, voter))
                else:
                    return self.respond(400, {'error': 'Не указано действие.'})
            self.respond(200, {'ok': True}, token)
        else:
            self.respond(404, {'error': 'Не найдено.'})


if __name__ == '__main__':
    initialize()
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
