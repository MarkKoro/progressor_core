/* Own-account connection preferences. Canonical asset in progressor_core/shared. */
(() => {
  'use strict';
  const source=document.currentScript?.dataset.progressorSource;
  const names={food:'Food',gym:'Gym Diary',supply:'Supply'};
  let dialog,content,notice,opener,current,busy=false;
  const el=(tag,text,parent)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;};
  async function api(path,body){
    const r=await fetch('/progressor/api/v1/me/connections'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
    if(!r.ok){let v;try{v=await r.json();}catch{}throw new Error(v?.detail||'Связь временно недоступна. Попробуйте позже.');}return r.json();
  }
  function button(label,parent,action){const b=el('button',label,parent);b.type='button';b.addEventListener('click',async()=>{if(busy)return;busy=true;b.disabled=true;notice.textContent='';try{await action();}catch(e){notice.textContent=String(e.message||e);}finally{busy=false;b.disabled=false;}});return b;}
  function toggle(label,parent,value){const row=el('label',undefined,parent);row.className='link-toggle';const check=el('input',undefined,row);check.type='checkbox';check.checked=!!value;el('span',label,row);return check;}
  function section(title,parent){const d=el('details',undefined,parent);el('summary',title,d);return d;}
  async function refresh(){current=await api('');render();}
  async function save(patch){const value=await api('',{action:'preferences',revision:current.preferences.revision,patch});current.preferences=value.preferences;render();notice.textContent='Настройки сохранены.';}
  function render(){
    const focus=document.activeElement?.dataset?.linkField;content.replaceChildren();const p=current.preferences;
    el('p',p.rest_active?'Сейчас отдых. Напоминания и автоматические подсказки приостановлены. Срок подписки продолжается.':'Вы выбираете, какие продукты помогают друг другу. Записи остаются у каждого продукта.',content);
    const rest=el('div',undefined,content);rest.className='link-actions';
    button(p.rest_active?'Вернуться к обычному режиму':'Отдохнуть от напоминаний',rest,()=>save({paused:!p.rest_active,pause_until:null}));
    const connections=section('Связи и напоминания',content);connections.open=true;
    const sources={};for(const s of ['food','gym','supply'])sources[s]=toggle(names[s]+' участвует в связях',connections,p.sources[s]);
    const hints=toggle('Подсказки в приложениях',connections,p.hints);
    const notifications=toggle('Обычные напоминания во всех продуктах',connections,p.notifications);
    const weight=toggle('Food напоминает проверить цель после нового веса Supply',connections,p.weight_notifications);
    const goal=toggle('Предлагать связанные действия после смены цели',connections,p.goal_links);
    const frequency=el('label','Частота подсказок ',connections);const select=el('select',undefined,frequency);
    for(const [v,t] of [['normal','Обычная'],['quiet','Меньше подсказок']]){const o=el('option',t,select);o.value=v;}select.value=p.frequency;
    button('Сохранить связи',connections,()=>save({sources:Object.fromEntries(Object.entries(sources).map(([s,n])=>[s,n.checked])),hints:hints.checked,notifications:notifications.checked,weight_notifications:weight.checked,goal_links:goal.checked,frequency:select.value}));
    const weekly=section('Один план питания в неделю',content);
    const weeklyOn=toggle('Присылать недельную сводку в Food',weekly,p.weekly_plan);
    const weeklyDay=el('select',undefined,weekly);weeklyDay.setAttribute('aria-label','День сводки');
    for(const [v,t] of [['monday','Понедельник'],['sunday','Воскресенье']]){const o=el('option',t,weeklyDay);o.value=v;}weeklyDay.value=p.weekly_day;
    const hour=el('select',undefined,weekly);hour.setAttribute('aria-label','Час по вашему времени');for(let h=8;h<=20;h++){const o=el('option',String(h).padStart(2,'0')+':00',hour);o.value=h;}hour.value=p.weekly_hour;
    el('small','По умолчанию понедельник, 10:00, по часовому поясу уведомлений Food. Всего одно сообщение за неделю; при отдыхе оно не отправляется. Подтверждение полноты дня добровольное.',weekly);
    button('Сохранить время сводки',weekly,()=>save({weekly_plan:weeklyOn.checked,weekly_day:weeklyDay.value,weekly_hour:Number(hour.value)}));
    button('Предпросмотр моей недели',weekly,async()=>{const v=await api('/weekly-plan');weekly.querySelector('[data-plan-preview]')?.remove();const box=el('p',v.text,weekly);box.dataset.planPreview='';box.style.whiteSpace='pre-line';});
    const rhythm=section('Питание по привычным дням тренировок',content),r=current.rhythm;
    el('p',r.proposal.message,rhythm);
    if(r.active){el('p','Ритм подтверждён. Общая сумма калорий за неделю сохранена. При смене цели, системы тренировок, отключении связи или окончании срока вернётся обычная цель.',rhythm);button('Вернуться к одинаковой цели каждый день',rhythm,async()=>{await api('',{action:'rhythm_off'});await refresh();});}
    else if(r.proposal.status==='proposal'){
      const labels=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];el('p','Повторяются: '+r.proposal.weekdays.map(d=>labels[d]).join(', ')+'. Это предварительное наблюдение за двумя неделями.',rhythm);
      for(const plan of r.proposal.previews){const box=el('div',undefined,rhythm);el('p',plan.training_extra_kcal===0?'Подтвердить ритм без изменения КБЖУ':`В день тренировки +${plan.training_extra_kcal} ккал; в остальные дни меньше на ту же недельную сумму. Белок и жиры остаются прежними.`,box);el('small',plan.days.map((d,i)=>labels[i]+': '+Math.round(d.kcal)+' ккал').join(' · '),box);button('Подтвердить этот вариант на 28 дней',box,async()=>{await api('',{action:'rhythm',fingerprint:r.proposal.fingerprint,base_goal_key:r.proposal.base_goal_key,extra:plan.training_extra_kcal});await refresh();notice.textContent='Ритм подтверждён. Food применит выбранный вариант после синхронизации. Недельная сумма сохранена.';});}
    }
    const atlas=section('Найти нутриент в еде',content);
    const clock=section('Проверить часовой пояс напоминаний',content);
    el('p','Проверьте местное время перед сохранением. Настройка применяется к '+names[source]+'. История не переносится на другие даты.',clock);
    const tzSelect=el('select',undefined,clock);tzSelect.setAttribute('aria-label','Новый часовой пояс');
    const zones=['UTC','Europe/Moscow','Asia/Bangkok','Europe/London','Europe/Berlin','Asia/Dubai','Asia/Tokyo','America/New_York','America/Los_Angeles','Australia/Sydney'];
    const detected=Intl.DateTimeFormat().resolvedOptions().timeZone;if(detected&&!zones.includes(detected))zones.push(detected);
    for(const value of zones){const o=el('option',value,tzSelect);o.value=value;}if(detected)tzSelect.value=detected;
    const clockResult=el('div',undefined,clock);
    async function clockApi(body){const prefix=source==='gym'?(location.pathname.startsWith('/gymapp_prod')?'/gymapi_prod':'/gymapi'):source==='supply'?'/supply/api':'/api';const r=await fetch(prefix+'/integrations/timezone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw new Error('Проверьте пояс и обновите предпросмотр.');return r.json();}
    button('Предпросмотр времени',clock,async()=>{const selected=tzSelect.value;const v=await clockApi({action:'preview',timezone:selected});clockResult.replaceChildren();
      el('p','Сейчас: '+v.current_timezone+' · '+v.clock_before,clockResult);el('p','После изменения: '+selected+' · '+v.clock_after,clockResult);
      for(const slot of v.slots)el('small',slot,clockResult);el('small',v.note,clockResult);
      button('Подтвердить новый пояс',clockResult,async()=>{if(tzSelect.value!==selected)throw new Error('Выбран другой пояс. Обновите предпросмотр.');await clockApi({action:'apply',timezone:selected,expected_timezone:v.current_timezone});clockResult.textContent='Новый пояс сохранён. Будущие напоминания используют его; история сохранена.';});
    });
    button('Выбрать нутриент',atlas,async()=>{const r=await api('/foods');atlas.querySelector('[data-atlas]')?.remove();const box=el('div',undefined,atlas);box.dataset.atlas='';const list=el('select',undefined,box);list.setAttribute('aria-label','Нутриент');for(const item of r.items){const o=el('option',item.name,list);o.value=item.code;}const result=el('div',undefined,box);button('Показать пищевые источники',box,async()=>{const v=await api('/foods/'+encodeURIComponent(list.value));result.replaceChildren();el('h3',v.name,result);for(const i of v.items)el('p','• '+i.name,result);el('small',v.note,result);const a=el('a','Источник справки',result);a.href=v.source_url;a.target='_blank';a.rel='noopener noreferrer';});});
    const food=section('Пищевые предпочтения',content);const diet=el('select',undefined,food);diet.setAttribute('aria-label','Тип питания');
    for(const [v,t] of [['any','Без выбранного ограничения'],['vegetarian','Вегетарианское'],['vegan','Веганское']]){const o=el('option',t,diet);o.value=v;}diet.value=p.diet;
    el('p','Исключения фильтруют пищевые примеры. Состав конкретного товара всегда проверьте на этикетке.',food);
    const groups={};const labels={fish:'Рыба',shellfish:'Моллюски и ракообразные',meat:'Мясо',poultry:'Птица',eggs:'Яйца',dairy:'Молочные продукты',soy:'Соя',nuts:'Орехи',gluten:'Продукты с глютеном',sesame:'Кунжут'};
    for(const g of current.food_groups)groups[g]=toggle('Исключить: '+labels[g],food,p.excluded_food_groups.includes(g));
    button('Сохранить предпочтения',food,()=>save({diet:diet.value,excluded_food_groups:Object.entries(groups).filter(([,n])=>n.checked).map(([g])=>g)}));
    const weights=current.weight.items;
    const profile=section(current.weight.conflict?'Уточнить разный вес в профилях':'Вес и источники профиля',content);
    if(!weights.length)el('p','Свежих согласованных данных о весе пока нет. Заполните собственный профиль и включите нужную связь.',profile);
    for(const item of weights){
      el('p',`${names[item.source]}: ${item.value} кг · ${new Date(item.observed_at).toLocaleDateString('ru-RU')}`,profile);
      button('Использовать '+item.value+' кг в профилях',profile,async()=>{
        const value=await api('',{action:'weight',event_id:item.event_id,fingerprint:current.weight.fingerprint,operation_id:crypto.randomUUID()});
        const box=el('div',undefined,profile);box.setAttribute('role','status');
        const display=v=>{box.textContent=v.complete?'Вес согласован во всех выбранных профилях.':v.items.map(i=>names[i.source]+': '+({pending:'обновляется',applied:'сохранён',conflict:'профиль успел измениться — нужен новый выбор',consent_required:'нужно согласие в продукте',missing_owner:'профиль не найден',expired:'подтверждение истекло'}[i.status]||i.status)).join('; ');};
        display(value);let count=0;const poll=setInterval(async()=>{if(++count>12||!dialog.open){clearInterval(poll);return;}try{const v=await api('/weight/'+value.operation_id);display(v);if(v.items.every(i=>i.status!=='pending'))clearInterval(poll);}catch{clearInterval(poll);box.textContent='Результат уточняется. Исходные данные сохранены.';}},5000);
      });
    }
    el('small',current.weight.explanation,profile);
    const coach=section('Что видит мой тренер',content);el('p',current.coach.explanation,coach);
    if(!current.coach.items.length)el('p','Сначала подтвердите связь с тренером в Gym Diary.',coach);
    for(const item of current.coach.items){
      const row=el('div',undefined,coach);el('strong',item.label,row);
      const macros=toggle('Разрешить дневные КБЖУ',row,item.macros);const dishes=toggle('Отдельно разрешить пять частых блюд',row,item.top_dishes);
      const duration=el('select',undefined,row);duration.setAttribute('aria-label','Срок разрешения');
      for(const days of [7,30,90]){const option=el('option',days+' дней',duration);option.value=days;}duration.value=30;
      if(item.expires_at)el('small','Разрешение до '+new Date(item.expires_at*1000).toLocaleDateString('ru-RU'),row);
      button('Сохранить разрешения',row,async()=>{await api('',{action:'coach',coach_id:item.coach_id,macros:macros.checked,top_dishes:macros.checked&&dishes.checked,days:Number(duration.value)});await refresh();notice.textContent='Разрешения обновлены.';});
      button('Отозвать доступ к питанию',row,async()=>{await api('',{action:'coach',coach_id:item.coach_id,macros:false,top_dishes:false,days:30});await refresh();notice.textContent='Доступ к питанию отозван.';});
    }
    const overview=section('Моя неделя',content);button('Показать недельный обзор',overview,async()=>{
      const v=await api('/weekly');overview.querySelector('[data-week]')?.remove();const box=el('div',undefined,overview);box.dataset.week='';
      if(v.nutrition){const n=v.nutrition,a=n.averages_on_logged_days;el('p',`Food: ${n.logged_days} записанных дней из 7. В среднем по ним: ${a.kcal??'—'} ккал; Б ${a.protein??'—'}, Ж ${a.fat??'—'}, У ${a.carbs??'—'} г.`,box);}
      if(v.workouts)el('p',`Gym Diary: ${v.workouts.recorded_sessions} сессий, ${v.workouts.completed_sessions} завершены; рабочих подходов ${v.workouts.working_sets}.`,box);
      if(v.supply)el('p',`Supply: ${v.supply.active_supplements} активных добавок; отметок приёма за неделю ${v.supply.recorded_intakes}.`,box);
      if(!v.nutrition&&!v.workouts&&!v.supply)el('p','Для обзора нужны свежие данные и доступ к выбранным продуктам.',box);el('small',v.coverage,box);
    });
    const help=section('Как это работает',content);for(const item of current.help){const d=section(item.title,help);el('p',item.text,d);}
    if(source==='supply'){
      const anchors=section('Напоминать о приёме после еды',content);
      el('p','Добровольная связь Food и Supply. Вы выбираете конкретный приём; при отсутствии записи еды остаётся обычное расписание.',anchors);
      button('Выбрать приём',anchors,async()=>{
        const r=await fetch('/supply/api/integrations/meal-anchors',{cache:'no-store'});if(!r.ok)throw new Error('Расписание Supply временно недоступно');const v=await r.json();
        anchors.querySelector('[data-meal-anchors]')?.remove();const box=el('div',undefined,anchors);box.dataset.mealAnchors='';
        if(!v.items.length)el('p','Сначала добавьте добавку и настройте время приёма.',box);
        for(const item of v.items){el('strong',item.name,box);el('small',item.note,box);for(const slot of item.slots){
          const check=toggle(slot.time+' · после записи еды',box,slot.enabled);
          button('Сохранить приём '+slot.time,box,async()=>{const res=await fetch('/supply/api/integrations/meal-anchors',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({supplement_id:item.supplement_id,time:slot.time,enabled:check.checked})});if(!res.ok)throw new Error('Приём изменился — обновите расписание.');notice.textContent='Выбор сохранён. Доза и запасное время сохраняются.';});
        }}
      });
      const overlap=section('Состав добавок и возможные пересечения',content);
      el('p','Проверяем ваш активный план и вещества с подтверждённой этикетки. Дозы и расписание сохраняются.',overlap);
      button('Проверить мой план',overlap,async()=>{
        const response=await fetch('/supply/api/integrations/supplements',{cache:'no-store'});if(!response.ok)throw new Error('Проверка Supply временно недоступна');const v=await response.json();
        overlap.querySelector('[data-overlap]')?.remove();const box=el('div',undefined,overlap);box.dataset.overlap='';
        for(const w of v.warnings)el('p',w.message,box);
        if(!v.warnings.length)el('p','Подтверждённых пересечений не найдено. Неизвестный состав не означает отсутствие пересечения.',box);
        el('small',v.note+' Без подтверждённого состава: '+v.unknown_composition_count,box);
        const choose=el('select',undefined,box);choose.setAttribute('aria-label','Моя добавка');
        for(const i of v.items){const o=el('option',i.name,choose);o.value=i.id;}
        const editor=el('div',undefined,box);
        button('Уточнить по этикетке',box,async()=>{
          editor.replaceChildren();const item=v.items.find(i=>String(i.id)===choose.value);if(!item)return;
          el('p',item.name+' · добавляйте только вещества, которые указаны на вашей этикетке.',editor);const fields=[];
          const registry=await api('/foods');const form=el('div',undefined,editor);
          function row(value={}){const d=el('div',undefined,form),code=el('select',undefined,d);code.setAttribute('aria-label','Вещество');
            for(const n of registry.items){const o=el('option',n.name,code);o.value=n.code;}if(value.code)code.value=value.code;
            const chemical=el('input',undefined,d);chemical.placeholder='Форма по этикетке (необязательно)';chemical.maxLength=80;chemical.value=value.form||'';chemical.setAttribute('aria-label','Форма вещества');
            const amount=el('input',undefined,d);amount.type='number';amount.min=0;amount.step='any';amount.placeholder='Количество по этикетке (необязательно)';amount.value=value.amount??'';amount.setAttribute('aria-label','Количество вещества');
            const unit=el('select',undefined,d);unit.setAttribute('aria-label','Единица этикетки');for(const u of ['g','mg','ug','IU']){const o=el('option',({g:'г',mg:'мг',ug:'мкг',IU:'МЕ'})[u],unit);o.value=u;}unit.value=value.unit||'mg';
            const field={d,code,chemical,amount,unit,removed:false};fields.push(field);button('Убрать вещество',d,()=>{field.removed=true;d.remove();});}
          for(const value of item.entries)row(value);button('Добавить вещество с этикетки',editor,()=>{if(fields.filter(f=>!f.removed).length<16)row();});
          button('Подтвердить состав',editor,async()=>{const entries=fields.filter(f=>!f.removed).map(f=>({code:f.code.value,form:f.chemical.value||null,amount:f.amount.value===''?null:Number(f.amount.value),unit:f.amount.value===''?null:f.unit.value}));
            const r=await fetch('/supply/api/integrations/supplements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({supplement_id:item.id,revision:item.revision,entries})});if(!r.ok)throw new Error('Состав изменился. Обновите проверку и подтвердите ещё раз.');editor.textContent='Состав подтверждён. Можно снова проверить план; дозы и расписание сохранены.';});
        });
      });
    }
    if(source==='food'){
      const day=section('Итог дня без обязательных отметок',content);
      const prompt=toggle('Спрашивать о последнем приёме в подходящий вечер',day,p.day_prompt);
      button('Сохранить настройку вопроса',day,()=>save({day_prompt:prompt.checked}));
      button('Посмотреть предварительный итог',day,async()=>{const response=await fetch('/api/day-status',{cache:'no-store'});if(!response.ok)throw new Error('Итог дня недоступен');const v=await response.json();day.querySelector('[data-day-status]')?.remove();const box=el('div',undefined,day);box.dataset.dayStatus='';el('p',v.message,box);if(v.totals)el('p',`${Math.round(v.totals.kcal)} ккал; Б ${v.totals.protein}, Ж ${v.totals.fat}, У ${v.totals.carbs} г · ${v.meal_count} приёмов`,box);if(!v.complete&&v.meal_count)button('На сегодня всё',box,async()=>{const r=await fetch('/api/day-status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({day:v.day})});if(!r.ok)throw new Error('Проверьте выбранный день');box.textContent='День подтверждён. Новое или изменённое блюдо снова откроет дневник.';});});
      const recent=section('Выбрать из последних 6 приёмов',content);button('Показать недавние блюда',recent,async()=>{
        const r=await fetch('/api/meals/recent');if(!r.ok)throw new Error('Не удалось получить ваши блюда');const data=await r.json();recent.querySelector('[data-recent-list]')?.remove();const list=el('div',undefined,recent);list.dataset.recentList='';
        if(!data.items.length)el('p','Сохраните первое блюдо по фото или описанию.',list);
        for(const meal of data.items){const box=el('div',undefined,list);el('p',meal.name+' · '+Math.round(meal.totals.kcal)+' ккал',box);const portions=el('select',undefined,box);portions.setAttribute('aria-label','Размер порции');for(const p of [.5,1,1.5,2]){const o=el('option','× '+p,portions);o.value=p;}portions.value=1;
          button('Выбрать порцию',box,async()=>{const response=await fetch('/api/meals/recent/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({meal_id:meal.id,portion:Number(portions.value)})});if(!response.ok)throw new Error('Исходное блюдо недоступно');const v=await response.json();box.querySelector('[data-confirm-recent]')?.remove();const confirm=el('div',undefined,box);confirm.dataset.confirmRecent='';el('p',`${v.name} × ${v.portion}: ${Math.round(v.totals.kcal)} ккал. ${v.note}`,confirm);button('Подтвердить и добавить',confirm,async()=>{const result=await fetch('/api/meals/recent/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:v.id})});if(!result.ok)throw new Error('Блюдо изменилось или выбор истёк. Выберите порцию снова.');confirm.textContent='Приём сохранён. Состав учтён без нового расчёта ИИ.';window.dispatchEvent(new Event('progressor:meal-saved'));});});
        }
      });
    }
    if(focus)content.querySelector('[data-link-field="'+CSS.escape(focus)+'"]')?.focus();
  }
  async function open(){
    opener=document.activeElement;
    if(!dialog){
      const style=el('style',`#progressor-connections{box-sizing:border-box;width:min(94vw,620px);max-height:88vh;border:1px solid var(--border,#46516b);border-radius:18px;background:var(--card,#14213d);color:var(--text,#fff);padding:18px;font:15px system-ui}#progressor-connections::backdrop{background:#0009}#progressor-connections button{box-sizing:border-box;min-height:44px;border:1px solid var(--border,#64748b);border-radius:10px;padding:9px 12px;margin:5px 0;background:var(--card,#243657);color:inherit;font:inherit;cursor:pointer}#progressor-connections select{max-width:100%;min-height:44px;margin:8px;border-radius:8px;background:var(--card,#243657);color:inherit;padding:8px}#progressor-connections details{padding:10px 0;border-top:1px solid var(--border,#46516b)}#progressor-connections summary{cursor:pointer;min-height:38px;display:flex;align-items:center;font-weight:600}#progressor-connections .link-toggle{display:flex;align-items:center;gap:10px;min-height:44px;margin:5px 0}#progressor-connections input[type=checkbox]{width:22px;height:22px;flex:none}#progressor-connections small{display:block;line-height:1.5;opacity:.85}#progressor-connections p{line-height:1.5}#progressor-connections :focus-visible{outline:3px solid #60a5fa;outline-offset:2px}`,document.head);
      dialog=el('dialog',undefined,document.body);dialog.id='progressor-connections';dialog.setAttribute('aria-labelledby','progressor-link-title');el('h2','Связь продуктов',dialog).id='progressor-link-title';notice=el('p',undefined,dialog);notice.setAttribute('role','status');content=el('div',undefined,dialog);
      // Host card colors can be translucent; the modal needs an opaque surface.
      el('style','#progressor-connections{background:#14213d;color:#f1f5f9}#progressor-connections,#progressor-connections *{font-family:system-ui,-apple-system,"Segoe UI",sans-serif!important}#progressor-connections input:not([type=checkbox]){box-sizing:border-box;max-width:100%;min-height:44px;padding:8px;border:1px solid #64748b;border-radius:8px;background:#243657;color:#f1f5f9}',document.head);
      button('Закрыть',dialog,async()=>dialog.close());dialog.addEventListener('close',()=>opener?.focus());
    }
    if(!dialog.open)dialog.showModal();notice.textContent='Загружаем ваши настройки…';
    try{await window.Progressor?.ready;await refresh();notice.textContent='';}catch(e){notice.textContent=e.message;}
  }
  window.Progressor=window.Progressor||{};window.Progressor.openConnections=open;
  document.addEventListener('progressor:open-connections',open);
})();
