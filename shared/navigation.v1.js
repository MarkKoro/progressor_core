/* Progressor shell v1. Contracts and rollback instructions: docs/PROGRESSOR_INTEGRATION.md. */
(() => {
  'use strict';
  const source = document.currentScript?.dataset.progressorSource;
  const routes = {gym: '/gymapp_prod/', food: '/webapp/', supply: '/supply/'};
  const apiPrefixes = {gym: '/gymapi_prod/', food: '/api/', supply: '/supply/api/'};
  if (!routes[source]) return;
  const storageKey = 'progressor.launch.v1';
  const rawFetch = window.fetch.bind(window);
  const localBridge=window.Progressor?._launchBridge?.source===source?window.Progressor._launchBridge:null;
  const readStorage = () => { try { return JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch (_) { return {}; } };
  const saveStorage = () => { try { sessionStorage.setItem(storageKey, JSON.stringify(saved)); } catch (_) {} };
  const fromUrl = () => {
    for (const raw of [location.search, location.hash.replace(/^#/, '')]) {
      const params = new URLSearchParams(raw);
      const value = params.get('tgWebAppData') || params.get('initData');
      if (value) return value;
    }
    return '';
  };
  let saved = localBridge ? localBridge.getState() : readStorage();
  const launched = fromUrl() || window.Telegram?.WebApp?.initData || '';
  if (!localBridge && launched && launched !== saved.launchData) {
    saved = {source, launchData: launched};
    saveStorage();
  }
  const sessionValid = () => localBridge ? localBridge.sessionValid() : saved.session?.assertions && saved.session.expires_at > Date.now() / 1000 + 5;
  const canNavigate = () => !localBridge || localBridge.canNavigate();
  let availableDomains = saved.session?.enabled_domains || [];
  let renewing;
  async function bootstrap(force = false) {
    if(localBridge){const result=await localBridge.bootstrap(force);saved=localBridge.getState();availableDomains=saved.session?.enabled_domains||[];return result;}
    if (!force && sessionValid()) return saved.session;
    if (renewing) return renewing;
    renewing = (async () => {
      if (!saved.launchData || !routes[saved.source]) return null;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 1500);
      try {
        const response = await rawFetch('/progressor/api/v1/sessions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source: saved.source, init_data: saved.launchData}), signal: controller.signal, cache: 'no-store'});
        if (!response.ok) return null;
        const data = await response.json();
        if (!data.assertions || !data.expires_at) return null;
        saved.session = data;
        availableDomains = data.enabled_domains || [];
        saveStorage();
        return data;
      } catch (_) { return null; }
      finally { clearTimeout(timeout); }
    })();
    try { return await renewing; } finally { renewing = null; }
  }
  const ready = bootstrap();
  if(!localBridge){
   window.Progressor = {launchData: saved.launchData || '', ready, renew: bootstrap};
   window.fetch = async (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    const audience = url.origin === location.origin && url.pathname.startsWith(apiPrefixes[source]) ? source : url.origin === location.origin && url.pathname.startsWith('/progressor/api/v1/me/') ? 'core' : null;
    if (!audience) return rawFetch(input, options);
    const session = await bootstrap();
    if (!session || !sessionValid()) return rawFetch(input, options);
    const headers = new Headers(input instanceof Request ? input.headers : undefined);
    new Headers(options.headers || {}).forEach((value, key) => headers.set(key, value));
    headers.set('X-Progressor-Auth', session.assertions[audience]);
    return rawFetch(input, {...options, headers});
   };
  }

  // Colour scheme follows Telegram; the chosen theme is shared by all three products on this device.
  const themes = ['classic', 'sand', 'graphite', 'ocean', 'forest'];
  function applyLook() {
    const root = document.documentElement, tg = window.Telegram?.WebApp;
    const scheme = tg?.colorScheme === 'dark' || (!tg?.colorScheme && window.matchMedia?.('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
    let theme = 'classic'; try { theme = localStorage.getItem('progressor.theme') || 'classic'; } catch {}
    if (!themes.includes(theme)) theme = 'classic';
    root.dataset.pgScheme = scheme;
    if (theme === 'classic') delete root.dataset.pgTheme; else root.dataset.pgTheme = theme;
    try { localStorage.setItem('progressor.scheme', scheme); } catch {}
    if (root.dataset.pgUi === '2') { try { const colour = getComputedStyle(root).getPropertyValue('--pg-bg').trim(); if (colour) { tg?.setHeaderColor?.(colour); tg?.setBackgroundColor?.(colour); } } catch {} }
  }
  applyLook();
  try { window.Telegram?.WebApp?.onEvent?.('themeChanged', applyLook); } catch {}
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', applyLook);
  new MutationObserver(applyLook).observe(document.documentElement, {attributes: true, attributeFilter: ['data-pg-ui']});
  // Real 3D: a pressed tile tilts toward the finger in perspective and settles back.
  if (!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    let tilted = null;
    const settle = () => { if (!tilted) return; tilted.style.transition = 'transform .45s cubic-bezier(.2,.9,.3,1.2)'; tilted.style.transform = ''; const done = tilted; tilted = null; setTimeout(() => { if (tilted !== done) done.style.transition = ''; }, 500); };
    const lean = event => {
      const tile = event.target.closest?.('.ph-tile,.u2-hero,.u2-tile');
      if (!tile || document.documentElement.dataset.pgUi !== '2' && !tile.closest('#progressor-home')) { settle(); return; }
      if (tilted && tilted !== tile) settle();
      const box = tile.getBoundingClientRect(), x = (event.clientX - box.left) / box.width - .5, y = (event.clientY - box.top) / box.height - .5;
      tilted = tile; tile.style.transition = 'transform .08s linear';
      tile.style.transform = `perspective(700px) rotateX(${(-y * 9).toFixed(2)}deg) rotateY(${(x * 9).toFixed(2)}deg) scale(.985)`;
    };
    document.addEventListener('pointerdown', lean, {passive: true});
    document.addEventListener('pointermove', event => { if (tilted && event.buttons !== 0 || event.pointerType === 'mouse' && event.target.closest?.('.ph-tile,.u2-hero')) lean(event); else if (tilted && event.pointerType === 'mouse') settle(); }, {passive: true});
    for (const name of ['pointerup', 'pointercancel', 'pointerleave']) document.addEventListener(name, settle, {passive: true});
    window.addEventListener('scroll', settle, {passive: true, capture: true});
  }
  window.Progressor.themes = themes;
  window.Progressor.theme = () => document.documentElement.dataset.pgTheme || 'classic';
  window.Progressor.setTheme = name => { if (!themes.includes(name)) return; try { if (name === 'classic') localStorage.removeItem('progressor.theme'); else localStorage.setItem('progressor.theme', name); } catch {} applyLook(); };

  // A purpose marker selects only an existing native view. It never grants access.
  // The sole continuation record is tab-local, short-lived and bound to the launch.
  const transferKey='progressor.transfer.v1',transferTtl=10*60*1000;
  const actionDomains={food_goal:'food',food_log:'food',open_food:'food',gym_plan:'gym',gym_today:'gym',gym_free:'gym',supply_plan:'supply',supply_catalog:'supply'};
  const returnViews={food:['today','analytics','subscription'],gym:['today','settings','library','allExercises','measurements','achievements','teams','subscription'],supply:['today','catalog','profile','achievements']};
  const arrivalParams=new URLSearchParams(location.search);
  const arrivalAction=arrivalParams.get('progressor_action'),arrivalReturn=arrivalParams.get('progressor_return');
  let interactionRevision=0;
  for(const event of ['pointerdown','keydown','input','change'])document.addEventListener(event,()=>{interactionRevision++;},true);
  window.Progressor.interactionRevision=()=>interactionRevision;
  const currentAuth=()=>{const state=localBridge?localBridge.getState():saved;return {owner:String(state.session?.user?.id||''),proof:state.launchData||''};};
  const sameAuth=(a,b=currentAuth())=>!!a.owner && a.owner===b.owner && a.proof===b.proof;
  function cleanAction(action){
    if(!action || !Object.hasOwn(actionDomains,action.kind))return null;
    if(action.kind==='supply_catalog')return ['железо','B12'].includes(action.query)?{kind:action.kind,query:action.query}:null;
    return {kind:action.kind};
  }
  function readTransfer(){try{return JSON.parse(sessionStorage.getItem(transferKey)||'null');}catch{return null;}}
  function clearTransfer(){try{sessionStorage.removeItem(transferKey);}catch{}}
  function writeTransfer(value){try{sessionStorage.setItem(transferKey,JSON.stringify(value));return sessionStorage.getItem(transferKey)===JSON.stringify(value);}catch{return false;}}
  async function authBinding(){
    const auth=currentAuth();
    if(!auth.owner || !auth.proof || !window.crypto?.subtle)return null;
    try{const bytes=await window.crypto.subtle.digest('SHA-256',new TextEncoder().encode(auth.proof));
      return sameAuth(auth)?{owner:auth.owner,proof_digest:Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('')}:null;
    }catch{return null;}
  }
  async function validTransfer(record){
    if(!record || record.version!==1 || !Object.hasOwn(routes,record.from) || !Object.hasOwn(routes,record.to) || record.from===record.to || !returnViews[record.from].includes(record.view) || !['outbound','active','return'].includes(record.phase) || !Number.isFinite(record.created_at) || !Number.isFinite(record.expires_at) || record.created_at>Date.now() || record.expires_at<=Date.now() || record.expires_at-record.created_at>transferTtl || !cleanAction(record.action) || actionDomains[record.action.kind]!==record.to)return false;
    const binding=await authBinding();
    return !!binding && binding.owner===record.owner && binding.proof_digest===record.proof_digest;
  }
  function clearArrivalMarker(){
    if(arrivalAction===null && arrivalReturn===null)return;
    const url=new URL(location.href);url.searchParams.delete('progressor_action');url.searchParams.delete('progressor_return');
    history.replaceState(history.state,'',url.pathname+url.search+url.hash);
  }

  function element(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  }
  function activityText(activity) {
    if (!activity) return '';
    if (activity.reason === 'workout_recorded') return `Тренировки: записей — ${activity.recorded_session_count ?? activity.completed_workout_count}, из них завершённых занятий — ${activity.completed_workout_count}. День в разделе «Еда»: ${activity.date} (${activity.day_timezone}).`;
    if (activity.reason === 'no_completed_workout_recorded') return `Тренировки: за ${activity.date} завершённая тренировка пока не отмечена.`;
    if (activity.reason === 'missing_gym_membership') return 'Данных о тренировках пока нет. Отмечайте завершение тренировки в разделе «Тренировки».';
    return 'Данные раздела «Тренировки» временно недоступны. Питание можно записывать как обычно.';
  }
  function nutritionText(context) {
    const seven = context.nutrition?.history?.['7'];
    if (!seven) return 'Данные раздела «Еда» временно недоступны. Остальные функции продолжают работать.';
    if (!seven.logged_days) return 'Записей питания за последние 7 завершённых дней пока нет.';
    return `Еда: ${seven.logged_days} записанных дней из 7; средний белок по записанным дням — ${seven.averages_on_logged_days.protein} г. Журнал может быть неполным.`;
  }
  const productNames = {food:'Еда', gym:'Тренировки', supply:'БАДы', bundle:'Все вместе'};
  const formatDate = value => value ? new Date(value).toLocaleDateString('ru-RU') : '';
  const money = (value,currency) => currency==='RUB' ? (value/100).toLocaleString('ru-RU')+' ₽' : value.toLocaleString('ru-RU')+' ⭐';
  let subscriptionData = null, subscriptionBox = null, selectedProduct = 'bundle', subscriptionLoading = false, purchaseBusy = false, subscriptionError = '', purchaseOptionsRevision=0;
  function productIcon(source,parent) {
    const paths={food:['M5 14h22a11 11 0 0 1-22 0Z','M10 10V5m6 5V3m6 7V5'],gym:['M8 16h16','M4 10v12m4-15v18m16-18v18m4-15v12'],supply:['M10 6a7 7 0 0 1 10 0l6 9a7 7 0 0 1-10 8l-6-9a7 7 0 0 1 0-8Z','M12 13l10-7'],bundle:['M16 5v10M6 23l10-8 10 8','M19 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM9 25a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm20 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z']};
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 32 32');svg.setAttribute('aria-hidden','true');
    for(const value of paths[source]){const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',value);svg.append(p);}parent.append(svg);
  }
  function accessText(p) {
    if(p.state==='unknown') return 'Уточняем доступ';
    if(p.kind==='bundle') return 'Общая подписка · до '+formatDate(p.expires_at);
    if(p.state==='active') return 'Отдельный доступ · до '+formatDate(p.expires_at);
    if(p.state==='trial') return 'Пробный доступ · до '+formatDate(p.expires_at);
    if(p.state==='free') return 'Бесплатный дневник';
    return p.native_until ? 'Истекла '+formatDate(p.native_until) : 'Подписки нет';
  }
  function renderProducts() {
    if(!subscriptionBox) return;
    const grid=subscriptionBox.querySelector('[data-products]');const focusProduct=grid.contains(document.activeElement)?document.activeElement.dataset.product:null;grid.replaceChildren();
    for(const id of ['food','gym','supply','bundle']){
      const p=subscriptionData?.products.find(p=>p.source===id);
      const active=id==='bundle'?subscriptionData?.bundle.active:p?.premium_active;
      const button=element('button',undefined,grid);button.type='button';button.className='progressor-product';button.dataset.product=id;
      button.setAttribute('aria-pressed',String(selectedProduct===id));
      productIcon(id,button);
      element('strong',productNames[id],button);
      const badge=element('span',active?'✓':p?.state==='unknown'||!subscriptionData?'…':p?.state==='trial'?'◷':p?.state==='free'?'○':'＋',button);badge.className='progressor-access-badge';badge.setAttribute('aria-hidden','true');
      const label=id==='bundle'?(!subscriptionData?'Уточняем доступ':subscriptionData.bundle.active?'Общая подписка · до '+formatDate(subscriptionData.bundle.expires_at):'Общей подписки нет'):p?accessText(p):'Уточняем доступ';
      element('small',label,button);
      button.onclick=()=>selectProduct(id);
    }
    if(focusProduct)grid.querySelector('[data-product="'+focusProduct+'"]')?.focus({preventScroll:true});
    const summary=subscriptionBox.querySelector('[data-access-summary]');
    if(!subscriptionData){summary.textContent=subscriptionError||'Проверяем ваши действующие подписки…';return;}
    const active=subscriptionData.products.filter(p=>p.premium_active).map(p=>p.name);
    const inactive=subscriptionData.products.filter(p=>['inactive','free','trial'].includes(p.state)).map(p=>p.name);
    summary.textContent=(active.length?'Уже доступны по подписке: '+active.join(', ')+'. ':subscriptionData.unknown_products.length?'':'Активных подписок пока нет. ')+(inactive.length?'Можно подключить: '+inactive.join(', ')+'. ':'')+(subscriptionData.unknown_products.length?'Часть данных временно недоступна. Уже оплаченный доступ продолжает действовать.':'');
  }
  function ensureSubscriptions(panel) {
    if(subscriptionBox?.isConnected) return subscriptionBox;
    subscriptionBox=element('section',undefined,panel);subscriptionBox.id='progressor-subscriptions';
    const header=element('div',undefined,panel);header.className='progressor-subscription-heading';element('strong','Мои подписки',header);
    const close=element('button','×',header);close.type='button';close.setAttribute('aria-label','Закрыть подписки');close.onclick=()=>{const toggle=document.querySelector('[aria-controls="progressor-context"]');panel.hidden=true;toggle?.setAttribute('aria-expanded','false');toggle?.focus();};
    const summary=element('p','',subscriptionBox);summary.dataset.accessSummary='';summary.setAttribute('aria-live','polite');
    const grid=element('div',undefined,subscriptionBox);grid.dataset.products='';grid.className='progressor-products';
    const detail=element('div',undefined,subscriptionBox);detail.dataset.purchaseOptions='';detail.id='progressor-bundle';
    panel.prepend(header,subscriptionBox);renderProducts();return subscriptionBox;
  }
  async function loadSubscriptions(panel) {
    ensureSubscriptions(panel);if(subscriptionLoading)return;subscriptionLoading=true;
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),2500);
    try{
      const r=await window.fetch('/progressor/api/v1/me/subscriptions',{cache:'no-store',signal:controller.signal});if(!r.ok)throw new Error();
      subscriptionData=await r.json();subscriptionError='';renderProducts();
    }catch(_){subscriptionData=null;subscriptionError='Не удалось обновить список подписок. Попробуйте ещё раз. Текущий продукт продолжает работать.';renderProducts();}
    finally{clearTimeout(timeout);subscriptionLoading=false;}
  }
  function showPaymentState(parent,text) {let state=parent.querySelector('[data-payment-status]');if(!state){state=element('p','',parent);state.dataset.paymentStatus='';state.setAttribute('role','status');}state.textContent=text;return state;}
  function paymentButton(parent,text,currency,plan,callback) {
    const button=element('button',text,parent);button.type='button';button.className='progressor-pay';button.dataset.currency=currency;button.dataset.plan=plan;
    button.addEventListener('click',async()=>{
      if(purchaseBusy)return;purchaseBusy=true;
      const all=[...subscriptionBox.querySelectorAll('.progressor-pay')];all.forEach(b=>b.disabled=true);
      try{await callback(button);}catch(_){subscriptionBox.closest('#progressor-context').hidden=false;document.querySelector('[aria-controls="progressor-context"]')?.setAttribute('aria-expanded','true');showPaymentState(parent.closest('[data-purchase-options]'),'Не удалось подготовить оплату. Если деньги списаны, повторно оплачивать не нужно. Помощь: /paysupport в боте.');}
      finally{purchaseBusy=false;all.forEach(b=>b.disabled=false);subscriptionBox.querySelector('.progressor-terms input')?.dispatchEvent(new Event('change'));}
    });return button;
  }
  function planRow(parent,label) {const row=element('section',undefined,parent);row.className='progressor-plan';element('strong',label,row);const buttons=element('div',undefined,row);buttons.className='progressor-payment-pair';return {row,buttons};}
  function* planContainers(parent,plans){
    const primary=new Set(['m1','1m','m6','6m','m12','12m','y1']);
    const regular=plans.filter(p=>p.id!=='align');
    if(!regular.some(p=>primary.has(p.id)))for(const p of regular.slice(0,3))primary.add(p.id);
    for(const plan of plans)if(primary.has(plan.id)||plan.id==='align')yield {plan,parent};
    const extra=regular.filter(p=>!primary.has(p.id));
    if(extra.length){const more=element('details',undefined,parent);more.className='progressor-other-periods';const summary=element('summary','Другие сроки',more);summary.style.cssText='min-height:44px;display:flex;align-items:center;cursor:pointer';for(const plan of extra)yield {plan,parent:more};}
  }
  async function selectProduct(id) {
    if(purchaseBusy)return;const revision=++purchaseOptionsRevision;selectedProduct=id;renderProducts();
    const box=subscriptionBox.querySelector('[data-purchase-options]');box.replaceChildren();
    if(id==='bundle')return openBundleOptions(box,revision);
    element('h3',productNames[id]+' · отдельная подписка',box);
    const own=subscriptionData?.products.find(p=>p.source===id);if(own)element('p',accessText(own),box);
    element('p','Эта покупка открывает только раздел «'+productNames[id]+'». Для трёх продуктов выберите «Все вместе».',box);
    if(id!==source){
      const button=element('button','Выбрать тариф «'+productNames[id]+'»',box);button.type='button';button.className='progressor-pay';
      button.onclick=async()=>{if(await bootstrap(true)&&sessionValid()&&canNavigate()&&availableDomains.includes(id))location.assign(routes[id]+'?progressor_subscription=1');else showPaymentState(box,'Переход временно недоступен. Откройте '+productNames[id]+' из его бота.');};return;
    }
    const hook=window.ProgressorDomain;
    if(!hook?.subscriptionPlans||!hook?.purchaseSubscription){showPaymentState(box,'Тарифы загружаются. Повторите выбор через несколько секунд.');return;}
    try{
      const plans=await hook.subscriptionPlans();if(revision!==purchaseOptionsRevision||!box.isConnected)return;
      for(const {plan:p,parent} of planContainers(box,plans)){const {buttons}=planRow(parent,p.label);
        if(p.RUB)paymentButton(buttons,money(p.RUB,'RUB'),'RUB',p.id,async button=>{subscriptionBox.closest('#progressor-context').hidden=true;await hook.purchaseSubscription(p.id,'RUB',button);});
        if(p.XTR)paymentButton(buttons,money(p.XTR,'XTR'),'XTR',p.id,async button=>{subscriptionBox.closest('#progressor-context').hidden=true;await hook.purchaseSubscription(p.id,'XTR',button);});
      }if(!plans.length)showPaymentState(box,'Тарифы сейчас недоступны. Попробуйте позже.');
      element('small','Рубли — платёжная страница ЮKassa. Звёзды — счёт Telegram. Без автоматического выбора способа оплаты.',box);
    }catch(_){if(revision===purchaseOptionsRevision)showPaymentState(box,'Не удалось загрузить тарифы. Попробуйте позже.');}
  }
  async function openBundleOptions(box,revision) {
    element('h3','Все вместе · три продукта',box);
    const notice=element('p','Загрузка персональной стоимости…',box);
    try{
      const response=await window.fetch('/progressor/api/v1/me/bundle/catalog',{cache:'no-store'});if(!response.ok)throw new Error();
      const catalog=await response.json();if(revision!==purchaseOptionsRevision||selectedProduct!=='bundle'||!box.isConnected)return;
      if(catalog.subscriptions){subscriptionData=catalog.subscriptions;subscriptionError='';renderProducts();}
      notice.textContent=catalog.limits;
      const accepted=element('label',undefined,box);accepted.className='progressor-terms';const checkbox=element('input',undefined,accepted);checkbox.type='checkbox';accepted.append(document.createTextNode(' Принимаю условия общей подписки'));
      const state=showPaymentState(box,'');
      if(catalog.pending_order){
        state.textContent='Есть неоплаченный счёт. Для другого срока или способа оплаты сначала отмените его. Если деньги списаны, дождитесь подтверждения.';
        if(!catalog.pending_order.checkout_id&&!catalog.pending_order.provider_id){const cancel=element('button','Отменить неоплаченный счёт',box);cancel.type='button';cancel.className='progressor-pay';cancel.onclick=async()=>{cancel.disabled=true;try{const r=await fetch('/progressor/api/v1/me/bundle/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:catalog.pending_order.id})});if(!r.ok)throw new Error();await selectProduct('bundle');}catch(_){state.textContent='Платёж уже проверяется. Дождитесь подтверждения; повторная оплата не нужна.';cancel.disabled=false;}};}
      }
      for(const {plan,parent} of planContainers(box,catalog.plans)){
        const {row,buttons}=planRow(parent,plan.label);
        if(plan.prices.XTR.already_covered&&plan.prices.RUB.already_covered){element('p','Все три продукта уже доступны на этот период. Доплачивать не нужно.',row);continue;}
        const credit=Object.entries(plan.prices).filter(([,p])=>p.credit_amount).map(([c,p])=>money(p.credit_amount,c));
        if(credit.length)element('small','Зачёт действующих оплаченных дней: '+credit.join(' / ')+'. Ниже — итоговая доплата.',row);
        for(const currency of ['RUB','XTR']){
          const price=plan.prices[currency];if(price.already_covered){element('small','На этот период доплата не требуется.',buttons);continue;}
          const button=paymentButton(buttons,money(price.amount,currency),currency,plan.id,async()=>{
            if(!checkbox.checked)return;
            if(currency==='RUB'){
              const url=new URL(catalog.website_url||'/progressor/subscribe',location.origin);url.searchParams.set('source',source);url.searchParams.set('plan',plan.id);
              if(url.origin!==location.origin||url.pathname!=='/progressor/subscribe')throw new Error('invalid_website');
              if(window.Telegram?.WebApp?.openLink)window.Telegram.WebApp.openLink(url.href);else window.open(url.href,'_blank','noopener');
              state.textContent='Открылся сайт оплаты. Подтвердите вход в свой аккаунт; сайт уточнит цену и откроет платёжную страницу ЮKassa.';return;
            }
            state.textContent='Подготовка счёта в звёздах…';
            const r=await fetch('/progressor/api/v1/me/bundle/invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source,plan:plan.id,order_id:crypto.randomUUID(),terms:catalog.terms_version})});if(!r.ok)throw new Error();
            const invoice=await r.json();const completed=async()=>{const result=await fetch('/progressor/api/v1/me/bundle/orders/'+encodeURIComponent(invoice.order_id),{cache:'no-store'});const v=result.ok?await result.json():{};state.textContent=v.status==='paid'?'Оплата подтверждена. Доступ обновится во всех продуктах примерно за 30 секунд.':'Оплата ещё не подтверждена. Если деньги списаны, повторно оплачивать не нужно. /paysupport';const panel=subscriptionBox.closest('#progressor-context');await bootstrap(true);await loadSubscriptions(panel);if(v.status==='paid'&&panel&&!panel.querySelector('[data-paid-link-step]')){const step=element('button','Настроить связь продуктов',panel);step.type='button';step.dataset.paidLinkStep='';step.onclick=()=>window.Progressor.openConnections();}};
            if(window.Telegram?.WebApp?.openInvoice)window.Telegram.WebApp.openInvoice(invoice.invoice_url,()=>completed().catch(()=>{state.textContent='Подтверждение появится после восстановления связи. /paysupport';}));
            else{const link=element('a','Открыть счёт в звёздах в Telegram',box);link.className='progressor-pay';link.href=invoice.invoice_url;link.target='_blank';link.rel='noopener';state.textContent='Счёт готов.';}
          });
          button.disabled=!checkbox.checked||(currency==='RUB'&&!catalog.rub_available);
          checkbox.addEventListener('change',()=>{button.disabled=purchaseBusy||!checkbox.checked||(currency==='RUB'&&!catalog.rub_available);});
        }
      }
      element('small','Рубли — на отдельной платёжной странице ЮKassa. Звёзды — в Telegram. Срок и стоимость подтверждаются до оплаты; автопродления нет.',box);
    }catch(_){if(revision===purchaseOptionsRevision)notice.textContent='Персональные тарифы сейчас недоступны. Ваши подписки и текущий продукт продолжают работать.';}
  }
  async function openBundle(panel) {ensureSubscriptions(panel);const revision=++purchaseOptionsRevision;await loadSubscriptions(panel);if(revision===purchaseOptionsRevision)await selectProduct('bundle');}

  async function mount() {
    document.body.dataset.progressorDomain = source;
    const style = element('style', `
      :root{--progressor-bar-height:48px}
      body[data-progressor-domain="gym"],body[data-progressor-domain="food"]{padding-top:var(--progressor-bar-height)}
      body[data-progressor-domain="gym"] .app-header{top:var(--progressor-bar-height)}
      body[data-progressor-domain="supply"] #app{height:calc(100% - var(--progressor-bar-height));margin-top:var(--progressor-bar-height)}
      #progressor-shell{position:fixed;top:0;left:0;right:0;z-index:24;isolation:isolate;color:#f1f5f9;font:13px system-ui;background:#13213d;border-bottom:1px solid var(--border,#46516b);padding:calc(2px + env(safe-area-inset-top,0px)) 8px 2px;}
      #progressor-shell nav button[hidden]{display:none}
      #progressor-shell nav[data-home]{grid-template-columns:minmax(44px,1fr) minmax(44px,1.3fr) minmax(44px,.7fr) minmax(44px,.8fr) minmax(44px,1.2fr)}
      #progressor-shell nav{display:grid;grid-template-columns:minmax(44px,1.3fr) minmax(44px,.7fr) minmax(44px,.8fr) minmax(44px,1.2fr);gap:4px;max-width:900px;margin:auto;}
      #progressor-shell *{font-family:inherit;box-sizing:border-box}
      #progressor-shell{box-sizing:border-box;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      #progressor-shell a,#progressor-shell button{display:flex;align-items:center;justify-content:center;min-height:48px;border:0;border-radius:10px;color:inherit;background:transparent;text-decoration:none;cursor:pointer;font:600 12px system-ui;}
      #progressor-shell a[aria-current="page"]{background:#2563eb;color:white}
      #progressor-shell nav a,#progressor-shell nav button{min-height:44px;min-width:0;border-radius:8px;padding:4px;white-space:normal;overflow-wrap:anywhere;text-align:center;line-height:1.25}
      #progressor-shell a[aria-disabled="true"]{opacity:.55}
      #progressor-context{position:absolute;top:100%;left:8px;right:8px;max-width:880px;margin:auto;background:#13213d;border:1px solid var(--border,#46516b);border-radius:0 0 14px 14px;padding:14px;box-shadow:0 10px 24px #0004;max-height:65vh;overflow:auto;overscroll-behavior:contain;line-height:1.5}
      #progressor-context[hidden]{display:none}
      #progressor-transfer[hidden]{display:none}
      #progressor-transfer{max-width:900px;margin:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:4px}
      #progressor-transfer p{flex:1 1 180px;margin:0;overflow-wrap:anywhere;line-height:1.4}
      #progressor-transfer button{border:1px solid #64748b;padding:8px 12px;white-space:normal;overflow-wrap:anywhere;text-align:center;max-width:100%}
      #progressor-transfer button:focus-visible{outline:3px solid #60a5fa;outline-offset:2px}
      #progressor-context p{margin:8px 0} #progressor-context a{display:inline-flex;background:#2563eb;color:white;padding:0 12px}
      #progressor-inline-host{margin:12px 0;scroll-margin-top:calc(var(--progressor-bar-height) + 16px)}
      #progressor-inline-host[hidden]{display:none}
      .progressor-hint{position:relative;padding:16px;border-radius:16px;border:1px solid var(--border,#46516b);background:var(--card,transparent);color:inherit;line-height:1.5;font:inherit;overflow-wrap:anywhere}
      .progressor-hint>strong{display:block;padding-right:36px;min-height:28px}
      .progressor-hint p{margin:8px 0;font-size:14px}
      .progressor-hint-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
      .progressor-hint button,.progressor-hint summary{min-height:48px;min-width:48px;cursor:pointer;font:inherit;color:inherit;border-radius:10px;padding:10px 12px}
      .progressor-hint button{border:1px solid var(--border,#46516b);background:transparent;max-width:100%;white-space:normal;overflow-wrap:anywhere}
      .progressor-hint button[data-primary]{background:#2563eb;border-color:#2563eb;color:white}
      .progressor-hint .progressor-dismiss{position:absolute;right:2px;top:2px;border:0;font-size:24px;width:48px;min-height:48px;padding:0;background:transparent}
      .progressor-hint button:focus-visible,#progressor-shell :focus-visible{outline:3px solid #60a5fa;outline-offset:2px}
      .progressor-hint details{margin-top:8px;font-size:13px}
      .progressor-hint .progressor-sources{font-size:12px;opacity:.8}
      .progressor-hint .progressor-example{border-left:2px solid var(--border,#46516b);padding-left:12px}

      #progressor-subscriptions{padding-bottom:16px;border-bottom:1px solid var(--border,#46516b)}
      #progressor-subscriptions h3{margin:16px 0 8px;font-size:16px}
      #progressor-subscriptions small{font-size:12px;line-height:1.45;display:block}
      .progressor-subscription-heading{display:flex;align-items:center;justify-content:space-between;font-size:17px;position:sticky;top:-14px;z-index:2;gap:12px;background:#13213d;margin-top:-14px;padding-top:14px;margin-bottom:8px}
      .progressor-subscription-heading strong{min-width:0;overflow-wrap:anywhere}
      #progressor-shell .progressor-subscription-heading button{flex:none;min-width:44px}
      #progressor-shell .progressor-products{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
      #progressor-shell .progressor-product{position:relative;display:flex;flex-direction:column;justify-content:flex-start;gap:8px;padding:12px 7px;border:1px solid #64748b;background:#1e3152;color:#f1f5f9;min-width:0;text-align:center;white-space:normal;overflow-wrap:anywhere;font-size:13px}
      #progressor-shell .progressor-product[aria-pressed=true]{border:2px solid #60a5fa;padding:11px 6px}
      .progressor-product svg{width:32px;height:32px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
      .progressor-access-badge{position:absolute;right:5px;top:3px;font-size:18px}
      .progressor-plan{padding:12px 0;border-bottom:1px solid var(--border,#46516b)}
      .progressor-payment-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
      #progressor-shell .progressor-pay{display:flex;justify-content:center;align-items:center;min-height:48px;padding:10px 12px;border:1px solid #60a5fa;border-radius:12px;background:#2563eb;color:#fff;font:600 14px system-ui;white-space:normal;overflow-wrap:anywhere;width:100%;text-align:center}
      #progressor-shell .progressor-pay:disabled{opacity:.5;cursor:default}
      .progressor-terms{display:flex;align-items:center;min-height:48px;gap:8px;font-size:13px}
      .progressor-terms input{width:20px;height:20px;flex-shrink:0}
      @media(max-width:480px){#progressor-shell .progressor-products{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(prefers-reduced-motion:reduce){.progressor-hint{scroll-behavior:auto}}

    `, document.head);
    const shell = element('section');
    shell.id = 'progressor-shell';
    const nav = element('nav', undefined, shell);
    nav.setAttribute('aria-label', 'Разделы Progressor');
    const transferBar=element('section',undefined,shell);transferBar.id='progressor-transfer';transferBar.hidden=true;
    transferBar.setAttribute('aria-label','Возврат после перехода');
    const transferStatus=element('p','',transferBar);transferStatus.setAttribute('role','status');
    let activeTransfer=null;
    function transferMessage(message){
      transferBar.hidden=false;transferStatus.textContent=message;
      if(!activeTransfer && !transferBar.querySelector('[data-transfer-close]')){const close=element('button','Закрыть',transferBar);close.type='button';close.dataset.transferClose='';close.onclick=closeTransfer;}
    }
    function closeTransfer(){clearTransfer();activeTransfer=null;transferBar.hidden=true;transferBar.querySelectorAll('button').forEach(b=>b.remove());}
    function showReturn(record){
      activeTransfer=record;transferBar.querySelectorAll('button').forEach(b=>b.remove());
      transferMessage('Открыт '+productNames[source]+'. Возврат доступен в этой вкладке 10 минут. Несохранённые формы не переносятся.');
      const back=element('button','Вернуться в раздел «'+productNames[record.from]+'»',transferBar);back.type='button';back.dataset.progressorReturn='';
      back.onclick=async()=>{
        if(back.disabled)return;back.disabled=true;const revision=interactionRevision,auth=currentAuth();
        try{
          if(!await bootstrap(true) || !sameAuth(auth) || revision!==interactionRevision || !sessionValid() || !canNavigate() || !availableDomains.includes(record.from) || !await validTransfer(record))throw Error('unavailable');
          if(revision!==interactionRevision || !sameAuth(auth) || !writeTransfer({...record,phase:'return'}))throw Error('unavailable');
          location.assign(routes[record.from]+'?progressor_return=1');
        }catch{transferMessage('Возврат временно недоступен. Текущий раздел продолжает работать. Можно открыть исходный продукт через верхнее меню.');back.disabled=false;}
      };
      const close=element('button','Убрать возврат',transferBar);close.type='button';close.onclick=closeTransfer;
    }
    async function waitForNative(revision){
      const deadline=Date.now()+10000;
      while(Date.now()<deadline){
        if(revision!==interactionRevision)return false;
        if(window.ProgressorDomain?.isReady?.())return true;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      return false;
    }
    async function resumeTransfer(){
      const record=readTransfer();
      clearArrivalMarker();
      if(!record && arrivalAction===null && arrivalReturn===null)return;
      const revision=0,proof=currentAuth().proof;
      if(!await bootstrap(true) || currentAuth().proof!==proof || !sessionValid() || !canNavigate() || !await validTransfer(record)){
        clearTransfer();if(arrivalAction!==null || arrivalReturn!==null)transferMessage('Переход уже недоступен. Откройте нужный раздел обычным способом.');return;
      }
      const returning=arrivalReturn==='1' && arrivalAction===null && record.phase==='return' && record.from===source;
      const arriving=arrivalReturn===null && arrivalAction===record.action.kind && record.phase==='outbound' && record.to===source;
      if(!returning && !arriving){
        if(arrivalAction!==null || arrivalReturn!==null){clearTransfer();transferMessage('Переход уже недоступен. Откройте нужный раздел обычным способом.');}
        else if(record.to===source && record.phase==='active')showReturn(record);
        return;
      }
      if(!availableDomains.includes(source)){clearTransfer();return;}
      const auth=currentAuth();
      const open=async expectedRevision=>{
        if(!await waitForNative(expectedRevision) || expectedRevision!==interactionRevision || !sameAuth(auth) || !await validTransfer(record) || expectedRevision!==interactionRevision)return false;
        try{return !!await (returning?window.ProgressorDomain.restoreView?.(record.view):window.ProgressorDomain.perform?.(record.action));}catch{return false;}
      };
      const handled=await open(revision);
      if(!sameAuth(auth)){closeTransfer();return;}
      if(returning){
        clearTransfer();
        if(!handled)transferMessage('Возврат отменён: текущий экран сохранён. Выберите нужный раздел в меню.');
        return;
      }
      if(record.expires_at<=Date.now()){closeTransfer();transferMessage('Время возврата истекло. Текущий раздел продолжает работать.');return;}
      record.phase='active';
      if(!writeTransfer(record)){clearTransfer();transferMessage('Возврат недоступен в этой вкладке. Текущий раздел продолжает работать.');return;}
      showReturn(record);
      if(!handled){
        transferStatus.textContent='Вы уже выбрали другой экран, или раздел ещё загружается. Продолжить переход можно явно.';
        const retry=element('button','Открыть выбранный раздел',transferBar);retry.type='button';
        retry.onclick=async()=>{if(retry.disabled)return;retry.disabled=true;const ok=await open(interactionRevision);if(ok)retry.remove();else{retry.disabled=false;transferStatus.textContent='Не удалось открыть раздел. Закончите текущую форму и попробуйте ещё раз.';}};
      }
    }
    void resumeTransfer().catch(()=>{closeTransfer();transferMessage('Переход временно недоступен. Текущий раздел продолжает работать.');});
    const panel = element('section', undefined, shell);
    const connectionButton=element('button','Связь продуктов',panel);connectionButton.type='button';
    connectionButton.addEventListener('click',()=>document.dispatchEvent(new Event('progressor:open-connections')));
    const settingsScript=document.createElement('script');settingsScript.src='/progressor/assets/connections.v1.js';settingsScript.dataset.progressorSource=source;document.head.append(settingsScript);
    panel.id = 'progressor-context'; panel.hidden = true;
    element('strong', 'Общий контекст', panel);
    const status = element('p', 'Загрузка контекста…', panel);
    const content = element('div', undefined, panel);
    const homeButton = element('button', 'Сегодня', nav); homeButton.type = 'button'; homeButton.dataset.progressorHome = ''; homeButton.setAttribute('aria-pressed', 'false'); homeButton.hidden = true;
    homeButton.addEventListener('click', () => { if (window.Progressor.homeOpen?.()) window.Progressor.closeHome(); else window.Progressor.openHome?.(); });
    document.addEventListener('progressor:home', event => homeButton.setAttribute('aria-pressed', String(!!event.detail?.open)));
    for (const [domain, label] of [['gym', 'Тренировки'], ['food', 'Еда'], ['supply', 'БАДы']]) {
      const link = element('a', label, nav); link.href = routes[domain]; link.dataset.domain = domain;
      if (domain === source) link.setAttribute('aria-current', 'page');
      link.addEventListener('click', async event => {
        if (domain === source) { event.preventDefault(); window.Progressor.closeHome?.(); return; }
        event.preventDefault();
        await bootstrap(true);
        if (sessionValid() && canNavigate() && availableDomains.includes(domain)) location.assign(routes[domain]);
        else { panel.hidden = false; status.textContent = 'Переход временно недоступен. Текущий раздел продолжает работать; попробуйте позже.'; }
      });
    }
    const toggle = element('button', 'Подписки', nav);
    toggle.type = 'button'; toggle.setAttribute('aria-label', 'Мои подписки и общий контекст');
    toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-controls', panel.id);
    toggle.addEventListener('click', () => { panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); if (!panel.hidden) {document.dispatchEvent(new Event('progressor:overlay-open'));loadContext();openBundle(panel);} });
    const bundle = element('button', 'Progressor · подписка на 3 продукта', panel);
    bundle.type = 'button'; bundle.id = 'progressor-bundle-button';
    bundle.addEventListener('click', () => openBundle(panel));
    window.Progressor.openBundle = () => { panel.hidden = false; toggle.setAttribute('aria-expanded','true'); document.dispatchEvent(new Event('progressor:overlay-open')); return openBundle(panel); };
    window.Progressor.openSubscriptions = window.Progressor.openBundle;
    window.Progressor.openProductSubscriptions = async id => {panel.hidden=false;toggle.setAttribute('aria-expanded','true');ensureSubscriptions(panel);const revision=++purchaseOptionsRevision;await loadSubscriptions(panel);if(revision===purchaseOptionsRevision)await selectProduct(id);};
    document.body.prepend(shell);
    if(new URLSearchParams(location.search).get('progressor_subscription')==='1'){panel.hidden=false;toggle.setAttribute('aria-expanded','true');ensureSubscriptions(panel);loadSubscriptions(panel).then(()=>selectProduct(source));}
    const height = () => document.documentElement.style.setProperty('--progressor-bar-height', `${Math.ceil(shell.getBoundingClientRect().height)}px`);
    height(); new ResizeObserver(height).observe(shell);
    let loading=false, lastContext=null, contextAuth=null, reviewConfirmation=null, panelSignature='', inlineSignature='',seenObserver=null,seenCheck=()=>{},initialContextRetries=0;
    function hintStatus(card,message){let node=card.querySelector('[role="status"]');if(!node){node=element('p','',card);node.setAttribute('role','status');}node.textContent=message;}
    async function reviewHint(button,card,hint,signature,auth){
      if(button.disabled)return;
      button.disabled=true;const revision=interactionRevision;
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000);
      try{
        if(!sameAuth(auth))throw Error('changed');
        const response=await window.fetch('/progressor/api/v1/me/hints/reviewed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:source,delivery_key:hint.delivery_key}),signal:controller.signal,cache:'no-store'});
        if(response.status!==200)throw Error('unavailable');
        const ack=await response.json();
        if(ack.reviewed!==true || ack.target!==source || ack.delivery_key!==hint.delivery_key || typeof ack.reviewed_at!=='number' || !Number.isFinite(ack.reviewed_at) || ack.reviewed_at<=0)throw Error('invalid_ack');
        // A delayed receipt belongs to this exact card and account only.
        if(!sameAuth(auth) || !card.isConnected || inlineSignature!==signature || lastContext?.inline_hint?.delivery_key!==hint.delivery_key)return;
        seenObserver?.disconnect();
        reviewConfirmation={delivery_key:hint.delivery_key,auth,focus:revision===interactionRevision};
        lastContext.inline_hint=null;lastContext.offer_preview=null;inlineSignature='';
        renderInline();
      }catch{
        if(sameAuth(auth) && card.isConnected && inlineSignature===signature)hintStatus(card,'Не удалось подтвердить проверку. Цель, план и дозы не менялись. Попробуйте ещё раз.');
      }finally{clearTimeout(timeout);button.disabled=false;if(!sameAuth(auth))renderInline();}
    }
    const acknowledged=new Set();
    function observeHint(card,hint) {
      seenObserver?.disconnect();seenObserver=null;
      seenCheck=()=>{};
      if(!hint.delivery_key || acknowledged.has(hint.delivery_key) || !window.IntersectionObserver) return;
      let ratio=0,timer=null;
      seenCheck=()=>{
        if(ratio<.6 || document.hidden || !card.isConnected || acknowledged.has(hint.delivery_key) || timer) return;
        const rect=card.getBoundingClientRect();
        const x=(Math.max(rect.left,0)+Math.min(rect.right,innerWidth))/2;
        const y=(Math.max(rect.top,0)+Math.min(rect.bottom,innerHeight))/2;
        if(!card.contains(document.elementFromPoint(x,y))) return;
        timer=setTimeout(()=>{
          timer=null;
          if(ratio<.6 || document.hidden || !card.isConnected || !card.contains(document.elementFromPoint(x,y))) return;
          seenObserver?.disconnect();acknowledged.add(hint.delivery_key);
          const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),2000);
          window.fetch('/progressor/api/v1/me/hints/seen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:source,delivery_key:hint.delivery_key}),signal:controller.signal})
            .then(async r=>{await r.text();if(!r.ok) acknowledged.delete(hint.delivery_key);})
            .catch(()=>acknowledged.delete(hint.delivery_key)).finally(()=>clearTimeout(timeout));
        },1000);
      };
      seenObserver=new IntersectionObserver(entries=>{
        ratio=entries[entries.length-1]?.intersectionRatio || 0;seenCheck();
      },{threshold:.6});seenObserver.observe(card);
    }
    document.addEventListener('click',()=>setTimeout(()=>seenCheck(),150));
    document.addEventListener('visibilitychange',()=>seenCheck());
    async function performAction(action) {
      if(action?.kind==='bundle'){await window.Progressor.openBundle();return true;}
      const purpose=cleanAction(action);if(!purpose)return false;
      const domain=actionDomains[purpose.kind];
      if(domain===source)return !!await window.ProgressorDomain?.perform?.(purpose);
      const view=window.ProgressorDomain?.captureView?.();
      if(!returnViews[source].includes(view))return false;
      const revision=interactionRevision,proof=currentAuth().proof;
      if(!await bootstrap(true) || currentAuth().proof!==proof || revision!==interactionRevision || !sessionValid() || !canNavigate() || !availableDomains.includes(domain))return false;
      const binding=await authBinding();
      if(!binding || revision!==interactionRevision)return false;
      const now=Date.now(),record={version:1,...binding,from:source,to:domain,action:purpose,view,created_at:now,expires_at:now+transferTtl,phase:'outbound'};
      if(!writeTransfer(record)){clearTransfer();return false;}
      location.assign(routes[domain]+'?progressor_action='+purpose.kind);
      return true;
    }
    window.Progressor.performAction = performAction;
    // Staged rollout: only a session the server marked receives the home screen.
    void ready.then(() => bootstrap()).then(session => {
      if (!session?.home || document.querySelector('script[data-progressor-home]')) return;
      nav.dataset.home = ''; homeButton.hidden = false;
      // One bottom tab bar for the home screen and for every product page that opted into the shared look.
      const glyphs = {
        home: 'M5 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM15 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM5 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zM15 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
        gym: 'M2 12h1M6 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2M6 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1zM9 12h6M15 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1a1 1 0 0 0-1 1zM18 8h2a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2M22 12h-1',
        food: 'M5 21c.5-4.5 2.5-8 7-10M9 18c6.218 0 10.5-3.288 11-12V4h-4.014c-9 0-11.986 4-12 9 0 1 0 3 2 5h3z',
        supply: 'M4.5 12.5l8-8a4.94 4.94 0 0 1 7 7l-8 8a4.94 4.94 0 0 1-7-7M8.5 8.5l7 7'};
      element('style', `
        #progressor-tabbar{position:fixed;left:0;right:0;bottom:0;z-index:31;background:var(--pg-glass,rgba(255,255,255,.88));-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);border-top:1px solid var(--pg-line,#E6E9EF);display:grid;grid-template-columns:repeat(4,1fr);padding:6px max(16px,calc(50% - 214px)) calc(6px + env(safe-area-inset-bottom,0px));box-sizing:border-box}
        #progressor-tabbar[hidden],html.progressor-sheet-open #progressor-tabbar{display:none}
        #progressor-tabbar button{border:0;background:none;color:var(--pg-muted,#A3AAB8);min-height:48px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:color .15s,transform .12s}
        #progressor-tabbar button:active{transform:scale(.9)}
        #progressor-tabbar button[aria-current]{color:var(--pg-text,#10131A)}
        #progressor-tabbar svg{width:26px;height:26px;stroke:currentColor;fill:none;stroke-width:1.75;stroke-linecap:round;stroke-linejoin:round}
        html[data-pg-ui="2"] #progressor-shell{background:none;border:0;padding:0}
        html[data-pg-ui="2"] #progressor-shell nav{display:none}
        html[data-pg-ui="2"] #progressor-context,html[data-pg-ui="2"] #progressor-transfer{background:#13213d;padding:calc(8px + env(safe-area-inset-top,0px)) 12px 12px;border-radius:0 0 18px 18px}
        html[data-pg-ui="2"]{--pg-bg:#fff;--pg-raise:#fff;--pg-surface:#F3F4F7;--pg-text:#10131A;--pg-muted:#6B7585;--pg-line:#E6E9EF;--pg-ink:#10131A;--pg-on-ink:#fff;--pg-glass:rgba(255,255,255,.88);--pg-tint-gym:#FFE7DF;--pg-tint-gym-text:#3B1206;--pg-tint-food:#DDF6E8;--pg-tint-food-text:#0B4A2A;--pg-tint-supply:#DEEBFF;--pg-tint-supply-text:#06254A}
        html[data-pg-ui="2"][data-pg-theme="sand"]{--pg-bg:#FBF7F0;--pg-raise:#FFFDF9;--pg-surface:#F1EADF;--pg-text:#2A2420;--pg-muted:#7A6F60;--pg-line:#E3D9C9;--pg-ink:#2A2420;--pg-glass:rgba(251,247,240,.88)}
        html[data-pg-ui="2"][data-pg-theme="graphite"]{--pg-bg:#F4F5F7;--pg-raise:#fff;--pg-surface:#E9EBEF;--pg-line:#D9DDE4;--pg-glass:rgba(244,245,247,.88)}
        html[data-pg-ui="2"][data-pg-theme="ocean"]{--pg-bg:#F3F8FD;--pg-raise:#fff;--pg-surface:#E6EFF8;--pg-text:#0E2A47;--pg-muted:#5E7690;--pg-line:#D3E1F0;--pg-ink:#0E2A47;--pg-glass:rgba(243,248,253,.88)}
        html[data-pg-ui="2"][data-pg-theme="forest"]{--pg-bg:#F4F8F3;--pg-raise:#fff;--pg-surface:#E7EFE5;--pg-text:#16281B;--pg-muted:#61745F;--pg-line:#D5E0D2;--pg-ink:#16281B;--pg-glass:rgba(244,248,243,.88)}
        html[data-pg-ui="2"][data-pg-scheme="dark"]{--pg-bg:#0E1014;--pg-raise:#242833;--pg-surface:#1A1D24;--pg-text:#F2F4F8;--pg-muted:#9AA3B2;--pg-line:#2C313C;--pg-ink:#F2F4F8;--pg-on-ink:#10131A;--pg-glass:rgba(14,16,20,.86);--pg-tint-gym:#3A1D14;--pg-tint-gym-text:#FFD0C2;--pg-tint-food:#12301F;--pg-tint-food-text:#BFF2D6;--pg-tint-supply:#132A4A;--pg-tint-supply-text:#CFE3FF}
        html[data-pg-ui="2"][data-pg-scheme="dark"][data-pg-theme="sand"]{--pg-bg:#17130E;--pg-raise:#2D261D;--pg-surface:#221C15;--pg-text:#F5EEE3;--pg-muted:#B0A391;--pg-line:#3A3126;--pg-ink:#F5EEE3;--pg-on-ink:#17130E;--pg-glass:rgba(23,19,14,.86)}
        html[data-pg-ui="2"][data-pg-scheme="dark"][data-pg-theme="graphite"]{--pg-bg:#0A0B0D;--pg-raise:#1F2227;--pg-surface:#15171B;--pg-line:#2A2E35;--pg-glass:rgba(10,11,13,.86)}
        html[data-pg-ui="2"][data-pg-scheme="dark"][data-pg-theme="ocean"]{--pg-bg:#08121E;--pg-raise:#18293C;--pg-surface:#101E2E;--pg-text:#EAF2FB;--pg-muted:#93A8BF;--pg-line:#22364B;--pg-ink:#EAF2FB;--pg-on-ink:#08121E;--pg-glass:rgba(8,18,30,.86)}
        html[data-pg-ui="2"][data-pg-scheme="dark"][data-pg-theme="forest"]{--pg-bg:#0B130D;--pg-raise:#1B2C1F;--pg-surface:#132016;--pg-text:#E9F3EA;--pg-muted:#98AD9B;--pg-line:#263A2A;--pg-ink:#E9F3EA;--pg-on-ink:#0B130D;--pg-glass:rgba(11,19,13,.86)}
      `, document.head);
      const tabbar = element('nav'); tabbar.id = 'progressor-tabbar'; tabbar.setAttribute('aria-label', 'Разделы');
      const tabs = {};
      for (const [id, label] of [['home', 'Сегодня'], ['gym', 'Тренировки'], ['food', 'Еда'], ['supply', 'БАДы']]) {
        const button = element('button', undefined, tabbar); button.type = 'button'; button.setAttribute('aria-label', label); tabs[id] = button;
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', glyphs[id]); svg.append(path); button.append(svg);
        button.addEventListener('click', () => {
          if (id === 'home') { if (!window.Progressor.homeOpen?.()) window.Progressor.openHome?.(); return; }
          if (id === source) { window.Progressor.closeHome?.(); return; }
          nav.querySelector(`a[data-domain="${id}"]`)?.click();
        });
      }
      const syncTabs = () => {
        const homeOpen = !!window.Progressor.homeOpen?.();
        tabbar.hidden = !(homeOpen || document.documentElement.dataset.pgUi === '2');
        for (const [id, button] of Object.entries(tabs)) { if (id === (homeOpen ? 'home' : source)) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); }
        document.documentElement.style.setProperty('--progressor-tab-height', tabbar.hidden ? '0px' : '61px');
      };
      document.addEventListener('progressor:home', syncTabs);
      new MutationObserver(syncTabs).observe(document.documentElement, {attributes: true, attributeFilter: ['data-pg-ui']});
      document.body.append(tabbar); syncTabs();
      const homeScript = document.createElement('script'); homeScript.src = '/progressor/assets/home.v1.js'; homeScript.dataset.progressorSource = source; homeScript.dataset.progressorHome = ''; document.head.append(homeScript);
    }).catch(() => {});
    function renderInline() {
      const host=window.ProgressorDomain?.hintHost?.();
      if (!host) return;
      if(contextAuth && !sameAuth(contextAuth)){host.hidden=true;seenObserver?.disconnect();reviewConfirmation=null;return;}
      if(!window.ProgressorDomain?.eligible?.(lastContext)){host.hidden=true;seenObserver?.disconnect();return;}
      if(reviewConfirmation){
        if(!sameAuth(reviewConfirmation.auth)){reviewConfirmation=null;}
        else if(!lastContext?.inline_hint || lastContext.inline_hint.delivery_key===reviewConfirmation.delivery_key){
          seenObserver?.disconnect();host.hidden=false;
          if(!host.querySelector('[data-review-confirmed]')){host.replaceChildren();const confirmation=element('p','Проверено. Цель, план и дозы не менялись.',host);confirmation.dataset.reviewConfirmed='';confirmation.setAttribute('role','status');confirmation.setAttribute('tabindex','-1');if(reviewConfirmation.focus)confirmation.focus({preventScroll:true});}
          return;
        }else reviewConfirmation=null;
      }
      const isOffer=!lastContext?.inline_hint && !!lastContext?.offer_preview;
      const hint=lastContext?.inline_hint || lastContext?.offer_preview;
      const eligible=hint && window.ProgressorDomain?.eligible?.(lastContext);
      host.hidden=!eligible;
      if (!eligible) {seenObserver?.disconnect();return;}
      const signature=JSON.stringify(hint);
      if (inlineSignature===signature && host.firstChild) {if(!isOffer) observeHint(host.firstChild,hint);return;}
      inlineSignature=signature; host.replaceChildren();
      const cardAuth=contextAuth||currentAuth();
      const card=element('aside',undefined,host); card.className='progressor-hint'; card.setAttribute('aria-label',hint.title);
      if(isOffer){card.dataset.kind='locked-example';element('small','Возможность общей подписки',card);}
      element('strong',hint.title,card); element('p',hint.message,card);
      if(isOffer){const example=element('p',hint.example,card);example.className='progressor-example';}
        const names=[...new Set((hint.basis||[]).map(b=>({gym:'Тренировки',food:'Еда',supply:'БАДы'}[b.source])).filter(Boolean))];
      if(!isOffer){const sources=element('p','Учтены ваши записи: '+names.join(', '),card); sources.className='progressor-sources';}
      else if(hint.current_access_domains?.length){const sources=element('p','Уже доступны: '+hint.current_access_domains.map(d=>({gym:'Тренировки',food:'Еда',supply:'БАДы'}[d])).join(', ')+'. Пробный и подарочный доступ тоже учитываются.',card);sources.className='progressor-sources';}
      const actions=element('div',undefined,card); actions.className='progressor-hint-actions';
      for (const action of [hint.action,hint.secondary_action].filter(a=>a && (!a.targets || a.targets.includes(source)))) {
        const button=element('button',action.label,actions); button.type='button';
        if(action===hint.action) button.dataset.primary='1';
        button.addEventListener('click',async event=>{
          if(button.disabled)return;if(action.kind==='bundle')event.stopPropagation();button.disabled=true;
          try{if(!await performAction(action))hintStatus(card,'Не удалось открыть раздел. Текущий экран сохранён; закончите форму или попробуйте позже.');}
          catch{hintStatus(card,'Переход временно недоступен. Текущий раздел продолжает работать.');}
          finally{button.disabled=false;}
        });
      }
      if(!isOffer && hint.reviewable===true && typeof hint.delivery_key==='string' && hint.delivery_key){
        const reviewed=element('button','Проверил, всё подходит',actions);reviewed.type='button';reviewed.dataset.reviewHint='';
        reviewed.addEventListener('click',()=>reviewHint(reviewed,card,hint,signature,cardAuth));
      }
        const details=element('details',undefined,card); element('summary',isOffer?'Как это появится':'Почему эта подсказка',details); element('p',hint.details,details); element('p',isOffer?'Крестик скрывает предложения этого раздела на неделю.':'Крестик скрывает подсказки этого раздела на неделю.',details);
        const dismiss=element('button','×',card); dismiss.type='button'; dismiss.className='progressor-dismiss'; dismiss.title=isOffer?'Скрыть предложение на неделю':'Скрыть подсказки на неделю'; dismiss.setAttribute('aria-label',dismiss.title);
      dismiss.addEventListener('click',async()=>{
        dismiss.disabled=true;
        try {
          const response=await window.fetch('/progressor/api/v1/me/'+(isOffer?'offers':'hints')+'/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:source})});
          if(!response.ok) throw new Error('unavailable');
          if(!sameAuth(cardAuth) || !card.isConnected || inlineSignature!==signature)return;
          if(isOffer) lastContext.offer_preview=null; else {lastContext.inline_hint=null;lastContext.offer_preview=null;} host.hidden=true; inlineSignature='';
        } catch (_) { let error=card.querySelector('[role="status"]'); if(!error){error=element('p',undefined,card);error.setAttribute('role','status');} error.textContent='Не удалось скрыть. Попробуйте ещё раз.'; }
        finally {dismiss.disabled=false;}
      });
      if(!isOffer) observeHint(card,hint);
    }
    window.Progressor.refreshSurface=renderInline;
    document.addEventListener('click',event=>{const path=event.composedPath();const inside=path.includes(shell)||path.some(n=>n?.id==='progressor-connections');if(!panel.hidden&&!inside){panel.hidden=true;toggle.setAttribute('aria-expanded','false');}});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden&&!document.querySelector('#progressor-connections[open]')){panel.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.focus();}});
    async function loadContext() {
      if (loading) return; loading = true;
      const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 2500);
      try {
        if (!await bootstrap()) throw new Error('unavailable');
        const requestAuth=currentAuth();
        const response = await window.fetch('/progressor/api/v1/me/context?target=' + source, {signal: controller.signal, cache: 'no-store'});
        if (!response.ok) throw new Error('unavailable');
        const context = await response.json();
        if(!sameAuth(requestAuth))return;
        contextAuth=requestAuth;
        availableDomains = context.enabled_domains || [];
        status.textContent = context.memberships.length ? `Личный контекст. Подключены: ${context.memberships.map(s => ({gym:'Тренировки',food:'Еда',supply:'БАДы'}[s])).join(', ')}.` : 'В этом разделе сейчас нет доступного общего контекста.';
        lastContext=context; renderInline();
        bundle.textContent=context.access?.bundle_active?'Общая подписка · срок и тарифы':'Progressor · подписка на 3 продукта';
        const signature=JSON.stringify({memberships:context.memberships,activity:context.activity,nutrition:context.nutrition,supply:context.supply});
        if(signature===panelSignature) return;
        panelSignature=signature;
        const expanded=[...content.querySelectorAll('details')].map(d=>d.open);
        content.replaceChildren();
        if (context.activity) element('p', activityText(context.activity), content);
        if (context.nutrition) element('p', nutritionText(context), content);
        if (context.supply?.status === 'ok') element('p', `БАДы: активных добавок — ${context.supply.active_supplement_count}, отмеченных приёмов — ${context.supply.recorded_intake_count}, доступных отчётов анализов — ${context.supply.lab_report_count}.`, content);
        for (const recommendation of context.recommendations || []) { element('strong', recommendation.title, content); element('p', recommendation.message, content); element('p', recommendation.uncertainty, content); const link = element('a', 'Проверить дневник питания', content); link.href = routes.food; link.addEventListener('click', async e => { e.preventDefault(); if (await bootstrap() && canNavigate()) location.assign(routes.food); }); }
        const nutrients = context.nutrition?.history?.['7']?.nutrients || {};
        const codes = Object.keys(nutrients);
        if (codes.length) { const details = element('details', undefined, content); element('summary', 'Нутриенты из записей питания', details); for (const code of codes) { const n = nutrients[code]; element('p', `${n.name || code}: ${n.average_on_observed_days} ${n.unit === 'ug' ? 'мкг' : n.unit === 'mg' ? 'мг' : 'г'} по ${n.observed_days} дням с данными; ${n.observed_meals} из ${n.logged_meals} приёмов пищи. Для порций с оценкой известен состав ${n.observed_components} из ${n.assessed_components} продуктов. Значения приблизительные, пропуски не считаются нулём.`, details); } }
        else if (context.nutrition) element('p', 'В этих записях питания пока нет оценки дополнительных нутриентов. Новые фото и описания сохраняют состав автоматически. Отсутствие данных не означает нулевое потребление.', content);
        if (context.supply?.active_supplements?.length || context.supply?.lab_reports?.length) {
          const details = element('details', undefined, content); element('summary', 'Добавки и анализы из раздела «БАДы»', details);
          for (const item of context.supply.active_supplements || []) element('p', `${item.name}${item.reported_dose_text ? ' · ' + item.reported_dose_text : ''}`, details);
          for (const report of context.supply.lab_reports || []) { element('p', `Отчёт ${report.report_date || 'без даты'} · ${report.observation_count} показателей · статус ${report.confirmation_state}`, details); for (const value of report.observations || []) element('p', `${value.name}: ${value.value ?? value.value_text ?? 'нет данных'} ${value.unit}`, details); }
          element('small', context.supply.uncertainty, details);
        }
        content.querySelectorAll('details').forEach((d,i)=>{d.open=!!expanded[i];});
        if (context.memberships.length) element('small', 'Источники: ' + context.memberships.map(s => ({gym:'Тренировки',food:'Еда',supply:'БАДы'}[s])).join(', ') + '. Изменения обычно появляются в течение минуты; выводы учитывают полноту записей.', content);
      } catch (_) { status.textContent = 'Общий контекст временно недоступен. Текущий раздел продолжает работать.'; lastContext=null; renderInline();if(initialContextRetries++<2)setTimeout(loadContext,2500); }
      finally { clearTimeout(timeout); loading = false; nav.querySelectorAll('a').forEach(a => a.setAttribute('aria-disabled', String(a.dataset.domain !== source && (!sessionValid() || !canNavigate() || !availableDomains.includes(a.dataset.domain))))); }
    }
    await loadContext();
    await loadSubscriptions(panel);
    setInterval(() => { if(activeTransfer && (activeTransfer.expires_at<=Date.now() || activeTransfer.owner!==currentAuth().owner))closeTransfer();if (document.visibilityState === 'visible') {loadContext();loadSubscriptions(panel);} }, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadContext(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
