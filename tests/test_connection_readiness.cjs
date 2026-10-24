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
function harness(){
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
  matches(selector){
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
   options.signal?.addEventListener('abort',()=>reject(Error('Synthetic request aborted')),{once:true});
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
 return {document,window,launcher,requests,note,input,toggle,flush,take,open,fireTimeout,notes:()=>document.body.querySelectorAll('[data-source-readiness]'),closeButton:()=>findButton('×'),close:()=>document.body.querySelector('#progressor-connections').close(),click:text=>{const button=findButton(text);assert.ok(button,'button '+text);return button.dispatchEvent({type:'click'});}};
}
async function main(){const passed=[];async function test(name,fn){await fn();passed.push(name);}
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
 console.log(JSON.stringify({passed:true,cases:passed.length,names:passed,network_or_provider_calls:0,scope:'Whole canonical asset, deterministic DOM/event/request seam only'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
