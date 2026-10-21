'use strict';
(() => {
  const form = document.querySelector('#planner-form');
  const open = document.querySelector('#open-planner');
  const status = document.querySelector('#planner-status');
  const date = document.querySelector('#game-date');
  const time = document.querySelector('#game-time');
  const options = document.querySelector('#game-options');
  const hourMode = document.querySelector('#choose-hour');
  const minuteMode = document.querySelector('#choose-minute');
  const period = document.querySelector('#clock-period');
  const clock = document.querySelector('.clock');
  let mode = 'hour', available = false, refreshing = false;
  function today() { return new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Moscow'}).format(new Date()); }
  date.min = today(); date.value = date.min;
  function message(text, error = false) { status.textContent = text; status.classList.toggle('error', error); }
  async function request(path, data) {
    const response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...(data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)} : {})});
    if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Сервис расписания недоступен.');
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'Не удалось сохранить. Попробуй ещё раз.');
    return body;
  }
  function hands() {
    const [h,m] = (time.value || '17:00').split(':').map(Number);
    clock.querySelector('.hour-hand').style.transform = `rotate(${h*30+m/2}deg)`;
    clock.querySelector('.minute-hand').style.transform = `rotate(${m*6}deg)`;
    period.textContent = h >= 12 ? 'После полудня' : 'До полудня';
    hourMode.setAttribute('aria-pressed', String(mode === 'hour'));
    minuteMode.setAttribute('aria-pressed', String(mode === 'minute'));
    document.querySelector('#clock-help').textContent = mode === 'hour' ? 'Нажми число на циферблате, чтобы выбрать час.' : 'Выбери минуты на циферблате. Любую точную минуту можно ввести в поле времени.';
    clock.querySelectorAll('.clock-number').forEach((button,i) => {
      button.textContent = mode === 'hour' ? String(i || 12) : String(i*5).padStart(2,'0');
      button.setAttribute('aria-label', mode === 'hour' ? `${i || 12} часов` : `${i*5} минут`);
      button.setAttribute('aria-pressed', String(mode === 'hour' ? h % 12 === i : m === i*5));
    });
  }
  for (let i=0;i<12;i++) {
    const button = document.createElement('button'); button.type='button'; button.className='clock-number';
    button.style.left = `${50+39*Math.sin(i*Math.PI/6)}%`; button.style.top = `${50-39*Math.cos(i*Math.PI/6)}%`;
    button.addEventListener('click', () => {
      let [h,m] = (time.value || '17:00').split(':').map(Number);
      if (mode === 'hour') { h = i + (h >= 12 ? 12 : 0); mode = 'minute'; } else m=i*5;
      time.value = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`; hands();
    }); clock.append(button);
  }
  hourMode.onclick=()=>{mode='hour';hands();};minuteMode.onclick=()=>{mode='minute';hands();};
  period.onclick=()=>{let [h,m]=time.value.split(':').map(Number);time.value=`${String((h+12)%24).padStart(2,'0')}:${String(m).padStart(2,'0')}`;hands();};
  time.addEventListener('input',hands); hands();
  open.onclick=()=>{form.hidden=!form.hidden;open.setAttribute('aria-expanded',String(!form.hidden));if(!form.hidden)date.focus();};
  function render(items) {
    options.replaceChildren();
    if (!items.length) { const p=document.createElement('p');p.textContent='Пока нет предложений. Запланируй первую игру!';options.append(p); }
    for (const item of items) {
      const card=document.createElement('article');card.className='game-option';
      const text=document.createElement('div'), when=document.createElement('time');when.dateTime=item.starts_at;
      when.textContent=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(item.starts_at));
      const count=document.createElement('small');count.textContent=`МСК · Голосов: ${item.votes}`;text.append(when,count);
      const vote=document.createElement('button');vote.type='button';vote.textContent=item.voted?'Снять голос':'Мне подходит';vote.setAttribute('aria-pressed',String(item.voted));
      vote.onclick=async()=>{vote.disabled=true;try{await request('/api/vote',{option_id:item.id,voted:!item.voted});await refresh();message(item.voted?'Голос снят.':'Голос учтён.');}catch(e){message(e.message,true);}finally{vote.disabled=false;}};
      card.append(text,vote);options.append(card);
    }
  }
  async function refresh() {
    if(refreshing)return;refreshing=true;
    try {const body=await request('/api/options');if(!Array.isArray(body.options))throw new Error('Некорректный ответ сервиса.');render(body.options);available=true;document.querySelector('#propose-game').disabled=false;}
    catch(e){available=false;document.querySelector('#propose-game').disabled=true;message('Общее голосование ещё не подключено на этом адресе. Можно выбрать дату и время, но публикация вариантов и голоса станут доступны после запуска сервера.',true);}
    finally{refreshing=false;}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!available)return;
    const value=`${date.value}T${time.value}:00+03:00`;
    if(!date.value||!time.value||new Date(value)<=new Date()){message('Выбери будущую дату и время.',true);return;}
    const submit=document.querySelector('#propose-game');submit.disabled=true;
    try {await request('/api/options',{starts_at:value});await refresh();message('Вариант добавлен. Теперь за него можно голосовать.');}
    catch(e){message(e.message,true);}finally{submit.disabled=!available;}
  });
  refresh().then(()=>{if(available)message('Общее расписание подключено. Все даты и время — по Москве.');});
  setInterval(()=>{if(!document.hidden)refresh();},15000);
})();
