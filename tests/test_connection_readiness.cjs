/* Run: node tests/test_connection_readiness.cjs
 * Executes the whole canonical asset with a small deterministic DOM/event seam.
 * No browser dependency, network, providers or host-app/layout claim.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const asset=fs.readFileSync(process.argv[2]||path.join(__dirname,'../shared/connections.v1.js'),'utf8');
const clone=v=>JSON.parse(JSON.stringify(v));
const pending='Проверяем…',unknown='Сейчас не удалось проверить участие данных. Обновите обзор дня.';
const unsaved='Изменение не сохранено. Нажмите «Сохранить связи».';
const sources=['food','gym','supply'];
function settings(enabled=true,revision=0){return {preferences:{revision,sources:{food:true,gym:true,supply:enabled},rest_active:false,frequency:'normal',weekly_day:'monday',weekly_hour:10,excluded_food_groups:[]},weight:{items:[],explanation:''},coach:{items:[],explanation:''},food_groups:[],help:[],rhythm:{proposal:{status:'unavailable',message:'No fixture rhythm'},active:false}};}
function today(status='stale'){
 const reasons={ready:['Данные актуальны','Сохранённые записи участвуют в общей картине.'],stale:['Обновление временно задерживается','Старые данные не используются для новых подсказок. Попробуйте обновить позже.'],consent_required:['Нужно согласие в Supply','Подтвердите использование данных в собственном профиле Supply.'],disabled:['Связь выключена вами','Её можно включить в разделе «Связи и напоминания».'],paused:['Сейчас отдых','Подсказки и напоминания на паузе. Записи и сроки подписок сохраняются.'],access_required:['Для связи нужен активный доступ','История сохраняется.']};
 const [label,message]=reasons[status]||['Unknown future label','Unknown future message'];
 return {sections:[{source:'food',name:'Food',text:'One recorded meal'}],health:{items:[{source:'supply',name:'Supply',status,label,message}],hints_enabled:true,notifications_enabled:true,rest_active:status==='paused'},generated_at:'2026-10-23T00:00:00Z',day_label:'Fixture Moscow journal day',coverage:'Only saved records'};
}
function harness({ignoreAbort=false}={}){
 const requests=[],timers=[];let document;
 class Node{
  constructor(tag){this.tagName=tag;this.parentElement=null;this.children=[];this.dataset={};this.attrs={};this.listeners={};this.style={};this.checked=false;this.disabled=false;this.open=false;this._text='';}
  append(child){if(child.parentElement)child.remove();child.parentElement=this;this.children.push(child);}
  replaceChildren(...children){for(const child of this.children)child.parentElement=null;this.children=[];this._text='';for(const child of children)this.append(child);}
  set textContent(value){this.replaceChildren();this._text=String(value??'');}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  setAttribute(name,value){this.attrs[name]=String(value);if(name==='id')this.id=String(value);if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(value);}
  getAttribute(name){return this.attrs[name]??null;}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  dispatchEvent(event){event.target=this;return Promise.all((this.listeners[event.type]||[]).map(fn=>fn(event)));}
  focus(){document.activeElement=this;}
  showModal(){this.open=true;}
  close(){this.open=false;void this.dispatchEvent({type:'close'});}
  remove(){if(this.parentElement){const parent=this.parentElement;parent.children=parent.children.filter(n=>n!==this);this.parentElement=null;}}
  get isConnected(){return this===document.head||this===document.body||!!this.parentElement?.isConnected;}
  getBoundingClientRect(){return {height:this.measuredHeight??60};}
  // Closed-details descendants may still report rectangles in the observed browser.
  // This generic seam intentionally leaves that exclusion to the actual key handler.
  getClientRects(){return this.isConnected?[this.getBoundingClientRect()]:[];}
  contains(node){for(let n=node;n;n=n.parentElement)if(n===this)return true;return false;}
  closest(selector){for(let n=this;n;n=n.parentElement)if(n.matches(selector))return n;return null;}
  matches(selector){
   const enabled=selector.match(/^(button|input|select|textarea):not\(:disabled\)$/);
   if(enabled)return this.tagName===enabled[1]&&!this.disabled;
   if(selector==='a[href]')return this.tagName==='a'&&this.getAttribute('href')!==null;
   if(selector==='[tabindex="0"]')return this.getAttribute('tabindex')==='0';
   if(selector==='[hidden]')return !!this.hidden||this.getAttribute('hidden')!==null;
   if(selector.startsWith('#'))return this.id===selector.slice(1);
   const data=selector.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);
   if(data){const key=data[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return Object.hasOwn(this.dataset,key)&&(data[2]===undefined||this.dataset[key]===data[2]);}
   return this.tagName===selector;
  }
  querySelectorAll(selector){const selectors=selector.split(',').map(s=>s.trim()),all=[];for(const child of this.children){if(selectors.some(s=>child.matches(s)))all.push(child);all.push(...child.querySelectorAll(selector));}return all;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 }
 document={head:new Node('head'),body:new Node('body'),currentScript:{dataset:{progressorSource:'food'}},hidden:false,listeners:{},createElement:tag=>new Node(tag),addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},dispatchEvent(){},querySelector(selector){return this.head.querySelector(selector)||this.body.querySelector(selector);}};
 const launcher=new Node('button');document.body.append(launcher);launcher.focus();
 const events=()=>({listeners:{},addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(value=>value!==fn);},dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn(event);}});
 const window={Progressor:{ready:Promise.resolve()},...events()};document.fonts=events();
 const env={window,document,fetch:(url,options)=>new Promise((resolve,reject)=>{
   requests.push({url,options,reply:(body,status=200)=>resolve({ok:status>=200&&status<300,status,json:async()=>clone(body)})});
   options.signal?.addEventListener('abort',()=>{if(!ignoreAbort)reject(Error('Synthetic request aborted'));},{once:true});
  }),
  Event:class{constructor(type){this.type=type;}},AbortController,Intl,Date,console,crypto:{randomUUID:()=> 'fixture-id'},setInterval:()=>1,clearInterval(){},
  setTimeout:(fn,ms)=>{timers.push({fn,ms,active:true});return timers.length;},clearTimeout:id=>{if(timers[id-1])timers[id-1].active=false;},location:{pathname:'/webapp/'}};
 vm.runInNewContext(asset,env,{filename:'shared/connections.v1.js'});
 // Traverse without selectors when checking semantic controls.
 const descendants=n=>[n,...n.children.flatMap(descendants)];
 const findButton=text=>descendants(document.body).find(n=>n.tagName==='button'&&n.textContent===text);
 const note=()=>document.body.querySelector('#progressor-source-readiness-supply');
 const input=()=>descendants(document.body).find(n=>n.tagName==='label'&&n.textContent==='Supply участвует в связях').querySelector('input');
 const toggle=checked=>{input().checked=checked;void input().dispatchEvent({type:'change'});};
 const flush=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
 const take=(method='GET',suffix='')=>{const index=requests.findIndex(r=>r.options.method===method&&r.url==='/progressor/api/v1/me/connections'+suffix);assert.ok(index>=0,'expected request '+method+' '+suffix);return requests.splice(index,1)[0];};
 const open=async(value=settings(),body=today())=>{const call=window.Progressor.openConnections();await flush();take().reply(value);await flush();take('GET','/today?target=food').reply(body);await call;await flush();};
 const fireTimeout=ms=>{const active=timers.filter(t=>t.active&&t.ms===ms);assert.equal(active.length,1,'one owned timeout');for(const t of active){t.active=false;t.fn();}};
 let authState;const bridge={source:'food',getState:()=>authState};const setAuth=(owner,proof)=>{authState={launchData:proof,session:{user:{id:owner}}};window.Progressor._launchBridge=bridge;};
 return {document,window,launcher,requests,note,input,toggle,flush,take,open,fireTimeout,setAuth,notes:()=>document.body.querySelectorAll('[data-source-readiness]'),closeButton:()=>findButton('×'),close:()=>document.body.querySelector('#progressor-connections').close(),click:text=>{const button=findButton(text);assert.ok(button,'button '+text);return button.dispatchEvent({type:'click'});}};
}

// These preference cases exercise public UI/partial-request boundaries, not a
// copy of the draft implementation. Captured real-B values are replayed separately.
function draftSettings(){const value=settings();Object.assign(value.preferences,{sources:{gym:true,food:true,supply:true},hints:true,notifications:true,weight_notifications:false,goal_links:true,weekly_plan:true,weekly_day:'monday',weekly_hour:10,diet:'any',excluded_food_groups:[],day_prompt:true,paused:false,pause_until:null});value.food_groups=['fish','eggs'];return value;}
function draftToday(p){const value=today(p.rest_active?'paused':p.sources.supply===false?'disabled':'ready');value.health.hints_enabled=!!p.hints;value.health.notifications_enabled=!!p.notifications;return value;}
function preferenceControls(h){
 const all=n=>[n,...n.children.flatMap(all)],section=title=>all(h.document.body).find(n=>n.tagName==='details'&&n.children[0]?.textContent===title);
 const weekly=section('Один план питания в неделю'),food=section('Пищевые предпочтения'),day=section('Итог дня без обязательных отметок');
 return {source:h.input(),weekly:weekly.querySelector('input'),weekday:weekly.querySelectorAll('select')[0],hour:weekly.querySelectorAll('select')[1],diet:food.querySelector('select'),fish:all(food).find(n=>n.tagName==='label'&&n.textContent==='Исключить: Рыба')?.querySelector('input'),day:day?.querySelector('input')};
}
const noticeText=h=>h.document.body.querySelector('#progressor-connections').querySelectorAll('p').find(n=>n.getAttribute('role')==='status').textContent;
const connectionKeys=['sources','hints','notifications','weight_notifications','goal_links','frequency'];
async function confirmPreferences(h,label,server,keys,beforeFresh){
 const saving=h.click(label);await h.flush();const post=h.take('POST'),body=JSON.parse(post.options.body);
 assert.equal(body.action,'preferences');assert.equal(body.revision,server.revision);assert.deepEqual(Object.keys(body.patch).sort(),[...keys].sort());
 const next={...clone(server),...clone(body.patch),revision:server.revision+1};next.rest_active=!!next.paused;
 post.reply({preferences:next});await saving;await h.flush();if(beforeFresh)beforeFresh();h.take('GET','/today?target=food').reply(draftToday(next));await h.flush();assert.equal(h.requests.length,0);
 return {next,body};
}

async function main(){const passed=[];async function test(name,fn){try{await fn();passed.push(name);}catch(error){console.log(JSON.stringify({passed:false,cases:passed.length,names:passed,failed_case:name,network_or_provider_calls:0}));throw error;}}
 for(const status of ['stale','consent_required','access_required','ready','disabled','paused','future_status'])await test('inline '+status,async()=>{
  const h=harness(),enabled=status!=='disabled';await h.open(settings(enabled),today(status));assert.equal(h.input().checked,enabled);
  if(status==='future_status')assert.equal(h.note().textContent,unknown);
  else{assert.ok(h.note().textContent.includes(today(status).health.items[0].label));if(status==='consent_required')assert.ok(h.note().textContent.includes('условия и политику конфиденциальности'));}
 });
 await test('missing source remains unknown',async()=>{const h=harness(),body=today();body.health.items=[];await h.open(settings(),body);assert.equal(h.note().textContent,unknown);});
 for(const failure of [false,true])await test('old settings GET '+(failure?'failure':'success')+' cannot overwrite reopened draft',async()=>{
  const h=harness(),oldOpen=h.window.Progressor.openConnections();await h.flush();const old=h.take();h.close();await h.open();h.toggle(false);assert.equal(h.note().textContent,unsaved);
  old.reply(settings(),failure?503:200);await oldOpen;await h.flush();assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);
 });
 for(const failure of [false,true])await test('old preferences POST '+(failure?'failure':'success')+' cannot overwrite reopened draft',async()=>{
  const h=harness();await h.open();h.toggle(false);const click=h.click('Сохранить связи');await h.flush();const old=h.take('POST');assert.equal(JSON.parse(old.options.body).revision,0);
  h.close();await h.open(settings(false,1),today('disabled'));h.toggle(true);assert.equal(h.note().textContent,unsaved);
  old.reply({preferences:settings(false,1).preferences},failure?503:200);await click;await h.flush();assert.equal(h.input().checked,true);assert.equal(h.input().disabled,false);assert.equal(h.note().textContent,unsaved);
 });
 await test('current CAS409 preserves draft and provides explicit refresh',async()=>{
  const h=harness();await h.open();h.toggle(false);const click=h.click('Сохранить связи');await h.flush();const post=h.take('POST');assert.equal(JSON.parse(post.options.body).revision,0);post.reply({},409);await click;await h.flush();
  assert.equal(h.input().checked,false);assert.equal(h.input().disabled,false);assert.equal(h.note().textContent,unsaved);assert.ok(h.document.body.textContent.includes('Данные изменились в другом окне'));
  const refresh=h.click('Обновить данные');await h.flush();h.take().reply(settings(true,2));await refresh;await h.flush();assert.equal(h.input().checked,true);assert.equal(h.note().textContent,pending);
  h.take('GET','/today?target=food').reply(today('ready'));await h.flush();assert.ok(h.note().textContent.includes('Данные актуальны'));
 });
 await test('late today keeps unsaved selection, error clears old readiness',async()=>{
  const h=harness();await h.open(settings(),today('ready'));const update=h.click('Обновить обзор дня');await h.flush();const response=h.take('GET','/today?target=food');assert.equal(h.note().textContent,pending);h.toggle(false);response.reply(today('ready'));await update;await h.flush();assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);
  h.toggle(true);const fail=h.click('Обновить обзор дня');await h.flush();h.take('GET','/today?target=food').reply({},503);await fail;assert.equal(h.note().textContent,unknown);
 });
 await test('failed reopened settings has working retry and preserves launcher focus',async()=>{
  const h=harness();await h.open();h.close();const reopen=h.window.Progressor.openConnections();await h.flush();h.take().reply({},503);await reopen;await h.flush();
  assert.equal(h.note(),null);assert.ok(h.document.body.textContent.includes('Повторить загрузку настроек'));
  await h.click('Повторить загрузку настроек');await h.flush();h.take().reply(settings());await h.flush();h.take('GET','/today?target=food').reply(today('ready'));await h.flush();
  assert.ok(h.note().textContent.includes('Данные актуальны'));h.close();assert.equal(h.document.activeElement,h.launcher);
 });
 await test('read retry remains usable while an old writer response is pending',async()=>{
  const h=harness();await h.open();h.toggle(false);const writing=h.click('Сохранить связи');await h.flush();const old=h.take('POST');h.close();
  const reopen=h.window.Progressor.openConnections();await h.flush();h.take().reply({},503);await reopen;await h.click('Повторить загрузку настроек');await h.flush();
  h.take().reply(settings(false,1));await h.flush();h.take('GET','/today?target=food').reply(today('disabled'));await h.flush();h.toggle(true);
  old.reply({preferences:settings(false,1).preferences});await writing;assert.equal(h.input().checked,true);assert.equal(h.note().textContent,unsaved);
 });
 await test('old bridge readiness rejection cannot replace the reopened view',async()=>{
  const h=harness();let reject;h.window.Progressor.ready=new Promise((resolve,fail)=>{reject=fail;});
  const oldOpen=h.window.Progressor.openConnections();await h.flush();assert.equal(h.requests.length,0);h.close();
  h.window.Progressor.ready=Promise.resolve();await h.open();h.toggle(false);reject(Error('obsolete bridge error'));await oldOpen;await h.flush();
  assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);assert.ok(!h.document.body.textContent.includes('obsolete bridge error'));
 });
 await test('pending preferences save locks its fields and leaves Close available',async()=>{
  const h=harness();await h.open();h.toggle(false);const saving=h.click('Сохранить связи');await h.flush();const post=h.take('POST');
  assert.equal(h.input().disabled,true);assert.equal(h.closeButton().disabled,false);
  assert.ok(h.document.body.querySelectorAll('select').every(field=>field.disabled));
  post.reply({preferences:settings(false,1).preferences});await saving;await h.flush();
  assert.equal(h.input().checked,false);assert.equal(h.input().disabled,false);h.take('GET','/today?target=food').reply(today('disabled'));await h.flush();
 });
 await test('settings GET timeout has explicit retry and late old completion is ignored',async()=>{
  const h=harness(),opening=h.window.Progressor.openConnections();await h.flush();const old=h.take();h.fireTimeout(8000);await opening;await h.flush();
  assert.equal(h.note(),null);assert.ok(h.document.body.textContent.includes('Повторить загрузку настроек'));assert.equal(h.closeButton().disabled,false);
  await h.click('Повторить загрузку настроек');await h.flush();h.take().reply(settings());await h.flush();h.take('GET','/today?target=food').reply(today('ready'));await h.flush();h.toggle(false);
  old.reply(settings(false,9));await h.flush();assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);
 });
 await test('preferences timeout restores fields and never claims unconfirmed success',async()=>{
  const h=harness();await h.open();h.toggle(false);const saving=h.click('Сохранить связи');await h.flush();const old=h.take('POST');assert.equal(h.input().disabled,true);
  h.fireTimeout(8000);await saving;await h.flush();assert.equal(h.input().disabled,false);assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);
  assert.ok(h.document.body.textContent.includes('Не удалось получить подтверждение'));assert.ok(!h.document.body.textContent.includes('Настройки сохранены'));
  h.close();await h.open(settings(false,1),today('disabled'));h.toggle(true);old.reply({preferences:settings(false,1).preferences});await h.flush();
  assert.equal(h.input().checked,true);assert.equal(h.input().disabled,false);assert.equal(h.note().textContent,unsaved);
 });
 await test('refresh reserves each measured note and restores natural same-result layout',async()=>{
  const h=harness();await h.open(settings(),today('ready'));const notes=h.notes();notes.forEach((note,i)=>note.measuredHeight=75+i*37.5);
  const refresh=h.click('Обновить обзор дня');await h.flush();notes.forEach((note,i)=>assert.equal(note.style.minHeight,(75+i*37.5)+'px'));assert.equal(h.note().textContent,pending);
  h.take('GET','/today?target=food').reply(today('ready'));await refresh;await h.flush();for(const note of notes)assert.equal(note.style.minHeight,'');assert.ok(h.note().textContent.includes('Данные актуальны'));
 });
 await test('new long reason and failed refresh release loading-only height',async()=>{
  const h=harness();await h.open(settings(),today('ready'));h.note().measuredHeight=75;const change=h.click('Обновить обзор дня');await h.flush();
  const changed=today('stale');changed.health.items[0].message='Причина остаётся полностью видимой. '.repeat(12);h.take('GET','/today?target=food').reply(changed);await change;await h.flush();assert.equal(h.note().style.minHeight,'');assert.ok(h.note().textContent.includes(changed.health.items[0].message));
  const fail=h.click('Обновить обзор дня');await h.flush();h.take('GET','/today?target=food').reply({},503);await fail;assert.equal(h.note().style.minHeight,'');assert.equal(h.note().textContent,unknown);
 });
 await test('resize/fonts/close invalidate reservations without retaining listeners',async()=>{
  const h=harness();await h.open();assert.equal(h.window.listeners.resize.length,1);assert.equal(h.document.fonts.listeners.loadingdone.length,1);
  const refresh=h.click('Обновить обзор дня');await h.flush();assert.ok(h.note().style.minHeight);h.window.dispatchEvent({type:'resize'});assert.equal(h.note().style.minHeight,'');h.take('GET','/today?target=food').reply(today());await refresh;
  const fonts=h.click('Обновить обзор дня');await h.flush();assert.ok(h.note().style.minHeight);h.document.fonts.dispatchEvent({type:'loadingdone'});assert.equal(h.note().style.minHeight,'');h.take('GET','/today?target=food').reply(today());await fonts;
  h.close();assert.equal(h.window.listeners.resize.length,0);assert.equal(h.document.fonts.listeners.loadingdone.length,0);await h.open();assert.equal(h.window.listeners.resize.length,1);
 });

 await test('unrelated dirty source survives a weekly-only acknowledgement',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);preferenceControls(h).hour.value=12;
  const {next}=await confirmPreferences(h,'Сохранить время сводки',value.preferences,['weekly_plan','weekly_day','weekly_hour'],()=>{assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);});
  assert.equal(next.sources.supply,true);assert.equal(next.weekly_hour,12);assert.equal(Number(preferenceControls(h).hour.value),12);assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);assert.ok(noticeText(h).includes('В других разделах есть несохранённые изменения'));
 });
 await test('weekly draft survives connections save and next scoped save uses acknowledged revision',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));preferenceControls(h).weekly.checked=false;preferenceControls(h).weekday.value='sunday';preferenceControls(h).hour.value=13;h.toggle(false);
  const first=await confirmPreferences(h,'Сохранить связи',value.preferences,connectionKeys);assert.equal(first.next.weekly_plan,true);assert.equal(first.next.weekly_hour,10);assert.equal(preferenceControls(h).weekly.checked,false);assert.equal(preferenceControls(h).weekday.value,'sunday');assert.equal(Number(preferenceControls(h).hour.value),13);assert.equal(h.input().checked,false);assert.ok(noticeText(h).includes('несохранённые'));
  const second=await confirmPreferences(h,'Сохранить время сводки',first.next,['weekly_plan','weekly_day','weekly_hour']);assert.equal(second.body.revision,1);assert.equal(second.next.weekly_plan,false);assert.equal(second.next.weekly_hour,13);assert.equal(noticeText(h),'Настройки сохранены.');
 });
 await test('diet and exclusions survive connections save without leaking into its patch',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));preferenceControls(h).diet.value='vegan';preferenceControls(h).fish.checked=true;h.toggle(false);
  const first=await confirmPreferences(h,'Сохранить связи',value.preferences,connectionKeys);assert.equal(first.next.diet,'any');assert.deepEqual(first.next.excluded_food_groups,[]);assert.equal(preferenceControls(h).diet.value,'vegan');assert.equal(preferenceControls(h).fish.checked,true);assert.ok(noticeText(h).includes('несохранённые'));
  const second=await confirmPreferences(h,'Сохранить предпочтения',first.next,['diet','excluded_food_groups']);assert.equal(second.next.diet,'vegan');assert.deepEqual(second.next.excluded_food_groups,['fish']);assert.equal(noticeText(h),'Настройки сохранены.');
 });
 await test('false and cleared exclusion drafts survive a rest acknowledgement',async()=>{
  const h=harness(),value=draftSettings();value.preferences.excluded_food_groups=['fish'];await h.open(value,draftToday(value.preferences));preferenceControls(h).weekly.checked=false;preferenceControls(h).fish.checked=false;preferenceControls(h).day.checked=false;h.toggle(false);
  const {next}=await confirmPreferences(h,'Отдохнуть от напоминаний',value.preferences,['paused','pause_until']);assert.equal(next.paused,true);assert.equal(next.rest_active,true);assert.equal(next.weekly_plan,true);assert.deepEqual(next.excluded_food_groups,['fish']);assert.equal(next.day_prompt,true);assert.equal(preferenceControls(h).weekly.checked,false);assert.equal(preferenceControls(h).fish.checked,false);assert.equal(preferenceControls(h).day.checked,false);assert.equal(h.input().checked,false);assert.equal(h.note().textContent,unsaved);assert.ok(h.document.body.textContent.includes('Сейчас отдых.'));assert.ok(noticeText(h).includes('несохранённые'));
 });
 await test('day-question-only save preserves weekly and food drafts',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));preferenceControls(h).hour.value=14;preferenceControls(h).diet.value='vegetarian';preferenceControls(h).day.checked=false;
  const {next}=await confirmPreferences(h,'Сохранить настройку вопроса',value.preferences,['day_prompt']);assert.equal(next.day_prompt,false);assert.equal(next.weekly_hour,10);assert.equal(next.diet,'any');assert.equal(Number(preferenceControls(h).hour.value),14);assert.equal(preferenceControls(h).diet.value,'vegetarian');assert.equal(preferenceControls(h).day.checked,false);assert.ok(noticeText(h).includes('несохранённые'));
 });
 await test('display defaults and unordered sets do not create phantom remaining drafts',async()=>{
  for(const value of [settings(),draftSettings()]){if(value.food_groups.length)value.preferences.excluded_food_groups=['eggs','fish'];const h=harness();await h.open(value,draftToday(value.preferences));preferenceControls(h).hour.value=11;await confirmPreferences(h,'Сохранить время сводки',value.preferences,['weekly_plan','weekly_day','weekly_hour']);assert.equal(noticeText(h),'Настройки сохранены.');}
 });
 await test('a reverted draft is not advertised as remaining after another save',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);h.toggle(true);preferenceControls(h).hour.value=11;await confirmPreferences(h,'Сохранить время сводки',value.preferences,['weekly_plan','weekly_day','weekly_hour']);assert.equal(h.input().checked,true);assert.equal(noticeText(h),'Настройки сохранены.');
 });
 await test('failed partial save leaves every pending preference and fields usable',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);preferenceControls(h).hour.value=12;preferenceControls(h).diet.value='vegan';const saving=h.click('Сохранить время сводки');await h.flush();h.take('POST').reply({},503);await saving;await h.flush();assert.equal(h.input().checked,false);assert.equal(h.input().disabled,false);assert.equal(Number(preferenceControls(h).hour.value),12);assert.equal(preferenceControls(h).diet.value,'vegan');assert.equal(h.requests.length,0);assert.ok(!noticeText(h).includes('Настройки сохранены'));
 });
 await test('409 preserves all preference drafts and explicit refresh still resets them',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);preferenceControls(h).hour.value=12;preferenceControls(h).diet.value='vegan';const saving=h.click('Сохранить время сводки');await h.flush();h.take('POST').reply({},409);await saving;await h.flush();assert.equal(h.input().checked,false);assert.equal(Number(preferenceControls(h).hour.value),12);assert.equal(preferenceControls(h).diet.value,'vegan');assert.ok(noticeText(h).includes('сбросит несохранённый выбор'));
  const fresh=h.click('Обновить данные');await h.flush();h.take().reply(value);await fresh;await h.flush();h.take('GET','/today?target=food').reply(draftToday(value.preferences));await h.flush();assert.equal(h.input().checked,true);assert.equal(Number(preferenceControls(h).hour.value),10);assert.equal(preferenceControls(h).diet.value,'any');
 });
 await test('unconfirmed partial write never acknowledges or loses other drafts',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);preferenceControls(h).hour.value=12;preferenceControls(h).diet.value='vegan';const saving=h.click('Сохранить время сводки');await h.flush();const old=h.take('POST');h.fireTimeout(8000);await saving;await h.flush();old.reply({preferences:{...value.preferences,weekly_hour:12,revision:1}});await h.flush();assert.equal(h.input().checked,false);assert.equal(h.input().disabled,false);assert.equal(Number(preferenceControls(h).hour.value),12);assert.equal(preferenceControls(h).diet.value,'vegan');assert.ok(noticeText(h).includes('Не удалось получить подтверждение'));assert.equal(h.requests.length,0);
 });
 for(const failure of [false,true])await test('old partial '+(failure?'failure':'success')+' cannot reapply captured drafts to reopened view',async()=>{
  const h=harness(),value=draftSettings();await h.open(value,draftToday(value.preferences));h.toggle(false);preferenceControls(h).hour.value=12;const saving=h.click('Сохранить время сводки');await h.flush();const old=h.take('POST');h.close();await h.open(value,draftToday(value.preferences));preferenceControls(h).diet.value='vegan';preferenceControls(h).hour.value=14;old.reply({preferences:{...value.preferences,weekly_hour:12,revision:1}},failure?503:200);await saving;await h.flush();assert.equal(h.input().checked,true);assert.equal(Number(preferenceControls(h).hour.value),14);assert.equal(preferenceControls(h).diet.value,'vegan');assert.equal(h.input().disabled,false);assert.equal(h.requests.length,0);
 });

 // These fixtures activate the real coach/rhythm callbacks omitted by the
 // previous empty-coach/unavailable-rhythm seam. No backend/provider is run.
 function actionSettings(kind='coach_save'){
  const value=draftSettings();
  value.coach={explanation:'Owned aggregate permission fixture',items:[{coach_id:'22',label:'Тренер fixture',macros:kind==='coach_revoke',top_dishes:kind==='coach_revoke',expires_at:null}]};
  value.rhythm={proposal:{status:'proposal',message:'Owned rhythm fixture',weekdays:[1,3],fingerprint:'fixture-rhythm',base_goal_key:'fixture-goal',previews:[{training_extra_kcal:100,days:Array.from({length:7},()=>({kcal:2200}))}]},active:kind==='rhythm_off'?{training_extra_kcal:100}:null};
  return value;
 }
 const actionLabel={coach_save:'Сохранить разрешения',coach_revoke:'Отозвать доступ к питанию',rhythm_apply:'Подтвердить этот вариант на 28 дней',rhythm_off:'Вернуться к одинаковой цели каждый день'};
 function coachControls(h){const all=n=>[n,...n.children.flatMap(all)],b=all(h.document.body).find(n=>n.tagName==='button'&&n.textContent==='Сохранить разрешения'),row=b.parentElement;return {row,macros:row.querySelectorAll('input')[0],dishes:row.querySelectorAll('input')[1],days:row.querySelector('select'),save:b};}
 function expectedAction(kind,h){if(kind==='coach_save'){const c=coachControls(h);c.macros.checked=true;c.dishes.checked=true;c.days.value=7;return {action:'coach',coach_id:'22',macros:true,top_dishes:true,days:7};}if(kind==='coach_revoke')return {action:'coach',coach_id:'22',macros:false,top_dishes:false,days:30};return kind==='rhythm_off'?{action:'rhythm_off'}:{action:'rhythm',fingerprint:'fixture-rhythm',base_goal_key:'fixture-goal',extra:100};}
 function actionAck(body){return body.action==='coach'?{items:[{coach_id:body.coach_id,macros:body.macros,top_dishes:body.top_dishes}],explanation:'Owned acknowledgement'}:body.action==='rhythm_off'?{active:false}:{training_extra_kcal:body.extra,weekdays:[1,3],expires_at:2000000000};}
 async function openAction(h,kind='coach_save'){h.setAuth('1','launch-A');const value=actionSettings(kind);await h.open(value,draftToday(value.preferences));return value;}
 async function completeActionRead(h,click,value){await h.flush();h.take().reply(value);await click;await h.flush();h.take('GET','/today?target=food').reply(draftToday(value.preferences));await h.flush();}

 for(const kind of Object.keys(actionLabel))await test(kind+' acknowledgement preserves unrelated live preference drafts',async()=>{
  const h=harness(),value=await openAction(h,kind),body=expectedAction(kind,h);h.toggle(false);const fields=preferenceControls(h);fields.hour.value=13;fields.diet.value='vegan';fields.day.checked=false;
  const click=h.click(actionLabel[kind]);await h.flush();const post=h.take('POST');assert.deepEqual(JSON.parse(post.options.body),body);post.reply(actionAck(body));await h.flush();
  const next=clone(value);next.preferences.revision=3;await completeActionRead(h,click,next);
  assert.equal(h.input().checked,false);assert.equal(Number(preferenceControls(h).hour.value),13);assert.equal(preferenceControls(h).diet.value,'vegan');assert.equal(preferenceControls(h).day.checked,false);assert.equal(h.note().textContent,unsaved);assert.ok(noticeText(h).includes('несохранённые'));assert.equal(h.requests.length,0);
 });
 await test('coach action preserves the latest edits made during POST and settings GET',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h);preferenceControls(h).hour.value=11;
  const click=h.click(actionLabel.coach_save);await h.flush();const post=h.take('POST');assert.equal(h.input().disabled,false);preferenceControls(h).hour.value=12;post.reply(actionAck(body));await h.flush();const get=h.take();preferenceControls(h).hour.value=14;preferenceControls(h).diet.value='vegetarian';h.toggle(false);get.reply(value);await click;await h.flush();
  assert.equal(Number(preferenceControls(h).hour.value),14);assert.equal(preferenceControls(h).diet.value,'vegetarian');assert.equal(h.input().checked,false);h.take('GET','/today?target=food').reply(draftToday(value.preferences));await h.flush();assert.equal(h.requests.length,0);
 });
 await test('coach action owns only its row fields while Close and preference inputs remain usable',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h),row=coachControls(h);const click=h.click(actionLabel.coach_save);await h.flush();const post=h.take('POST');
  assert.equal(row.macros.disabled,true);assert.equal(row.dishes.disabled,true);assert.equal(row.days.disabled,true);assert.equal(h.input().disabled,false);assert.equal(preferenceControls(h).hour.disabled,false);assert.equal(h.closeButton().disabled,false);
  await h.click(actionLabel.coach_save);assert.equal(h.requests.length,0);post.reply(actionAck(body));await completeActionRead(h,click,value);
 });
 for(const failure of [false,true])await test('old coach POST '+(failure?'failure':'success')+' cannot refresh or notice into a reopened form',async()=>{
  const h=harness({ignoreAbort:true}),value=await openAction(h),body=expectedAction('coach_save',h);const click=h.click(actionLabel.coach_save);await h.flush();const old=h.take('POST');h.close();await h.open(value,draftToday(value.preferences));preferenceControls(h).hour.value=14;h.toggle(false);const before=noticeText(h);old.reply(actionAck(body),failure?503:200);await click;await h.flush();
  assert.equal(h.requests.length,0);assert.equal(Number(preferenceControls(h).hour.value),14);assert.equal(h.input().checked,false);assert.equal(noticeText(h),before);
 });
 for(const failure of [false,true])await test('old rhythm refresh '+(failure?'failure':'success')+' cannot replace a reopened form',async()=>{
  const h=harness({ignoreAbort:true}),value=await openAction(h,'rhythm_apply'),body=expectedAction('rhythm_apply',h);const click=h.click(actionLabel.rhythm_apply);await h.flush();h.take('POST').reply(actionAck(body));await h.flush();const old=h.take();h.close();await h.open(value,draftToday(value.preferences));preferenceControls(h).diet.value='vegan';const before=noticeText(h);old.reply(value,failure?503:200);await click;await h.flush();
  assert.equal(h.requests.length,0);assert.equal(preferenceControls(h).diet.value,'vegan');assert.equal(noticeText(h),before);
 });
 for(const changed of ['proof','owner'])await test('coach acknowledgement ignores changed '+changed+' context before starting a refresh',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h);const click=h.click(actionLabel.coach_save);await h.flush();const old=h.take('POST');h.setAuth(changed==='owner'?'2':'1',changed==='proof'?'launch-B':'launch-A');preferenceControls(h).hour.value=13;const before=noticeText(h);old.reply(actionAck(body));await click;await h.flush();assert.equal(h.requests.length,0);assert.equal(Number(preferenceControls(h).hour.value),13);assert.equal(noticeText(h),before);
 });
 await test('rendered coach action refuses a changed account before any POST',async()=>{
  const h=harness();await openAction(h);expectedAction('coach_save',h);h.setAuth('2','launch-B');await h.click(actionLabel.coach_save);await h.flush();assert.equal(h.requests.length,0);assert.ok(noticeText(h).includes('Сессия изменилась'));
 });
 await test('same owner and proof survive a normal bridge session object renewal',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h);const click=h.click(actionLabel.coach_save);await h.flush();const post=h.take('POST');h.setAuth('1','launch-A');post.reply(actionAck(body));await completeActionRead(h,click,value);assert.ok(noticeText(h).includes('Разрешения обновлены'));
 });
 await test('fallback launch context replacement ignores the old coach completion',async()=>{
  const h=harness(),value=actionSettings();h.window.Progressor.launchData='fallback-A';await h.open(value,draftToday(value.preferences));const body=expectedAction('coach_save',h);const click=h.click(actionLabel.coach_save);await h.flush();const post=h.take('POST');h.window.Progressor.launchData='fallback-B';post.reply(actionAck(body));await click;await h.flush();assert.equal(h.requests.length,0);assert.ok(!noticeText(h).includes('Разрешения обновлены'));
 });
 await test('coach settings GET cannot render after the proof changes',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h);const click=h.click(actionLabel.coach_save);await h.flush();h.take('POST').reply(actionAck(body));await h.flush();const get=h.take();h.toggle(false);h.setAuth('1','launch-B');const before=noticeText(h);get.reply(value);await click;await h.flush();assert.equal(h.input().checked,false);assert.equal(noticeText(h),before);assert.equal(h.requests.length,0);
 });
 await test('current coach409 preserves drafts and offers explicit read-only discard refresh',async()=>{
  const h=harness(),value=await openAction(h);expectedAction('coach_save',h);preferenceControls(h).hour.value=13;const click=h.click(actionLabel.coach_save);await h.flush();h.take('POST').reply({},409);await click;await h.flush();assert.equal(Number(preferenceControls(h).hour.value),13);assert.equal(coachControls(h).macros.disabled,false);assert.ok(noticeText(h).includes('сбросит несохранённый выбор'));
  const refresh=h.click('Обновить данные');await h.flush();assert.equal(h.requests.length,1);await completeActionRead(h,refresh,value);assert.equal(Number(preferenceControls(h).hour.value),10);assert.equal(h.requests.length,0);
 });
 await test('coach POST deadline is bounded even when transport ignores abort and never retries the write',async()=>{
  const h=harness({ignoreAbort:true}),value=await openAction(h),body=expectedAction('coach_save',h);preferenceControls(h).hour.value=13;const click=h.click(actionLabel.coach_save);await h.flush();const old=h.take('POST');h.fireTimeout(8000);await click;await h.flush();assert.equal(coachControls(h).macros.disabled,false);assert.equal(h.closeButton().disabled,false);assert.equal(Number(preferenceControls(h).hour.value),13);assert.equal(h.requests.length,0);assert.ok(noticeText(h).includes('Не удалось получить подтверждение'));assert.ok(!noticeText(h).includes('Разрешения обновлены'));
  const retry=h.click('Обновить настройки');await h.flush();assert.equal(h.requests.length,1);await completeActionRead(h,retry,value);old.reply(actionAck(body));await h.flush();assert.equal(h.requests.length,0);assert.equal(Number(preferenceControls(h).hour.value),13);assert.ok(!noticeText(h).includes('Разрешения обновлены'));
 });
 for(const timedOut of [false,true])await test('acknowledged coach action with '+(timedOut?'timed-out':'failed')+' refresh offers only a draft-preserving read retry',async()=>{
  const h=harness({ignoreAbort:timedOut}),value=await openAction(h),body=expectedAction('coach_save',h);preferenceControls(h).hour.value=12;const click=h.click(actionLabel.coach_save);await h.flush();h.take('POST').reply(actionAck(body));await h.flush();const get=h.take();if(timedOut)h.fireTimeout(8000);else get.reply({},503);await click;await h.flush();assert.equal(h.requests.length,0);assert.equal(Number(preferenceControls(h).hour.value),12);assert.ok(noticeText(h).includes('Разрешения обновлены'));assert.ok(noticeText(h).includes('настройки не обновились'));
  const retry=h.click('Повторить обновление настроек');await h.flush();const read=h.take();assert.equal(read.options.method,'GET');preferenceControls(h).hour.value=14;read.reply(value);await retry;await h.flush();h.take('GET','/today?target=food').reply(draftToday(value.preferences));await h.flush();if(timedOut)get.reply(value);await h.flush();assert.equal(Number(preferenceControls(h).hour.value),14);assert.equal(h.requests.length,0);assert.ok(noticeText(h).includes('несохранённые'));
 });
 await test('old coach finally cannot unlock a newer preference write after close and reopen',async()=>{
  const h=harness({ignoreAbort:true}),value=await openAction(h),body=expectedAction('coach_save',h);const oldClick=h.click(actionLabel.coach_save);await h.flush();const old=h.take('POST');h.close();await h.open(value,draftToday(value.preferences));h.toggle(false);const saving=h.click('Сохранить связи');await h.flush();const post=h.take('POST');old.reply(actionAck(body));await oldClick;await h.flush();assert.equal(h.input().disabled,true);await h.click(actionLabel.coach_save);await h.flush();assert.equal(h.requests.length,0);const next={...clone(value.preferences),sources:{...value.preferences.sources,supply:false},revision:1};post.reply({preferences:next});await saving;await h.flush();h.take('GET','/today?target=food').reply(draftToday(next));await h.flush();assert.equal(h.input().disabled,false);
 });
 await test('the next preference save uses the refreshed server revision without leaking coach fields',async()=>{
  const h=harness(),value=await openAction(h),body=expectedAction('coach_save',h);preferenceControls(h).hour.value=13;const click=h.click(actionLabel.coach_save);await h.flush();h.take('POST').reply(actionAck(body));const next=clone(value);next.preferences.revision=8;await completeActionRead(h,click,next);const saving=h.click('Сохранить время сводки');await h.flush();const post=h.take('POST'),write=JSON.parse(post.options.body);assert.equal(write.revision,8);assert.deepEqual(Object.keys(write.patch).sort(),['weekly_plan','weekly_day','weekly_hour'].sort());assert.equal(write.patch.weekly_hour,13);post.reply({preferences:{...next.preferences,...write.patch,revision:9}});await saving;await h.flush();h.take('GET','/today?target=food').reply(draftToday(value.preferences));await h.flush();assert.equal(h.requests.length,0);
 });

 // Keyboard regressions execute the actual dialog listener. Synthetic appended
 // controls give explicit known visible/closed/disabled boundaries, no layout claim.
 await test('closed nested details cannot supply hidden keyboard boundaries',async()=>{
  const h=harness();await h.open();const dialog=h.document.body.querySelector('#progressor-connections');
  const add=(tag,parent,label)=>{const n=h.document.createElement(tag);if(label)n.textContent=label;parent.append(n);return n;};
  const outer=add('details',dialog),summary=add('summary',outer,'Visible closed summary'),summaryChild=add('span',summary,'Visible summary child');summaryChild.setAttribute('tabindex','0');
  const hiddenButton=add('button',outer,'Hidden direct action'),nested=add('details',outer);nested.open=true;add('summary',nested,'Hidden nested summary');const hiddenNestedButton=add('button',nested,'Hidden nested action');
  assert.equal(hiddenButton.getClientRects().length,1);assert.equal(hiddenNestedButton.getClientRects().length,1);assert.equal(outer.open,false);
  h.closeButton().focus();let prevented=false;await dialog.dispatchEvent({type:'keydown',key:'Tab',shiftKey:true,preventDefault(){prevented=true;}});
  assert.equal(prevented,true,'reverse Tab is owned at the visible first boundary');assert.equal(h.document.activeElement,summaryChild,'only the closed details own summary and its children remain keyboard-visible');assert.equal(h.requests.length,0);
 });
 await test('Tab cycles both visible boundaries while open actions remain eligible',async()=>{
  const h=harness();await h.open();const dialog=h.document.body.querySelector('#progressor-connections');
  const add=(tag,parent,label)=>{const n=h.document.createElement(tag);if(label)n.textContent=label;parent.append(n);return n;};
  const outer=add('details',dialog);outer.open=true;add('summary',outer,'Visible open summary');const nested=add('details',outer);add('summary',nested,'Visible nested closed summary');add('button',nested,'Hidden nested action');
  const last=add('button',outer,'Visible final action'),disabled=add('button',outer,'Disabled later action');disabled.disabled=true;
  const hidden=add('div',dialog);hidden.setAttribute('hidden','');add('button',hidden,'Hidden later action');
  let prevented=false;last.focus();await dialog.dispatchEvent({type:'keydown',key:'Tab',shiftKey:false,preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.document.activeElement,h.closeButton(),'forward Tab wraps from the actual visible final action');
  prevented=false;await dialog.dispatchEvent({type:'keydown',key:'Tab',shiftKey:true,preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.document.activeElement,last,'reverse Tab returns to the open section action, not a closed/hidden/disabled descendant');assert.equal(h.requests.length,0);
 });

 console.log(JSON.stringify({passed:true,cases:passed.length,names:passed,network_or_provider_calls:0,scope:'Whole canonical asset, deterministic DOM/event/request seam only'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
