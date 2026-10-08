/* Progressor shell v1. Contracts and rollback instructions: docs/PROGRESSOR_INTEGRATION.md. */
(() => {
  'use strict';
  const source = document.currentScript?.dataset.progressorSource;
  const routes = {gym: '/gymapp_prod/', food: '/webapp/', supply: '/supply/'};
  const apiPrefixes = {gym: '/gymapi_prod/', food: '/api/', supply: '/supply/api/'};
  if (!routes[source]) return;
  const storageKey = 'progressor.launch.v1';
  const rawFetch = window.fetch.bind(window);
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
  let saved = readStorage();
  const launched = fromUrl() || window.Telegram?.WebApp?.initData || '';
  if (launched && launched !== saved.launchData) {
    saved = {source, launchData: launched};
    saveStorage();
  }
  const sessionValid = () => saved.session?.assertions && saved.session.expires_at > Date.now() / 1000 + 5;
  let availableDomains = saved.session?.enabled_domains || [];
  let renewing;
  async function bootstrap(force = false) {
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

  function element(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  }
  function activityText(activity) {
    if (!activity) return '';
    if (activity.reason === 'workout_recorded') return `Gym: завершено тренировок — ${activity.completed_workout_count}. День Food: ${activity.date} (${activity.day_timezone}).`;
    if (activity.reason === 'no_completed_workout_recorded') return `Gym: за ${activity.date} завершённая тренировка пока не отмечена.`;
    if (activity.reason === 'missing_gym_membership') return 'Данных Gym пока нет. Отмечайте завершение тренировки в разделе «Тренировки».';
    return 'Данные Gym временно недоступны. Питание можно записывать как обычно.';
  }
  function nutritionText(context) {
    const seven = context.nutrition?.history?.['7'];
    if (!seven) return 'Данные Food временно недоступны. Остальные функции продолжают работать.';
    if (!seven.logged_days) return 'Записей питания за последние 7 завершённых дней пока нет.';
    return `Food: ${seven.logged_days} записанных дней из 7; средний белок по записанным дням — ${seven.averages_on_logged_days.protein} г. Журнал может быть неполным.`;
  }
  async function openBundle(panel) {
    let box = panel.querySelector('#progressor-bundle');
    if (box) { box.remove(); return; }
    box = element('section', undefined, panel); box.id = 'progressor-bundle';
    const notice = element('p', 'Загрузка тарифов…', box);
    try {
      const response = await window.fetch('/progressor/api/v1/bundle/catalog', {cache:'no-store'});
      if (!response.ok) throw new Error('unavailable');
      const catalog = await response.json();
      notice.textContent = 'Тренировки, питание и БАДы. Без автопродления. ' + catalog.limits;
      const accepted = element('label', undefined, box); const checkbox = element('input', undefined, accepted); checkbox.type = 'checkbox';
      accepted.append(document.createTextNode(' Принимаю условия общей подписки'));
      const state = element('p', '', box);
      for (const plan of catalog.plans) {
        const button = element('button', `${plan.label} · ${plan.XTR} ⭐`, box); button.type = 'button'; button.disabled = true;
        checkbox.addEventListener('change', () => { button.disabled = !checkbox.checked; });
        button.addEventListener('click', async () => {
          if (!checkbox.checked) return; button.disabled = true;
          const orderId = crypto.randomUUID(); state.textContent = 'Подготовка счёта…';
          try {
            const invoice = await window.fetch('/progressor/api/v1/me/bundle/invoice', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source,plan:plan.id,order_id:orderId,terms:catalog.terms_version})});
            if (!invoice.ok) throw new Error('invoice_failed');
            const data = await invoice.json();
            const completed = async () => {
              state.textContent = 'Проверяем подтверждение оплаты…';
              const result = await window.fetch('/progressor/api/v1/me/bundle/orders/' + encodeURIComponent(orderId),{cache:'no-store'});
              const status = result.ok ? await result.json() : {};
              state.textContent = status.status === 'paid' ? 'Подписка подтверждена. Доступ обновится во всех разделах примерно за 30 секунд.' : 'Оплата ещё не подтверждена. Если деньги списаны, повторно оплачивать не нужно. Помощь: /paysupport в боте.';
              await bootstrap(true);
            };
            if (window.Telegram?.WebApp?.openInvoice) window.Telegram.WebApp.openInvoice(data.invoice_url, () => { completed().catch(() => { state.textContent = 'Подтверждение появится после восстановления связи. /paysupport'; }); });
            else { const link = element('a', 'Открыть счёт в Telegram', box); link.href = data.invoice_url; link.target = '_blank'; link.rel = 'noopener'; state.textContent = 'Счёт готов. Откройте его для оплаты в Stars.'; }
          } catch (_) { state.textContent = 'Не удалось подготовить счёт. Оплата не проведена; попробуйте позже.'; }
          finally { button.disabled = !checkbox.checked; }
        });
      }
    } catch (_) { notice.textContent = 'Общие тарифы временно недоступны. Текущий продукт продолжает работать.'; }
  }
  async function mount() {
    document.body.dataset.progressorDomain = source;
    const style = element('style', `
      :root{--progressor-bar-height:56px}
      body[data-progressor-domain="gym"],body[data-progressor-domain="food"]{padding-top:var(--progressor-bar-height)}
      body[data-progressor-domain="gym"] .app-header{top:var(--progressor-bar-height)}
      body[data-progressor-domain="supply"] #app{height:calc(100% - var(--progressor-bar-height));margin-top:var(--progressor-bar-height)}
      #progressor-shell{position:fixed;top:0;left:0;right:0;z-index:24;isolation:isolate;color:var(--text,inherit);font:13px system-ui;background:var(--card,#13213d);border-bottom:1px solid var(--border,#46516b);padding:calc(6px + env(safe-area-inset-top,0px)) 8px 6px;}
      #progressor-shell nav{display:grid;grid-template-columns:1fr 1fr 1fr 48px;gap:4px;max-width:900px;margin:auto;}
      #progressor-shell *{font-family:inherit;box-sizing:border-box}
      #progressor-shell{box-sizing:border-box;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      #progressor-shell a,#progressor-shell button{display:flex;align-items:center;justify-content:center;min-height:48px;border:0;border-radius:10px;color:inherit;background:transparent;text-decoration:none;cursor:pointer;font:600 12px system-ui;}
      #progressor-shell a[aria-current="page"]{background:#2563eb;color:white}
      #progressor-shell a[aria-disabled="true"]{opacity:.55}
      #progressor-context{position:absolute;top:100%;left:8px;right:8px;max-width:880px;margin:auto;background:var(--card,#13213d);border:1px solid var(--border,#46516b);border-radius:0 0 14px 14px;padding:14px;box-shadow:0 10px 24px #0004;max-height:65vh;overflow:auto;overscroll-behavior:contain;line-height:1.5}
      #progressor-context[hidden]{display:none}
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
      @media(prefers-reduced-motion:reduce){.progressor-hint{scroll-behavior:auto}}

    `, document.head);
    const shell = element('section');
    shell.id = 'progressor-shell';
    const nav = element('nav', undefined, shell);
    nav.setAttribute('aria-label', 'Разделы Progressor');
    const panel = element('section', undefined, shell);
    panel.id = 'progressor-context'; panel.hidden = true;
    element('strong', 'Progressor · общий контекст', panel);
    const status = element('p', 'Загрузка контекста…', panel);
    const content = element('div', undefined, panel);
    for (const [domain, label] of [['gym', 'Тренировки'], ['food', 'Еда'], ['supply', 'БАДы']]) {
      const link = element('a', label, nav); link.href = routes[domain]; link.dataset.domain = domain;
      if (domain === source) link.setAttribute('aria-current', 'page');
      link.addEventListener('click', async event => {
        if (domain === source) { event.preventDefault(); return; }
        event.preventDefault();
        await bootstrap(true);
        if (sessionValid() && availableDomains.includes(domain)) location.assign(routes[domain]);
        else { panel.hidden = false; status.textContent = 'Переход временно недоступен. Текущий раздел продолжает работать; попробуйте позже.'; }
      });
    }
    const toggle = element('button', '↔', nav);
    toggle.type = 'button'; toggle.setAttribute('aria-label', 'Контекст Progressor');
    toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-controls', panel.id);
    toggle.addEventListener('click', () => { panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); if (!panel.hidden) loadContext(); });
    const bundle = element('button', 'Progressor · подписка на 3 продукта', panel);
    bundle.type = 'button'; bundle.id = 'progressor-bundle-button';
    bundle.addEventListener('click', () => openBundle(panel));
    window.Progressor.openBundle = () => { panel.hidden = false; return openBundle(panel); };
    document.body.prepend(shell);
    const height = () => document.documentElement.style.setProperty('--progressor-bar-height', `${Math.ceil(shell.getBoundingClientRect().height)}px`);
    height(); new ResizeObserver(height).observe(shell);
    let loading=false, lastContext=null, panelSignature='', inlineSignature='';
    async function performAction(action) {
      if (!action) return;
      const handled=await window.ProgressorDomain?.perform?.(action);
      if (handled) return;
      if (action.kind==='open_food' && await bootstrap(true) && availableDomains.includes('food')) location.assign(routes.food);
    }
    function renderInline() {
      const host=window.ProgressorDomain?.hintHost?.();
      if (!host) return;
      const hint=lastContext?.inline_hint;
      const eligible=hint && window.ProgressorDomain?.eligible?.(lastContext);
      host.hidden=!eligible;
      if (!eligible) return;
      const signature=JSON.stringify(hint);
      if (inlineSignature===signature && host.firstChild) return;
      inlineSignature=signature; host.replaceChildren();
      const card=element('aside',undefined,host); card.className='progressor-hint'; card.setAttribute('aria-label',hint.title);
      element('strong',hint.title,card); element('p',hint.message,card);
        const names=[...new Set((hint.basis||[]).map(b=>({gym:'Тренировки',food:'Еда',supply:'БАДы'}[b.source])).filter(Boolean))];
      const sources=element('p','Учтены ваши записи: '+names.join(', '),card); sources.className='progressor-sources';
      const actions=element('div',undefined,card); actions.className='progressor-hint-actions';
      for (const action of [hint.action,hint.secondary_action].filter(Boolean)) {
        const button=element('button',action.label,actions); button.type='button';
        if(action===hint.action) button.dataset.primary='1';
        button.addEventListener('click',async()=>{button.disabled=true;try{await performAction(action);}finally{button.disabled=false;}});
      }
        const details=element('details',undefined,card); element('summary','Почему эта подсказка',details); element('p',hint.details,details); element('p','Крестик скрывает подсказки этого раздела на неделю.',details);
        const dismiss=element('button','×',card); dismiss.type='button'; dismiss.className='progressor-dismiss'; dismiss.title='Скрыть подсказки на неделю'; dismiss.setAttribute('aria-label',dismiss.title);
      dismiss.addEventListener('click',async()=>{
        dismiss.disabled=true;
        try {
          const response=await window.fetch('/progressor/api/v1/me/hints/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:source})});
          if(!response.ok) throw new Error('unavailable');
          lastContext.inline_hint=null; host.hidden=true; inlineSignature='';
        } catch (_) { let error=card.querySelector('[role="status"]'); if(!error){error=element('p',undefined,card);error.setAttribute('role','status');} error.textContent='Не удалось скрыть. Попробуйте ещё раз.'; }
        finally {dismiss.disabled=false;}
      });
    }
    window.Progressor.refreshSurface=renderInline;
    document.addEventListener('click',event=>{if(!panel.hidden&&!shell.contains(event.target)){panel.hidden=true;toggle.setAttribute('aria-expanded','false');}});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){panel.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.focus();}});
    async function loadContext() {
      if (loading) return; loading = true;
      const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 2500);
      try {
        if (!await bootstrap()) throw new Error('unavailable');
        const response = await window.fetch('/progressor/api/v1/me/context?target=' + source, {signal: controller.signal, cache: 'no-store'});
        if (!response.ok) throw new Error('unavailable');
        const context = await response.json();
        availableDomains = context.enabled_domains || [];
        status.textContent = context.memberships.length ? `Личный контекст. Подключены: ${context.memberships.map(s => ({gym:'Gym',food:'Food',supply:'Supply'}[s])).join(', ')}.` : 'В этом разделе сейчас нет доступного общего контекста.';
        lastContext=context; renderInline();
        const signature=JSON.stringify({memberships:context.memberships,activity:context.activity,nutrition:context.nutrition,supply:context.supply});
        if(signature===panelSignature) return;
        panelSignature=signature;
        const expanded=[...content.querySelectorAll('details')].map(d=>d.open);
        content.replaceChildren();
        if (context.activity) element('p', activityText(context.activity), content);
        if (context.nutrition) element('p', nutritionText(context), content);
        if (context.supply?.status === 'ok') element('p', `Supply: активных добавок — ${context.supply.active_supplement_count}, отмеченных приёмов — ${context.supply.recorded_intake_count}, доступных отчётов анализов — ${context.supply.lab_report_count}.`, content);
        for (const recommendation of context.recommendations || []) { element('strong', recommendation.title, content); element('p', recommendation.message, content); element('p', recommendation.uncertainty, content); const link = element('a', 'Проверить журнал Food', content); link.href = routes.food; link.addEventListener('click', async e => { e.preventDefault(); if (await bootstrap()) location.assign(routes.food); }); }
        const nutrients = context.nutrition?.history?.['7']?.nutrients || {};
        const codes = Object.keys(nutrients);
        if (codes.length) { const details = element('details', undefined, content); element('summary', 'Нутриенты из записей Food', details); for (const code of codes) { const n = nutrients[code]; element('p', `${n.name || code}: ${n.average_on_observed_days} ${n.unit === 'ug' ? 'мкг' : n.unit === 'mg' ? 'мг' : 'г'} по ${n.observed_days} дням с данными; ${n.observed_meals} из ${n.logged_meals} приёмов пищи. Для порций с оценкой известен состав ${n.observed_components} из ${n.assessed_components} продуктов. Значения приблизительные, пропуски не считаются нулём.`, details); } }
        else if (context.nutrition) element('p', 'В этих записях Food пока нет оценки дополнительных нутриентов. Новые фото и описания сохраняют состав автоматически. Отсутствие данных не означает нулевое потребление.', content);
        if (context.supply?.active_supplements?.length || context.supply?.lab_reports?.length) {
          const details = element('details', undefined, content); element('summary', 'Добавки и анализы из Supply', details);
          for (const item of context.supply.active_supplements || []) element('p', `${item.name}${item.reported_dose_text ? ' · ' + item.reported_dose_text : ''}`, details);
          for (const report of context.supply.lab_reports || []) { element('p', `Отчёт ${report.report_date || 'без даты'} · ${report.observation_count} показателей · статус ${report.confirmation_state}`, details); for (const value of report.observations || []) element('p', `${value.name}: ${value.value ?? value.value_text ?? 'нет данных'} ${value.unit}`, details); }
          element('small', context.supply.uncertainty, details);
        }
        content.querySelectorAll('details').forEach((d,i)=>{d.open=!!expanded[i];});
        if (context.memberships.length) element('small', 'Источники: ' + context.memberships.map(s => ({gym:'Gym',food:'Food',supply:'Supply'}[s])).join(', ') + '. Изменения обычно появляются в течение минуты; выводы учитывают полноту записей.', content);
      } catch (_) { status.textContent = 'Общий контекст временно недоступен. Текущий раздел продолжает работать.'; lastContext=null; renderInline(); }
      finally { clearTimeout(timeout); loading = false; nav.querySelectorAll('a').forEach(a => a.setAttribute('aria-disabled', String(a.dataset.domain !== source && (!sessionValid() || !availableDomains.includes(a.dataset.domain))))); }
    }
    await loadContext();
    setInterval(() => { if (document.visibilityState === 'visible') loadContext(); }, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadContext(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
