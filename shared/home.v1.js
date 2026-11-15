/* Progressor home "Сегодня" v1. Canonical single copy in Core; never mirrored into bots.
   Read-only views of each owner API plus the existing Supply day toggles. No AI, no new writers. */
(() => {
  'use strict';
  const source = document.currentScript?.dataset.progressorSource;
  const api = {gym: '/gymapi_prod', food: '/api', supply: '/supply/api'};
  if (!api[source] || !window.Progressor || window.Progressor._home) return;
  const seenKey = 'progressor.home.v1';
  const icons = {
    play: 'M7 4v16l13-8z', ok: 'M5 12l5 5L20 7', down: 'M6 9l6 6 6-6', plus: 'M12 5v14M5 12h14', lock: 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z',
    cam: 'M5 7h3l2-3h4l2 3h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zM15.5 13a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0z',
    mic: 'M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3', stop: 'M7 7h10v10H7z',
    home: 'M5 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM15 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM5 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zM15 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z',
    gym: 'M2 12h1M6 8H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2M6 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1zM9 12h6M15 7v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1a1 1 0 0 0-1 1zM18 8h2a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2M22 12h-1',
    food: 'M5 21c.5-4.5 2.5-8 7-10M9 18c6.218 0 10.5-3.288 11-12V4h-4.014c-9 0-11.986 4-12 9 0 1 0 3 2 5h3z',
    supply: 'M4.5 12.5l8-8a4.94 4.94 0 0 1 7 7l-8 8a4.94 4.94 0 0 1-7-7M8.5 8.5l7 7'};
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (value !== false && value != null) node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children) if (child != null) node.append(child);
    return node;
  }
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', 'ph-i');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', icons[name]); svg.append(path);
    return svg;
  }
  function ring(percent) {
    const known = Number.isFinite(percent), p = known ? Math.max(0, Math.min(100, percent)) : 0, c = 2 * Math.PI * 22;
    const box = h('div', {class: 'ph-ring'});
    box.innerHTML = `<svg viewBox="0 0 56 56" aria-hidden="true"><circle cx="28" cy="28" r="22" class="ph-track"/><circle cx="28" cy="28" r="22" stroke-dasharray="${(c * p / 100).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 28 28)"/><text x="28" y="33" text-anchor="middle">${known ? Math.round(p) + '%' : '—'}</text></svg>`;
    return box;
  }

  let session = null, generation = 0, busy = false;
  const state = {gym: {status: 'loading'}, food: {status: 'loading'}, supply: {status: 'loading'}, relationship: null, gymFree: false, gymHint: null, links: null};
  async function call(domain, path, body, options = {}) {
    // A product page can use the capture sheets before the home screen was ever opened.
    if (!session) session = await window.Progressor.renew();
    const assertion = domain === 'core' ? session?.assertions?.core : session?.assertions?.[domain];
    if (typeof assertion !== 'string') return {ok: false, status: 0};
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), options.timeout || 8000);
    try {
      const headers = {'X-Progressor-Auth': assertion}, raw = body instanceof Blob;
      if (body) headers['Content-Type'] = raw ? options.type || body.type || 'application/octet-stream' : 'application/json';
      const url = domain === 'core' ? '/progressor/api/v1/me' + path : api[domain] + path;
      const response = await fetch(url, {method: options.method || (body ? 'POST' : 'GET'), headers, body: raw ? body : body ? JSON.stringify(body) : undefined, signal: controller.signal, cache: 'no-store'});
      let data = null; try { data = await response.json(); } catch {}
      return {ok: response.ok && data?.ok !== false, status: response.status, data};
    } catch { return {ok: false, status: 0}; }
    finally { clearTimeout(timer); }
  }
  const allowed = domain => (session?.enabled_domains || []).includes(domain) && session?.access?.domains?.[domain] !== false;
  async function loadDomain(domain, path) {
    if (!allowed(domain)) return {status: 'locked'};
    const result = await call(domain, path);
    if (result.ok) return {status: 'ready', data: result.data};
    return {status: [401, 402, 403].includes(result.status) ? 'locked' : 'error'};
  }
  async function load() {
    const mine = ++generation;
    session = await window.Progressor.renew();
    if (mine !== generation) return;
    if (!session) { for (const d of Object.keys(api)) state[d] = {status: 'error'}; render(); return; }
    render();
    const jobs = [
      loadDomain('gym', '/day/today').then(v => { if (mine === generation) { state.gym = v; render(); } }),
      (allowed('gym') ? call('gym', '/all_exercises/session/current') : Promise.resolve({ok: false})).then(v => { if (mine === generation) { state.gymFree = !!(v.ok && v.data?.session_id); render(); } }),
      (allowed('gym') ? call('gym', '/day/start_hint') : Promise.resolve({ok: false})).then(v => { if (mine === generation) { state.gymHint = v.ok ? v.data : null; render(); } }),
      loadDomain('food', '/stats/today').then(v => { if (mine === generation) { state.food = v; render(); } }),
      loadDomain('supply', '/today').then(v => { if (mine === generation) { state.supply = v; render(); } }),
      call('core', '/connections/links?target=' + source).then(v => { if (mine === generation) { state.links = v.ok ? v.data : null; render(); } }),
      call('core', '/connections/today?target=' + source).then(v => { if (mine === generation) { state.relationship = v.ok ? v.data?.relationship || null : null; render(); } })];
    await Promise.all(jobs);
  }

  // Supply: one flat list per slot. A complex is taken through its own existing toggle.
  function supplySlots() {
    return (state.supply.data?.slots || []).map(slot => {
      const units = [];
      for (const c of slot.complexes || []) units.push({kind: 'complex', id: c.complex_id, name: c.name, taken: c.status === 'taken', pending: c.status !== 'taken' && c.status !== 'skipped', count: c.total_count || 1, done: c.taken_count || 0});
      for (const i of slot.items || []) if (!i.blocked) units.push({kind: 'item', id: i.supplement_id, name: i.name, taken: i.status === 'taken', pending: i.status === 'none', count: 1, done: i.status === 'taken' ? 1 : 0});
      return {title: slot.title, time: slot.time_local, units};
    }).filter(slot => slot.units.length);
  }
  async function setUnits(units, status) {
    if (busy) return false;
    busy = true;
    let ok = true;
    const day = state.supply.data?.day;
    for (const unit of units) {
      const result = unit.kind === 'complex'
        ? await call('supply', '/today/toggle_complex', {complex_id: unit.id, status, day})
        : await call('supply', '/today/toggle', {supplement_id: unit.id, status, day});
      if (!result.ok) { ok = false; break; }
    }
    const refreshed = await loadDomain('supply', '/today');
    busy = false;
    state.supply = refreshed; render();
    if (sheetKind === 'supply') openSupplySheet();
    return ok;
  }

  // Food capture: one request id per meal, so a repeated upload cannot be saved or charged twice.
  const requestId = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c => (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
  let recorder = null, recordTimer = 0;
  function stopRecorder(cancel) {
    clearInterval(recordTimer);
    const current = recorder; recorder = null;
    if (!current) return;
    if (cancel) current.cancelled = true;
    try { if (current.media.state !== 'inactive') current.media.stop(); } catch {}
    current.stream.getTracks().forEach(track => track.stop());
  }
  async function shrink(file) {
    // Phone photos are several megabytes; 1600 px keeps the plate legible and the upload fast.
    try {
      const bitmap = await createImageBitmap(file, {imageOrientation: 'from-image'});
      const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas'); canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close?.();
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.86));
      return blob || file;
    } catch { return file; }
  }
  async function submitMeal(kind, payload, preview) {
    const id = requestId();
    const send = () => kind === 'text' ? call('food', '/meals/capture/text', {request_id: id, text: payload}, {timeout: 90000})
      : call('food', `/meals/capture/${kind}?request_id=${id}`, payload, {timeout: 90000, type: kind === 'photo' ? 'image/jpeg' : payload.type});
    const attempt = async () => {
      openSheet('food', h('h3', null, 'Считаем…'), preview || null, h('div', {class: 'ph-spin', role: 'status', 'aria-label': 'Идёт расчёт'}));
      const result = await send();
      if (sheetKind !== 'food') { if (result.ok) { void load(); document.dispatchEvent(new CustomEvent('progressor:meal-recorded', {detail: {day: result.data?.day}})); } return; }
      if (result.ok && result.data?.meal) { mealSheet(result.data, preview); void load(); document.dispatchEvent(new CustomEvent('progressor:meal-recorded', {detail: {day: result.data.day}})); return; }
      const message = result.data?.detail?.message || (result.status ? 'Не удалось посчитать. Повторите попытку.' : 'Нет связи с сервером. Запись не потеряна — повторите.');
      // The same request id is reused: if the first answer was lost, the saved meal comes back without a new charge.
      openSheet('food', h('h3', null, 'Не получилось'), h('p', {class: 'ph-muted'}, message),
        h('div', {class: 'ph-btns'}, [402, 413, 415, 422].includes(result.status) ? null : h('button', {type: 'button', class: 'ph-btn dark grow', onclick: attempt}, 'Повторить'),
          h('button', {type: 'button', class: 'ph-btn light grow', onclick: () => textSheet(kind === 'text' ? payload : '')}, 'Описать текстом')));
    };
    await attempt();
  }
  function mealSheet(data, preview) {
    const meal = data.meal; let version = meal.version, saving = false;
    const list = h('div'), totals = h('div', {class: 'ph-tot'}), note = h('p', {class: 'ph-muted', role: 'status'});
    const draw = () => {
      const sum = key => Math.round(meal.items.reduce((n, i) => n + (i[key] || 0), 0));
      list.replaceChildren(...meal.items.map((item, index) => {
        const step = delta => async () => {
          const grams = Math.max(5, Math.min(5000, Math.round(item.grams + delta)));
          if (saving || grams === Math.round(item.grams)) return;
          saving = true; note.textContent = 'Сохраняем…';
          const result = await call('food', `/meals/${meal.id}/items/${index}`, {grams, version}, {method: 'PATCH'});
          saving = false;
          if (!result.ok) { note.textContent = 'Правка не сохранилась. Откройте дневник и проверьте запись.'; return; }
          const ratio = grams / item.grams; version = result.data.version;
          for (const key of ['kcal', 'protein', 'fat', 'carbs']) item[key] = (item[key] || 0) * ratio;
          item.grams = grams; note.textContent = ''; draw(); void load(); document.dispatchEvent(new CustomEvent('progressor:meal-recorded', {detail: {day: data.day}}));
        };
        return h('div', {class: 'ph-item'}, h('div', {class: 'ph-grow'}, item.name, h('small', null, `${Math.round(item.kcal || 0)} ккал`)),
          h('div', {class: 'ph-step'}, h('button', {type: 'button', 'aria-label': 'Меньше на 10 граммов', onclick: step(-10)}, '−'), h('span', null, `${Math.round(item.grams)} г`), h('button', {type: 'button', 'aria-label': 'Больше на 10 граммов', onclick: step(10)}, '+')));
      }));
      totals.replaceChildren(...[['kcal', 'ккал'], ['protein', 'белки'], ['fat', 'жиры'], ['carbs', 'углев.']].map(([key, label]) => h('div', null, h('b', null, String(sum(key))), h('span', null, label))));
    };
    draw();
    // Food → Supply: an intake that is due around this meal, or already overdue, can be marked right here.
    const supplyRow = h('div', {class: 'ph-pair', hidden: true});
    if (allowed('supply')) void loadDomain('supply', '/today').then(result => {
      if (result.status !== 'ready' || sheetKind !== 'food') return;
      state.supply = result;
      const now = new Date(), minutes = now.getHours() * 60 + now.getMinutes();
      const due = supplySlots().find(slot => { const m = /^(\d\d):(\d\d)$/.exec(slot.time || ''); return slot.units.some(u => u.pending) && m && Number(m[1]) * 60 + Number(m[2]) <= minutes + 90; });
      if (!due) return;
      const pending = due.units.filter(u => u.pending);
      const button = h('button', {type: 'button', class: 'ph-mini', onclick: async () => {
        button.disabled = true;
        const ok = await setUnits(pending, 'taken');
        supplyRow.replaceChildren(h('span', null, ok ? `БАДы «${due.title}» отмечены` : 'Не все отметки сохранились — проверьте в разделе БАДов'));
      }}, 'Принял');
      supplyRow.replaceChildren(h('span', null, h('b', null, `БАДы «${due.title}»`), ` · не отмечено ${pending.length}`), button);
      supplyRow.hidden = false;
    });
    openSheet('food', h('h3', null, data.created ? 'Записано' : 'Уже записано'),
      data.transcript ? h('p', {class: 'ph-heard'}, '«' + data.transcript + '»') : preview || null,
      h('p', {class: 'ph-muted'}, 'Это оценка. Поправьте граммы, если порция была другой.'), list, totals, note, supplyRow,
      h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn dark grow', onclick: closeSheet}, 'Готово')));
  }
  function textSheet(initial) {
    stopRecorder(true);
    const area = h('textarea', {rows: '4', maxlength: '2000', placeholder: 'Куриная грудка 180 г, рис 200 г, салат с маслом', 'aria-label': 'Что вы съели'});
    area.value = initial || '';
    const error = h('p', {class: 'ph-muted', role: 'alert'});
    openSheet('food', h('h3', null, 'Что вы съели?'), area, error,
      h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn dark grow', onclick: () => { const text = area.value.trim(); if (!text) { error.textContent = 'Напишите блюдо и примерную порцию.'; return; } submitMeal('text', text, h('p', {class: 'ph-heard'}, text)); }}, 'Посчитать')));
    area.focus();
  }
  async function startVoice() {
    const type = window.MediaRecorder && ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find(t => MediaRecorder.isTypeSupported(t));
    if (!type || !navigator.mediaDevices?.getUserMedia) { textSheet(''); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
    catch { textSheet(''); toast('Микрофон недоступен. Опишите еду текстом или надиктуйте с клавиатуры.'); return; }
    const media = new MediaRecorder(stream, {mimeType: type, audioBitsPerSecond: 32000}), chunks = [], current = {media, stream, cancelled: false};
    recorder = current;
    media.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    media.onstop = () => { if (current.cancelled) return; const blob = new Blob(chunks, {type: type.split(';')[0]}); if (blob.size < 800) { textSheet(''); return; } submitMeal('voice', blob, null); };
    const started = Date.now(), clock = h('b', {class: 'ph-clock'}, '0:00');
    recordTimer = setInterval(() => { const s = Math.floor((Date.now() - started) / 1000); clock.textContent = `0:${String(s).padStart(2, '0')}`; if (s >= 59) stopRecorder(false); }, 250);
    openSheet('food', h('h3', null, 'Слушаю…'), h('p', {class: 'ph-muted'}, 'Скажите, что и сколько вы съели.'),
      h('div', {class: 'ph-wave', 'aria-hidden': 'true'}, ...Array.from({length: 12}, (_, i) => h('i', {style: `animation-delay:${i * 80}ms`}))), clock,
      h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn dark grow', onclick: () => stopRecorder(false)}, icon('stop'), 'Готово'),
        h('button', {type: 'button', class: 'ph-btn light', onclick: () => textSheet('')}, 'Текстом')));
    media.start();
  }
  let photoInput = null;
  function startPhoto() {
    if (!photoInput) {
      photoInput = h('input', {type: 'file', accept: 'image/*', capture: 'environment', hidden: true, 'aria-hidden': 'true', tabindex: '-1'});
      photoInput.addEventListener('change', async () => {
        const file = photoInput.files?.[0]; photoInput.value = '';
        if (!file) return;
        const blob = await shrink(file), image = h('img', {class: 'ph-photo', alt: 'Фото еды'});
        image.src = URL.createObjectURL(blob);
        submitMeal('photo', blob, image);
      });
      root.append(photoInput);
    }
    photoInput.click();
  }

  const gymKey = 'progressor.home.gym';
  // An unfinished free session wins; then what the person actually records (server history of
  // recent sessions with sets); with too little history, the last choice on this device; else the plan.
  function gymChoice(hasPlan) {
    if (state.gymFree || !hasPlan) return 'free';
    const hint = state.gymHint;
    if (hint && hint.sample >= 3 && (hint.preferred === 'free' || hint.preferred === 'plan')) return hint.preferred;
    let last = null; try { last = localStorage.getItem(gymKey); } catch {}
    return last === 'free' ? 'free' : 'plan';
  }
  let opened = false, painted = false, linksOpen = false;
  let root = null, body = null, sheet = null, toastNode = null, sheetKind = null, toastTimer = 0;
  function toast(message, actionLabel, action) {
    toastNode.replaceChildren(h('span', null, message));
    if (actionLabel) toastNode.append(h('button', {type: 'button', onclick: () => { toastNode.hidden = true; action(); }}, actionLabel));
    toastNode.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastNode.hidden = true; }, 6000);
  }
  function closeSheet() { stopRecorder(true); sheet.hidden = true; sheetKind = null; sheet.replaceChildren(); document.documentElement.classList.remove('progressor-sheet-open'); }
  function openSheet(kind, ...children) {
    sheetKind = kind;
    sheet.replaceChildren(h('div', {class: 'ph-sheet', role: 'dialog', 'aria-modal': 'true'},
      h('div', {class: 'ph-sheet-head'}, children[0], h('button', {type: 'button', class: 'ph-x', 'aria-label': 'Закрыть', onclick: closeSheet}, '×')), ...children.slice(1)));
    sheet.hidden = false; document.documentElement.classList.add('progressor-sheet-open');
  }
  function openSupplySheet() {
    const slots = supplySlots();
    const total = slots.reduce((n, s) => n + s.units.reduce((m, u) => m + u.count, 0), 0), done = slots.reduce((n, s) => n + s.units.reduce((m, u) => m + u.done, 0), 0);
    openSheet('supply', h('h3', null, 'БАДы на сегодня'),
      h('p', {class: 'ph-muted'}, `Принято ${done} из ${total}. Нажмите на добавку, чтобы отметить или снять.`),
      ...slots.map(slot => {
        const pending = slot.units.filter(u => u.pending);
        return h('section', {class: 'ph-slot'},
          h('div', {class: 'ph-slot-head'}, h('b', null, slot.title, h('span', null, ' · ' + slot.time)),
            pending.length ? h('button', {type: 'button', class: 'ph-mini', onclick: () => takeUnits(pending, slot.title)}, 'Принял все') : h('span', {class: 'ph-muted'}, 'Готово')),
          h('div', {class: 'ph-chips'}, ...slot.units.map(u => h('button', {type: 'button', class: 'ph-chip' + (u.taken ? ' on' : ''), 'aria-pressed': String(u.taken),
            onclick: async () => { if (!await setUnits([u], u.taken ? 'none' : 'taken')) toast('Не удалось сохранить отметку. Список обновлён.'); }},
            u.name, u.kind === 'complex' ? h('small', null, ` ${u.done}/${u.count}`) : null))));
      }));
  }
  // "Понятно" hides a card on this device for a week; the rule itself keeps running on the server.
  const hiddenKey = 'progressor.links.hidden';
  function hiddenCards() {
    try { const saved = JSON.parse(localStorage.getItem(hiddenKey) || '{}'), now = Date.now(); return new Set(Object.keys(saved).filter(key => saved[key] > now)); } catch { return new Set(); }
  }
  function hideCard(cardKey) {
    try { const saved = JSON.parse(localStorage.getItem(hiddenKey) || '{}'), now = Date.now(); for (const key of Object.keys(saved)) if (saved[key] <= now) delete saved[key]; saved[cardKey] = now + 7 * 86400000; localStorage.setItem(hiddenKey, JSON.stringify(saved)); } catch {}
  }
  // A rest day: Core pauses hints and reminders until tomorrow morning and the streak is kept.
  async function toggleRest() {
    if (busy) return;
    busy = true;
    const resting = !!state.links?.rest_active, morning = new Date(); morning.setHours(29, 0, 0, 0);
    const result = await call('core', '/connections', {action: 'preferences', revision: state.links?.preferences_revision ?? 0, patch: resting ? {paused: false, pause_until: null} : {paused: true, pause_until: Math.floor(morning.getTime() / 1000)}});
    busy = false;
    toast(result.ok ? (resting ? 'Обычный режим включён' : 'Сегодня отдых: напоминания и подсказки на паузе до утра, серия сохранится') : 'Не удалось изменить режим. Обновите экран и повторите.');
    void load();
  }
  // Ask about one's own records. Food answers; the daily allowance is enforced on its server.
  function openAsk(initial) {
    const area = h('textarea', {rows: '3', maxlength: '500', placeholder: 'Хватает ли мне белка на этой неделе?', 'aria-label': 'Ваш вопрос'});
    area.value = initial || '';
    const out = h('div', {class: 'ph-answer', role: 'status', hidden: true}), note = h('p', {class: 'ph-muted'}, 'Ответ строится по вашим записям. Это не медицинская консультация.');
    const button = h('button', {type: 'button', class: 'ph-btn dark grow', onclick: async () => {
      const question = area.value.trim();
      if (question.length < 3) { note.textContent = 'Напишите вопрос одной-двумя фразами.'; return; }
      button.disabled = true; out.hidden = false; out.replaceChildren(h('div', {class: 'ph-spin', 'aria-label': 'Думаю'}));
      const result = await call('food', '/ask', {question}, {timeout: 70000});
      button.disabled = false;
      if (sheetKind !== 'ask') return;
      if (result.ok && result.data?.answer) {
        out.replaceChildren(...String(result.data.answer).split(/\n+/).map(line => h('p', null, line)));
        note.textContent = `Осталось вопросов сегодня: ${result.data.left_today}.` + (result.data.ecosystem_used ? '' : ' Учтён только дневник питания.');
      } else {
        out.replaceChildren(h('p', null, result.data?.detail?.message || (result.status ? 'Не удалось получить ответ. Попробуйте позже.' : 'Нет связи с сервером.')));
      }
    }}, 'Спросить');
    openSheet('ask', h('h3', null, 'Спросить про свои данные'), area,
      h('div', {class: 'ph-chips'}, ...['Хватает ли мне белка?', 'Что подтянуть на этой неделе?', 'Как сочетаются мои добавки?'].map(text => h('button', {type: 'button', class: 'ph-chip', onclick: () => { area.value = text; area.focus(); }}, text))),
      h('div', {class: 'ph-btns'}, button), out, note);
    area.focus();
  }
  const themeNames = {classic: 'Классика', sand: 'Песок', graphite: 'Графит', ocean: 'Океан', forest: 'Лес'};
  function openThemes() {
    const current = window.Progressor.theme?.() || 'classic';
    openSheet('themes', h('h3', null, 'Оформление'),
      h('p', {class: 'ph-muted'}, 'Одна тема на все три раздела. Светлый или тёмный вариант выбирается по теме Telegram.'),
      h('div', {class: 'ph-themes'}, ...(window.Progressor.themes || ['classic']).map(name => h('button', {type: 'button', class: 'ph-theme', 'data-theme-name': name, 'aria-pressed': String(name === current),
        onclick: () => { window.Progressor.setTheme?.(name); openThemes(); }}, h('i', {'aria-hidden': 'true'}), themeNames[name] || name))));
  }
  async function takeUnits(units, title) {
    if (!units.length) return;
    const ok = await setUnits(units, 'taken');
    if (!ok) { toast('Не все отметки сохранились. Список обновлён.'); return; }
    toast(`${title}: отмечено — ${units.length}`, 'Отменить', () => setUnits(units, 'none'));
  }
  async function go(action) {
    const handled = await window.Progressor.performAction?.(action);
    if (handled) hide(); else toast('Переход временно недоступен. Откройте раздел через верхнее меню.');
  }
  function lockedTile(domain, cls, title) {
    return h('div', {class: 'ph-tile ph-locked ' + cls},
      h('div', {class: 'ph-lock'}, icon('lock')), h('h2', null, title),
      h('p', null, {gym: 'План, подходы с прошлым результатом и прогресс весов', food: 'Калории и БЖУ по фото, голосу или тексту', supply: 'Расписание добавок, отметка в одно касание и напоминания'}[domain] || 'Раздел не подключён'),
      h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn grow', onclick: () => { hide(); window.Progressor.openProductSubscriptions?.(domain); }}, 'Подключить'),
        h('button', {type: 'button', class: 'ph-btn light', onclick: () => { hide(); window.Progressor.openBundle?.(); }}, 'Все три')));
  }
  function plainTile(cls, title, text) {
    return h('div', {class: 'ph-tile ' + cls}, ring(NaN), h('h2', null, title), h('p', null, text),
      text.startsWith('Не') ? h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn grow', onclick: load}, 'Повторить')) : null);
  }
  function tile(domain, cls, title, build) {
    const s = state[domain];
    if (s.status === 'locked') return lockedTile(domain, cls, title);
    if (s.status === 'loading') return plainTile(cls, title, 'Загрузка…');
    if (s.status === 'error') return plainTile(cls, title, 'Не удалось загрузить');
    return build(s.data || {});
  }
  function render() {
    if (!root || !opened) return;
    const name = session?.user?.first_name, percents = [];
    const gym = tile('gym', 'gy', 'Зал', d => {
      const days = d.active_days || [], done = (d.completed_days || []).length;
      const next = days.find(x => x.day_index === d.suggested_day_index);
      const label = next ? next.label || 'День ' + next.day_index : null, choice = gymChoice(!!label);
      percents.push(days.length ? done / days.length * 100 : NaN);
      const start = kind => { try { localStorage.setItem(gymKey, kind); } catch {} closeSheet(); go({kind: kind === 'free' ? 'gym_free' : 'gym_today'}); };
      const choose = () => openSheet('gym', h('h3', null, 'Что сегодня?'),
        h('p', {class: 'ph-muted'}, state.gymHint?.sample >= 3 ? `Кнопка «Начать» выбирает то, что вы записываете чаще: по плану — ${state.gymHint.plan_sessions}, свободных — ${state.gymHint.free_sessions} из последних ${state.gymHint.sample}.` : 'Кнопка «Начать» запоминает ваш последний выбор, пока тренировок мало.'),
        label ? h('button', {type: 'button', class: 'ph-opt' + (choice === 'plan' ? ' rec' : ''), onclick: () => start('plan')}, h('b', null, label), h('small', null, 'Тренировка по вашему плану')) : null,
        h('button', {type: 'button', class: 'ph-opt' + (choice === 'free' ? ' rec' : ''), onclick: () => start('free')}, h('b', null, state.gymFree ? 'Продолжить свободную' : 'Свободная тренировка'), h('small', null, 'Добавляете упражнения по ходу')),
        h('button', {type: 'button', class: 'ph-opt', onclick: () => { closeSheet(); go({kind: 'gym_plan'}); }}, h('b', null, label ? 'Изменить план' : 'Настроить план'), h('small', null, 'Дни и упражнения программы')));
      return h('div', {class: 'ph-tile gy'}, ring(days.length ? done / days.length * 100 : NaN), h('h2', null, 'Зал'),
        h('p', null, choice === 'free' ? (state.gymFree ? 'Свободная · уже идёт' : 'Свободная тренировка') : `${label} · по плану`),
        h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn grow', onclick: () => start(choice)}, icon('play'), state.gymFree && choice === 'free' ? 'Дальше' : 'Начать'),
          h('button', {type: 'button', class: 'ph-btn ico', 'aria-label': 'Выбрать другую тренировку', onclick: choose}, icon('down'))));
    });
    const food = tile('food', 'fd', 'Еда', d => {
      const kcal = Math.round(d.totals?.kcal || 0), goal = d.goal?.kcal ? Math.round(d.goal.kcal) : null;
      const left = d.goal?.protein ? Math.max(0, Math.round(d.goal.protein - (d.totals?.protein || 0))) : null;
      percents.push(goal ? kcal / goal * 100 : NaN);
      return h('div', {class: 'ph-tile fd'}, ring(goal ? kcal / goal * 100 : NaN), h('h2', null, 'Еда'),
        h('p', null, goal ? `${kcal} из ${goal} ккал` + (left !== null ? ` · белка ещё ${left} г` : '') : `${kcal} ккал · цель не задана`),
        h('div', {class: 'ph-btns'}, h('button', {type: 'button', class: 'ph-btn grow', onclick: startPhoto}, icon('cam'), 'Фото'),
          h('button', {type: 'button', class: 'ph-btn ico', 'aria-label': 'Надиктовать, что вы съели', onclick: startVoice}, icon('mic'))),
        goal ? null : h('button', {type: 'button', class: 'ph-textlink', onclick: () => go({kind: 'food_goal'})}, 'Задать цель'));
    });
    const supply = tile('supply', 'sp', 'БАДы', () => {
      const slots = supplySlots(), total = slots.reduce((n, s) => n + s.units.reduce((m, u) => m + u.count, 0), 0), done = slots.reduce((n, s) => n + s.units.reduce((m, u) => m + u.done, 0), 0);
      const next = slots.find(s => s.units.some(u => u.pending)), pending = next ? next.units.filter(u => u.pending) : [];
      percents.push(total ? done / total * 100 : NaN);
      const text = !total ? 'На сегодня приёмов нет' : next ? `${next.title} · ${pending.length} шт · принято ${done} из ${total}` : `Все ${total} отмечены`;
      return h('div', {class: 'ph-tile sp', role: 'button', tabindex: '0', onclick: openSupplySheet, onkeydown: e => { if (e.key === 'Enter') openSupplySheet(); }},
        ring(total ? done / total * 100 : NaN), h('div', {class: 'ph-grow'}, h('h2', null, 'БАДы'), h('p', null, text)),
        next ? h('button', {type: 'button', class: 'ph-btn', onclick: e => { e.stopPropagation(); takeUnits(pending, next.title); }}, icon('ok'), 'Принял') : null);
    });
    const known = percents.filter(Number.isFinite), index = known.length ? Math.round(known.reduce((a, b) => a + Math.min(b, 100), 0) / known.length) : null;
    // Cross-product links: rules computed by Core from the owner's own records.
    const cards = (state.links?.cards || []).filter(card => !hiddenCards().has(card.key)), shown = linksOpen ? cards : cards.slice(0, 2);
    const linkCards = shown.map(card => h('div', {class: 'ph-card'}, h('b', null, card.title), h('p', null, card.text),
      h('div', {class: 'ph-card-actions'}, card.action ? h('button', {type: 'button', class: 'ph-mini', onclick: () => go({kind: card.action.kind})}, card.action.label) : null,
        h('button', {type: 'button', class: 'ph-textlink', onclick: () => { hideCard(card.key); render(); }}, 'Понятно'))));
    const link = cards.length
      ? h('div', {class: 'ph-links'}, h('div', {class: 'ph-links-head'}, h('b', null, cards.length > 1 ? 'Связки дня' : 'Связка дня'),
          cards.length > 2 ? h('button', {type: 'button', class: 'ph-textlink', 'aria-expanded': String(linksOpen), onclick: () => { linksOpen = !linksOpen; render(); }}, linksOpen ? 'Свернуть' : `Ещё ${cards.length - 2}`) : null), ...linkCards)
      : state.relationship ? h('div', {class: 'ph-link'}, h('b', null, 'Связка дня'), state.relationship)
      : h('div', {class: 'ph-link'}, h('b', null, 'Связки появятся с первыми записями'),
          h('ul', null, h('li', null, 'Тренировка → сколько белка добрать'), h('li', null, 'Еда → какие добавки она уже закрывает'), h('li', null, 'Добавки → что с чем лучше не пить вместе')));
    const week = state.links?.week, streak = state.links?.streak;
    const weekParts = week ? [week.workouts != null ? `тренировок ${week.workouts}` : null, week.food_days != null ? `питание ${week.food_days} из 7` : null, week.supply_days != null ? `добавки ${week.supply_days} из 7` : null].filter(Boolean) : [];
    const restNote = state.links?.rest_active ? h('div', {class: 'ph-week'}, h('b', null, 'Сегодня отдых'), h('p', null, 'Подсказки и напоминания на паузе до утра. Записи можно вести как обычно, серия сохранится.')) : null;
    const weekBlock = weekParts.length ? h('div', {class: 'ph-week'}, h('b', null, 'Неделя' + (state.links?.goal_label ? ` · цель: ${state.links.goal_label}` : '')), h('p', null, weekParts.join(' · ')), week.headline ? h('p', {class: 'ph-muted'}, week.headline) : null) : null;
    const streakChip = streak && streak.days > 0 ? h('div', {class: 'ph-streak' + (streak.today_recorded ? '' : ' wait'), role: 'img', 'aria-label': `Серия: ${streak.days} дн. подряд` + (streak.today_recorded ? '' : ', сегодня ещё нет записей')},
      h('b', null, String(streak.days)), h('span', null, streak.today_recorded ? 'дн. подряд' : 'серия ждёт')) : null;
    body.classList.toggle('ph-settled', painted); painted = true;
    body.replaceChildren(
      h('header', null, h('h1', null, name ? 'Привет, ' + name : 'Сегодня'), h('div', {class: 'ph-head-right'}, streakChip,
        h('div', {class: 'ph-idx', role: 'img', 'aria-label': index === null ? 'Данных за сегодня пока нет' : `День выполнен на ${index} процентов`}, h('b', null, index === null ? '—' : String(index)), h('span', null, 'день')))),
      h('div', {class: 'ph-grid'}, gym, food, supply),
      state.food.status === 'ready' ? h('button', {type: 'button', class: 'ph-ask', onclick: () => openAsk('')}, h('span', null, 'Спросить про свои данные'), h('i', {'aria-hidden': 'true'}, '→')) : null,
      restNote || link, weekBlock,
      h('div', {class: 'ph-foot'}, state.links ? h('button', {type: 'button', class: 'ph-textlink', onclick: toggleRest}, state.links.rest_active ? 'Закончить отдых' : 'Сегодня отдых') : null,
        h('button', {type: 'button', class: 'ph-textlink', onclick: openThemes}, 'Оформление'),
        h('button', {type: 'button', class: 'ph-textlink', onclick: () => { hide(); window.Progressor.openSubscriptions?.(); }}, 'Подписки')));
  }
  function build() {
    const style = h('style');
    style.textContent = `
#progressor-home{position:fixed;inset:0;z-index:30;background:var(--pg-bg,#fff);color:var(--pg-text,#10131A);overflow:auto;-webkit-overflow-scrolling:touch;font:15px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
#progressor-home *{box-sizing:border-box}#progressor-home [hidden]{display:none!important}
#progressor-home .ph-body{max-width:460px;margin:0 auto;padding:calc(18px + env(safe-area-inset-top,0px)) 16px calc(88px + env(safe-area-inset-bottom,0px))}
#progressor-home.ph-closed{background:none;pointer-events:none;overflow:visible}#progressor-home.ph-closed .ph-body{display:none}
#progressor-home .ph-shade,#progressor-home .ph-toast{pointer-events:auto}
#progressor-home .ph-idx{background:var(--pg-ink,#10131A);color:var(--pg-on-ink,#fff);border-radius:16px;padding:8px 14px;text-align:center;line-height:1.1;flex:none}
#progressor-home .ph-idx b{display:block;font-size:20px}#progressor-home .ph-idx span{font-size:11px;opacity:.72}
#progressor-home .ph-link ul{margin:6px 0 4px;padding-left:18px}#progressor-home .ph-link li{margin:3px 0;font-size:14px}
#progressor-home .ph-opt{display:block;width:100%;text-align:left;border:0;font:inherit;background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A);border-radius:16px;padding:14px;margin-top:8px;cursor:pointer}
#progressor-home .ph-opt.rec{background:#FF7A59;color:#3B1206}#progressor-home .ph-opt small{display:block;font-size:13px}
#progressor-home header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:12px}
#progressor-home h1{font-size:24px;margin:0;font-weight:700;letter-spacing:-.4px;color:inherit}
#progressor-home h2{margin:8px 0 0;font-size:18px;font-weight:700;color:inherit}#progressor-home h3{margin:0;font-size:20px;color:inherit}
#progressor-home p{margin:2px 0 0;font-size:13px}#progressor-home .ph-muted{color:var(--pg-muted,#6B7585);font-size:13px}
#progressor-home .ph-x{border:0;background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A);width:44px;height:44px;border-radius:14px;font-size:22px;line-height:1;cursor:pointer;flex:none}
#progressor-home .ph-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px 12px}
#progressor-home .ph-tile{border-radius:24px;padding:16px;min-width:0;animation:ph-rise .5s cubic-bezier(.2,.8,.2,1) both}
#progressor-home .ph-tile:nth-child(2){animation-delay:.06s}#progressor-home .ph-tile:nth-child(3){animation-delay:.12s}
#progressor-home .ph-settled .ph-tile{animation:none}
@keyframes ph-rise{from{opacity:0;transform:perspective(700px) rotateX(14deg) translateY(18px)}}
@media(prefers-reduced-motion:reduce){#progressor-home .ph-tile{animation:none}}
#progressor-home .ph-btn{transition:transform .1s,background .1s}#progressor-home .ph-btn:active{transform:translateY(2px);background:rgba(0,0,0,.26)}
#progressor-home .gy{background:linear-gradient(160deg,#FF8E70,#FF7A59 55%);color:#3B1206;box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 6px 0 #E0613F,0 20px 28px -14px rgba(255,122,89,.75)}
#progressor-home .fd{background:linear-gradient(160deg,#78E9B2,#5EE0A0 55%);color:#06311C;box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 6px 0 #3FC585,0 20px 28px -14px rgba(94,224,160,.8)}
#progressor-home .sp{background:linear-gradient(160deg,#8AC4FF,#6FB6FF 55%);color:#06254A;box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 6px 0 #4E9BEA,0 20px 28px -14px rgba(111,182,255,.8);grid-column:span 2;display:flex;align-items:center;gap:14px;cursor:pointer}
#progressor-home .sp h2{margin:0}#progressor-home .ph-grow{flex:1;min-width:0}
#progressor-home .ph-locked{background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A);box-shadow:0 6px 0 var(--pg-line,#E0E4EA);cursor:default;display:block}
#progressor-home .ph-lock{width:56px;height:56px;border-radius:50%;background:var(--pg-line,#E0E4EA);display:flex;align-items:center;justify-content:center}
#progressor-home .ph-ring svg{display:block;width:56px;height:56px}
#progressor-home .ph-ring circle{fill:none;stroke:currentColor;stroke-width:7;stroke-linecap:round}
#progressor-home .ph-ring .ph-track{opacity:.22}
#progressor-home .ph-ring text{font-size:13px;font-weight:700;fill:currentColor}
#progressor-home .ph-btns{display:flex;gap:6px;margin-top:12px}
#progressor-home .ph-btn{border:0;font:inherit;font-weight:600;font-size:14px;color:inherit;background:rgba(0,0,0,.16);border-radius:14px;padding:10px 12px;display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;min-height:44px}
#progressor-home .ph-btn.grow{flex:1}#progressor-home .ph-btn.ico{width:44px;padding:0}
#progressor-home .ph-btn.dark{background:var(--pg-ink,#10131A);color:var(--pg-on-ink,#fff)}#progressor-home .ph-btn.light{background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A)}
#progressor-home .ph-textlink{border:0;background:none;color:inherit;font:inherit;font-size:13px;text-decoration:underline;padding:14px 0;cursor:pointer;opacity:.75}
#progressor-home .ph-spin{width:38px;height:38px;border-radius:50%;border:4px solid var(--pg-line,#E6E9EF);border-top-color:#3FC585;animation:ph-r .8s linear infinite;margin:26px auto}
@keyframes ph-r{to{transform:rotate(360deg)}}@keyframes ph-w{0%,100%{height:10px}50%{height:52px}}
#progressor-home .ph-wave{display:flex;gap:4px;align-items:center;justify-content:center;height:64px;margin:12px 0 4px}
#progressor-home .ph-wave i{width:5px;border-radius:3px;background:#3FC585;animation:ph-w 1s infinite ease-in-out}
#progressor-home .ph-clock{display:block;text-align:center;font-size:18px}
#progressor-home .ph-photo{width:100%;height:150px;object-fit:cover;border-radius:16px;margin:8px 0;background:var(--pg-surface,#F3F4F7);display:block}
#progressor-home .ph-heard{background:var(--pg-surface,#F3F4F7);border-radius:16px;padding:12px 14px;font-size:15px;margin:8px 0}
#progressor-home textarea{width:100%;border:1.5px solid var(--pg-line,#E6E9EF);border-radius:16px;padding:12px 14px;font:inherit;font-size:16px;color:var(--pg-text,#10131A);background:var(--pg-raise,#fff);margin-top:8px;resize:vertical}
#progressor-home .ph-item{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--pg-line,#E6E9EF)}
#progressor-home .ph-item small{color:var(--pg-muted,#6B7585);display:block}
#progressor-home .ph-step{display:flex;align-items:center;gap:4px}
#progressor-home .ph-step button{width:44px;height:44px;border-radius:12px;border:0;background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A);font-size:20px;cursor:pointer}
#progressor-home .ph-step span{min-width:54px;text-align:center;font-weight:600}
#progressor-home .ph-pair{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--pg-tint-supply,#DEEBFF);color:var(--pg-tint-supply-text,#06254A);border-radius:16px;padding:10px 12px;margin-top:10px;font-size:14px}
#progressor-home .ph-tot{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0 4px;text-align:center}
#progressor-home .ph-tot div{background:#5EE0A0;color:#06311C;border-radius:14px;padding:8px 4px}
#progressor-home .ph-tot b{display:block;font-size:17px}#progressor-home .ph-tot span{font-size:11px}
@media(prefers-reduced-motion:reduce){#progressor-home .ph-wave i,#progressor-home .ph-spin{animation:none}}#progressor-home .ph-locked .ph-btn{background:var(--pg-ink,#10131A);color:var(--pg-on-ink,#fff)}
#progressor-home .ph-i{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
#progressor-home .ph-foot{display:flex;gap:18px}
#progressor-home .ph-ask{display:flex;justify-content:space-between;align-items:center;width:100%;margin-top:18px;border:1.5px solid var(--pg-line,#E6E9EF);background:var(--pg-raise,#fff);color:var(--pg-muted,#6B7585);border-radius:18px;min-height:52px;padding:0 16px;font:inherit;font-size:15px;cursor:pointer}
#progressor-home .ph-ask i{font-style:normal;color:var(--pg-text,#10131A);font-size:18px}
#progressor-home .ph-answer{background:var(--pg-surface,#F3F4F7);border-radius:16px;padding:12px 14px;margin-top:12px}
#progressor-home .ph-answer p{font-size:15px;margin:0 0 8px}#progressor-home .ph-answer p:last-child{margin-bottom:0}
#progressor-home .ph-sheet .ph-chips{margin-top:8px}
#progressor-home .ph-head-right{display:flex;gap:8px;align-items:stretch;flex:none}
#progressor-home .ph-streak{background:var(--pg-tint-gym,#FFE7DF);color:var(--pg-tint-gym-text,#3B1206);border-radius:16px;padding:8px 12px;text-align:center;line-height:1.1}
#progressor-home .ph-streak.wait{background:var(--pg-surface,#F3F4F7);color:var(--pg-muted,#6B7585)}
#progressor-home .ph-streak b{display:block;font-size:20px}#progressor-home .ph-streak span{font-size:11px}
#progressor-home .ph-links{margin-top:20px;display:grid;gap:8px}
#progressor-home .ph-links-head{display:flex;justify-content:space-between;align-items:center}
#progressor-home .ph-links-head b{font-size:13px;color:var(--pg-muted,#6B7585);font-weight:600}
#progressor-home .ph-links-head .ph-textlink{padding:4px 0}
#progressor-home .ph-card{background:var(--pg-surface,#F3F4F7);border-radius:20px;padding:14px 16px}
#progressor-home .ph-card b{display:block;font-size:15px}
#progressor-home .ph-card p{font-size:14px;margin:4px 0 0}
#progressor-home .ph-card-actions{display:flex;align-items:center;gap:14px;margin-top:10px}
#progressor-home .ph-card-actions .ph-textlink{padding:0;margin-left:auto}
#progressor-home .ph-foot{flex-wrap:wrap}
#progressor-home .ph-card .ph-mini{background:var(--pg-ink,#10131A);color:var(--pg-on-ink,#fff)}
#progressor-home .ph-week{background:var(--pg-surface,#F3F4F7);border-radius:20px;padding:14px 16px;margin-top:8px}
#progressor-home .ph-week b{display:block;font-size:13px;color:var(--pg-muted,#6B7585);font-weight:600;margin-bottom:2px}
#progressor-home .ph-week p{font-size:14px}
#progressor-home .ph-themes{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:10px;margin-top:8px}
#progressor-home .ph-theme{border:2px solid transparent;border-radius:18px;padding:10px 8px;background:var(--pg-surface,#F3F4F7);color:var(--pg-text,#10131A);font:inherit;font-size:13px;font-weight:600;cursor:pointer;display:grid;gap:8px;justify-items:center}
#progressor-home .ph-theme[aria-pressed=true]{border-color:var(--pg-ink,#10131A)}
#progressor-home .ph-theme i{width:100%;height:44px;border-radius:12px;border:1px solid var(--pg-line,#E6E9EF)}
#progressor-home .ph-theme[data-theme-name=classic] i{background:linear-gradient(135deg,#fff 50%,#0E1014 50%)}
#progressor-home .ph-theme[data-theme-name=sand] i{background:linear-gradient(135deg,#FBF7F0 50%,#221C15 50%)}
#progressor-home .ph-theme[data-theme-name=graphite] i{background:linear-gradient(135deg,#E9EBEF 50%,#15171B 50%)}
#progressor-home .ph-theme[data-theme-name=ocean] i{background:linear-gradient(135deg,#E6EFF8 50%,#101E2E 50%)}
#progressor-home .ph-theme[data-theme-name=forest] i{background:linear-gradient(135deg,#E7EFE5 50%,#132016 50%)}
#progressor-home .ph-link{background:var(--pg-surface,#F3F4F7);border-radius:20px;padding:14px 16px;margin-top:20px}
#progressor-home .ph-link b{display:block;font-size:13px;color:var(--pg-muted,#6B7585);font-weight:600;margin-bottom:2px}
#progressor-home .ph-shade{position:fixed;inset:0;z-index:2;background:rgba(10,12,18,.45);display:flex;align-items:flex-end;justify-content:center}
#progressor-home .ph-sheet{background:var(--pg-raise,#fff);width:100%;max-width:460px;border-radius:26px 26px 0 0;padding:16px 16px calc(26px + env(safe-area-inset-bottom,0px));max-height:86vh;overflow:auto}
#progressor-home .ph-sheet-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:4px}
#progressor-home .ph-slot{margin-top:14px}
#progressor-home .ph-slot-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px}
#progressor-home .ph-slot-head span{color:var(--pg-muted,#6B7585);font-weight:400}
#progressor-home .ph-chips{display:flex;flex-wrap:wrap;gap:8px}
#progressor-home .ph-chip{border:1.5px solid var(--pg-line,#E6E9EF);background:var(--pg-raise,#fff);border-radius:14px;padding:9px 12px;font:inherit;font-size:14px;cursor:pointer;color:var(--pg-text,#10131A);min-height:44px}
#progressor-home .ph-chip.on{background:#6FB6FF;border-color:#6FB6FF;color:#06254A}
#progressor-home .ph-mini{border:0;font:inherit;font-size:13px;font-weight:600;background:#6FB6FF;color:#06254A;border-radius:10px;padding:0 12px;min-height:44px;cursor:pointer}
#progressor-home .ph-toast{position:fixed;left:50%;bottom:calc(76px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);z-index:3;background:var(--pg-ink,#10131A);color:var(--pg-on-ink,#fff);border-radius:14px;padding:11px 14px;font-size:14px;display:flex;align-items:center;gap:10px;max-width:calc(100% - 32px)}
#progressor-home .ph-toast button{border:0;background:#6FB6FF;color:#06254A;font:inherit;font-weight:600;border-radius:10px;padding:8px 10px;cursor:pointer}`;
    document.head.append(style);
    body = h('div', {class: 'ph-body'});
    sheet = h('div', {class: 'ph-shade', hidden: true, onclick: e => { if (e.target === sheet) closeSheet(); }});
    toastNode = h('div', {class: 'ph-toast', role: 'status', hidden: true});
    root = h('section', {id: 'progressor-home', 'aria-label': 'Сегодня', class: 'ph-closed'}, body, sheet, toastNode);
    document.body.append(root);
  }
  function show() {
    if (!root) build();
    opened = true; painted = false; root.classList.remove('ph-closed');
    try { sessionStorage.setItem(seenKey, '1'); } catch {}
    document.dispatchEvent(new CustomEvent('progressor:home', {detail: {open: true}}));
    render(); void load();
  }
  function hide() {
    if (!root || !opened) return;
    generation++; closeSheet(); toastNode.hidden = true; opened = false; root.classList.add('ph-closed');
    document.dispatchEvent(new CustomEvent('progressor:home', {detail: {open: false}}));
  }
  document.addEventListener('progressor:overlay-open', hide);
  document.addEventListener('visibilitychange', () => { if (root && opened && !document.hidden && !busy && !sheetKind) void load(); });
  window.Progressor._home = true;
  window.Progressor.openHome = show;
  window.Progressor.closeHome = hide;
  window.Progressor.homeOpen = () => opened;
  // The same capture sheets serve a product page while the home screen is closed.
  window.Progressor.capture = {photo: () => { if (!root) build(); startPhoto(); }, voice: () => { if (!root) build(); return startVoice(); }, text: () => { if (!root) build(); textSheet(''); }};
  // First launch of this tab only; a cross-product arrival keeps its requested native screen.
  const params = new URLSearchParams(location.search);
  let seen = true; try { seen = sessionStorage.getItem(seenKey) === '1'; } catch {}
  if (!seen && !params.has('progressor_action') && !params.has('progressor_return') && !params.has('progressor_subscription')) show();
})();
