/* Isolated shared-shell fixture: browser DOM, no external network, providers or real proof. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const origin='https://progressor.test';
const routes={gym:'/gymapp_prod/',food:'/webapp/',supply:'/supply/'};
const shell=fs.readFileSync(path.join(__dirname,'../shared/navigation.v1.js'),'utf8');
const auth={launchData:'fixture-launch-only',session:{user:{id:123},assertions:{core:'fixture-only'},expires_at:Date.now()/1000+3600,enabled_domains:['gym','food','supply']}};
const proof_digest=crypto.createHash('sha256').update(auth.launchData).digest('hex');
function record(extra={}){const now=Date.now();return {version:1,owner:'123',proof_digest,from:'gym',to:'food',action:{kind:'food_goal'},view:'today',created_at:now,expires_at:now+600000,phase:'outbound',...extra};}
function hint(key='old',extra={}){return {title:key,message:'Проверить собственный план',details:'Fixture',basis:[{source:'food'}],delivery_key:key,reviewable:true,action:{kind:'food_goal',label:'Открыть цель Food'},...extra};}
const contextFor=h=>({memberships:['gym','food','supply'],enabled_domains:['gym','food','supply'],access:{bundle_active:true},inline_hint:h,offer_preview:null,recommendations:[]});
function html(source,initial={}){return `<!doctype html><html><head><meta charset="utf-8"><title>Fixture</title><script>
window.auth=${JSON.stringify(auth)};window.nativeReady=${initial.nativeReady!==false};window.coreAvailable=${initial.coreAvailable!==false};window.nativeActions=[];window.view='today';window.intervals=[];
window.setInterval=fn=>{window.intervals.push(fn);return window.intervals.length;};
window.Progressor={_launchBridge:{source:'${source}',getState:()=>window.auth,sessionValid:()=>true,canNavigate:()=>true,bootstrap:async()=>{if(window.bootstrapGate)await window.bootstrapGate;return window.coreAvailable?window.auth.session:null;}}};
window.ProgressorDomain={isReady:()=>window.nativeReady,eligible:()=>true,hintHost:()=>document.getElementById('progressor-inline-host'),captureView:()=>window.view,restoreView:async view=>{window.nativeActions.push({restore:view});window.view=view;return true;},perform:async action=>{window.nativeActions.push(action);window.view=action.kind;document.getElementById('destination').textContent=action.kind;return true;},subscriptionPlans:async()=>[],purchaseSubscription:async()=>{}};
</script><script src="/progressor/assets/navigation.v1.js" data-progressor-source="${source}" defer></script></head><body><main><h1 id="destination">Today</h1><div id="progressor-inline-host"></div><label>Draft<input id="draft"></label></main></body></html>`;}
async function create(browser,source='gym',options={}){
 const browserContext=await browser.newContext({viewport:{width:320,height:844},reducedMotion:'reduce'});
 const posts=[],errors=[];let context=contextFor(options.hint===undefined?hint():options.hint),reviewCount=0;
 if(options.record)await browserContext.addInitScript(({record})=>{if(!sessionStorage.getItem('fixture-seeded')){sessionStorage.setItem('progressor.transfer.v1',JSON.stringify(record));sessionStorage.setItem('fixture-seeded','1');}},{record:options.record});
 await browserContext.route('**/*',async route=>{
  const u=new URL(route.request().url());assert.equal(u.origin,origin,'External network requested');
  if(route.request().method()==='POST')posts.push({path:u.pathname,body:JSON.parse(route.request().postData()||'{}')});
  if(u.pathname==='/progressor/assets/navigation.v1.js')return route.fulfill({contentType:'application/javascript',body:shell});
  if(u.pathname==='/progressor/assets/connections.v1.js')return route.fulfill({contentType:'application/javascript',body:''});
  if(u.pathname==='/progressor/api/v1/me/context')return route.fulfill({json:context});
  if(u.pathname==='/progressor/api/v1/me/subscriptions')return route.fulfill({json:{products:[],bundle:{active:false},unknown_products:[]}});
  if(u.pathname==='/progressor/api/v1/me/hints/reviewed'){
   reviewCount++;if(options.reviewGate)await options.reviewGate;
   const body=JSON.parse(route.request().postData());return route.fulfill({status:options.reviewStatus||200,json:options.badAck?{reviewed:true,target:'food',delivery_key:'other',reviewed_at:1}:{reviewed:true,...body,reviewed_at:Date.now()/1000}});
  }
  if(u.pathname.endsWith('/hints/seen')||u.pathname.endsWith('/hints/dismiss'))return route.fulfill({json:{ok:true}});
  const target=Object.keys(routes).find(k=>routes[k]===u.pathname);if(target)return route.fulfill({contentType:'text/html',body:html(target,options)});
  return route.fulfill({status:404,body:'fixture path unavailable'});
 });
 const page=await browserContext.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+routes[source]+(options.query||''));await page.locator('#progressor-shell').waitFor();
 return {page,context:browserContext,posts,errors,setHint:h=>{context=contextFor(h);},setOffer:offer=>{context=contextFor(null);context.offer_preview=offer;},get reviewCount(){return reviewCount;}};
}
async function refresh(t){await t.page.waitForFunction(()=>window.intervals.length);await t.page.evaluate(()=>window.intervals[0]());}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});const results=[];
 async function run(name,fn){const t=await fn();assert.deepEqual(t.errors,[],name+' JS errors');await t.context.close();results.push(name);}
 try{
  await run('cross-purpose-ready-return-reload',async()=>{
   const t=await create(browser);assert.equal(await t.page.locator('#progressor-transfer').isHidden(),true);await t.page.locator('[data-primary]').click();await t.page.waitForURL(origin+routes.food+'*');await t.page.waitForFunction(()=>window.nativeActions.some(a=>a.kind==='food_goal'));
   assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[{kind:'food_goal'}]);assert.equal(await t.page.locator('[data-progressor-return]').textContent(),'Вернуться в Gym Diary');
   assert.equal(new URL(t.page.url()).search,'');const stored=await t.page.evaluate(()=>sessionStorage.getItem('progressor.transfer.v1'));assert.ok(!stored.includes(auth.launchData));assert.ok(!stored.includes('assertions'));
   await t.page.reload();await t.page.locator('[data-progressor-return]').waitFor();assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);
   await t.page.locator('[data-progressor-return]').click();await t.page.waitForURL(origin+routes.gym+'*');await t.page.waitForFunction(()=>window.nativeActions.some(a=>a.restore==='today'));assert.equal(await t.page.evaluate(()=>sessionStorage.getItem('progressor.transfer.v1')),null);
   assert.equal(await t.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);return t;
  });
  await run('pending-native-interaction-cancels-auto-open',async()=>{
   const t=await create(browser,'food',{nativeReady:false,record:record(),query:'?progressor_action=food_goal'});await t.page.locator('#draft').fill('kept draft');await t.page.evaluate(()=>{window.nativeReady=true;});
   await t.page.getByRole('button',{name:'Открыть выбранный раздел'}).waitFor();assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);assert.equal(await t.page.locator('#draft').inputValue(),'kept draft');
   await t.page.getByRole('button',{name:'Открыть выбранный раздел'}).click();await t.page.waitForFunction(()=>window.nativeActions.length===1);return t;
  });
  await run('incoming-core-outage-keeps-native-view',async()=>{const t=await create(browser,'food',{coreAvailable:false,record:record(),query:'?progressor_action=food_goal'});await t.page.getByText('Переход уже недоступен.',{exact:false}).waitFor();assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);assert.equal(await t.page.locator('#destination').textContent(),'Today');return t;});
  await run('proof-changes-while-native-is-loading',async()=>{const t=await create(browser,'food',{nativeReady:false,record:record(),query:'?progressor_action=food_goal'});await t.page.waitForTimeout(100);await t.page.evaluate(()=>{window.auth.launchData='replacement-launch';window.nativeReady=true;});await t.page.waitForTimeout(180);assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);assert.equal(await t.page.evaluate(()=>sessionStorage.getItem('progressor.transfer.v1')),null);return t;});
  for(const [name,stored,query] of [
   ['expiry',record({created_at:Date.now()-700000,expires_at:Date.now()-100000}),'food_goal'],
   ['account',record({owner:'456'}),'food_goal'],['proof',record({proof_digest:'0'.repeat(64)}),'food_goal'],['unknown',record(),'arbitrary_action']]){
   await run('safe-'+name,async()=>{const t=await create(browser,'food',{record:stored,query:'?progressor_action='+query});await t.page.getByText('Переход уже недоступен.',{exact:false}).waitFor();assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);assert.equal(await t.page.evaluate(()=>sessionStorage.getItem('progressor.transfer.v1')),null);return t;});
  }
  await run('storage-unavailable-no-navigation',async()=>{const t=await create(browser);await t.page.evaluate(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key==='progressor.transfer.v1')throw Error('fixture');return original.call(this,key,value);};});await t.page.locator('[data-primary]').click();await t.page.getByText('Не удалось открыть раздел.',{exact:false}).waitFor();assert.equal(new URL(t.page.url()).pathname,routes.gym);return t;});
  await run('core-outage-no-navigation',async()=>{const t=await create(browser);await t.page.evaluate(()=>{window.coreAvailable=false;});await t.page.locator('[data-primary]').click();await t.page.getByText('Не удалось открыть раздел.',{exact:false}).waitFor();assert.equal(new URL(t.page.url()).pathname,routes.gym);return t;});
  await run('explicit-reviewed-single-submit-no-ad',async()=>{
   let release;const reviewGate=new Promise(resolve=>{release=resolve;});const t=await create(browser,'gym',{reviewGate});await t.page.locator('[data-review-hint]').waitFor();assert.equal(t.reviewCount,0);
   await t.page.locator('[data-review-hint]').evaluate(button=>{button.click();button.click();});await t.page.waitForFunction(()=>document.querySelector('[data-review-hint]').disabled);release();await t.page.locator('[data-review-confirmed]').waitFor();
   assert.equal(t.reviewCount,1);assert.deepEqual(t.posts.filter(p=>p.path.endsWith('/reviewed')),[{path:'/progressor/api/v1/me/hints/reviewed',body:{target:'gym',delivery_key:'old'}}]);assert.deepEqual(await t.page.evaluate(()=>window.nativeActions),[]);
   t.setOffer(hint('advertisement',{reviewable:false,action:{kind:'bundle',label:'Подписка'}}));await refresh(t);await t.page.waitForTimeout(80);assert.equal(await t.page.locator('.progressor-hint').count(),0);assert.equal(await t.page.locator('[data-review-confirmed]').count(),1);return t;
  });
  await run('late-review-does-not-hide-new-hint',async()=>{
   let release;const reviewGate=new Promise(resolve=>{release=resolve;});const t=await create(browser,'gym',{reviewGate});await t.page.locator('[data-review-hint]').click();t.setHint(hint('new'));await refresh(t);await t.page.locator('.progressor-hint strong').filter({hasText:'new'}).waitFor();release();await t.page.waitForTimeout(100);assert.equal(await t.page.locator('.progressor-hint strong').textContent(),'new');assert.equal(await t.page.locator('[data-review-confirmed]').count(),0);return t;
  });
  await run('late-review-after-account-switch',async()=>{
   let release;const reviewGate=new Promise(resolve=>{release=resolve;});const t=await create(browser,'gym',{reviewGate});await t.page.locator('[data-review-hint]').click();await t.page.evaluate(()=>{window.auth.session.user.id=456;window.auth.launchData='new-launch';});release();await t.page.waitForTimeout(100);assert.equal(await t.page.locator('[data-review-confirmed]').count(),0);return t;
  });
  await run('review-ack-keeps-new-draft-focus',async()=>{let release;const reviewGate=new Promise(resolve=>{release=resolve;});const t=await create(browser,'gym',{reviewGate});await t.page.locator('[data-review-hint]').click();await t.page.locator('#draft').fill('local draft');release();await t.page.locator('[data-review-confirmed]').waitFor();assert.equal(await t.page.evaluate(()=>document.activeElement.id),'draft');assert.equal(await t.page.locator('#draft').inputValue(),'local draft');return t;});
  await run('review-error-stays-retryable',async()=>{const t=await create(browser,'gym',{reviewStatus:409});await t.page.locator('[data-review-hint]').click();await t.page.getByText('Не удалось подтвердить проверку.',{exact:false}).waitFor();assert.equal(await t.page.locator('[data-review-hint]').isEnabled(),true);assert.equal(await t.page.locator('.progressor-hint').count(),1);return t;});
  await run('review-invalid-ack-stays-visible',async()=>{const t=await create(browser,'gym',{badAck:true});await t.page.locator('[data-review-hint]').click();await t.page.getByText('Не удалось подтвердить проверку.',{exact:false}).waitFor();assert.equal(await t.page.locator('.progressor-hint').count(),1);return t;});
  await run('nonreviewable-hint-has-no-review-button',async()=>{const t=await create(browser,'gym',{hint:hint('normal',{reviewable:false})});await t.page.locator('.progressor-hint').waitFor();assert.equal(await t.page.locator('[data-review-hint]').count(),0);return t;});
  console.log(JSON.stringify({passed:true,checks:results,physical_telegram:false,real_network:0,ai_requests:0}));
 }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
