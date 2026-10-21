const nativeAssert=require('node:assert/strict');
let actionAssertions=0;
const assert=new Proxy(nativeAssert,{get:(target,key)=>typeof target[key]==='function'?(...args)=>{actionAssertions++;return target[key](...args);}:target[key]});
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../..');
const files={gym:'gym_diary_bot/webapp/index.html',food:'food_bot/static/webapp/index.html',supply:'supply_bot/webapp/index.html'};
function hook(source,extra={}){
 const html=fs.readFileSync(path.join(root,files[source]),'utf8');
 const code=html.match(/window\.ProgressorDomain=(\{version:1,[\s\S]*?\n\s*\});/)[0];
 const calls=[],nodes={};
 const node=id=>nodes[id] ||= {id,style:{},classList:{contains:()=>id==='screen-today'},setAttribute(){},focus(){calls.push(['focus',id]);},scrollIntoView(){calls.push(['scroll',id]);}};
 const state={uiReady:true,userId:123,initData:'fixture-launch',nativeSubject:'123',nativeIdentityProof:'fixture-launch',acting:{userId:null},onboarding:{active:false},settings:{},currentRoute:'today',me:{webapp_access:true},today:{},activeTab:'profile',mySupplements:{open:false},catalog:{}};
 let revision=0;
 const env={window:{Progressor:{interactionRevision:()=>revision,_launchBridge:{getState:()=>({session:{user:{id:123}},launchData:'fixture-launch'})}}},document:{getElementById:node,querySelector:()=>node('own-list-close')},matchMedia:()=>({matches:true}),state,loadViewerRole:async()=>{},mealDrafts:{},mealEditorOpen:false,activeMode:'yesterday',lastDayData:{day:'2026-10-19'},lastLoadedDateIso:'2026-10-19',dayRequest:0,screenToday:node('screen-today'),isEditing:()=>false,isoToday:()=> '2026-10-19',
  showScreen:name=>calls.push(['screen',name]),setActiveMode:name=>{env.activeMode=name;calls.push(['mode',name]);},loadDay:async name=>{env.dayRequest++;calls.push(['load',name]);},
  navigateTo:route=>{calls.push(['route',route,state.settings.pendingView]);state.currentRoute=route;},activateTab:tab=>{calls.push(['tab',tab]);state.activeTab=tab;},openMySupplements:async()=>{calls.push(['own-list']);state.mySupplements.open=true;},...extra};
 if(source==='gym'){
  vm.runInNewContext(html.match(/function hasVerifiedOwnGymSubject\(\) \{[\s\S]*?\n    \}/)[0],env,{filename:files[source]});
  state.tour={active:false,automaticDeferred:false};env.stopTour=()=>{state.tour.active=false};
  vm.runInNewContext(html.match(/function deferAutomaticTourForOwnedTask\(\) \{[\s\S]*?\n    \}/)[0],env,{filename:files[source]});
 }
 vm.runInNewContext(code,env,{filename:files[source]});
 return {hook:env.window.ProgressorDomain,state,calls,env,node,setRevision:value=>{revision=value;}};
}
async function main(){
 let syntax=0;
 for(const file of Object.values(files)){
  const html=fs.readFileSync(path.join(root,file),'utf8');
  for(const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi))if(!/\bsrc=/.test(match[1])&&match[2].trim()){new vm.Script(match[2],{filename:file});syntax++;}
 }
 new vm.Script(fs.readFileSync(path.join(root,'progressor_core/shared/navigation.v1.js'),'utf8'));
 const gym=hook('gym');assert.equal(await gym.hook.perform({kind:'gym_plan'}),true);assert.deepEqual(gym.calls,[['route','settings','plan']]);
 gym.state.acting.userId=55;assert.equal(await gym.hook.perform({kind:'gym_plan'}),false);assert.equal(gym.hook.captureView(),null);
 gym.state.acting.userId=null;gym.state.onboarding.active=true;assert.equal(await gym.hook.perform({kind:'gym_plan'}),false);
 // Transferred SDK user can be absent; the native server identity, matched to
 // the original launch's verified subject, authorizes the own-account view.
 const receiving=hook('gym');receiving.state.userId=null;assert.equal(receiving.hook.eligible(),true);assert.equal(await receiving.hook.perform({kind:'gym_plan'}),true);
 const wrongSubject=hook('gym');wrongSubject.state.nativeSubject='456';assert.equal(wrongSubject.hook.eligible(),false);assert.equal(await wrongSubject.hook.perform({kind:'gym_plan'}),false);assert.deepEqual(wrongSubject.calls,[]);
 const wrongProof=hook('gym');wrongProof.state.nativeIdentityProof='other-launch';assert.equal(await wrongProof.hook.perform({kind:'gym_plan'}),false);assert.equal(await wrongProof.hook.restoreView('today'),false);assert.deepEqual(wrongProof.calls,[]);
 const waiting=hook('gym');waiting.state.nativeSubject=null;waiting.env.loadViewerRole=async()=>{waiting.state.nativeSubject='123';waiting.state.acting.userId=55;};assert.equal(await waiting.hook.perform({kind:'gym_plan'}),false);assert.deepEqual(waiting.calls,[]);
 const inputRace=hook('gym');inputRace.state.nativeSubject=null;inputRace.env.loadViewerRole=async()=>{inputRace.state.nativeSubject='123';inputRace.setRevision(1);};assert.equal(await inputRace.hook.perform({kind:'gym_plan'}),false);assert.deepEqual(inputRace.calls,[]);
 for(const [kind,id] of [['food_goal','food-context-settings'],['food_log','card-today-meals'],['open_food','card-week']]){
  const food=hook('food');assert.equal(await food.hook.perform({kind}),true);assert.deepEqual(food.calls.slice(0,3),[['screen','today'],['mode','today'],['load','today']]);assert.ok(food.calls.some(c=>c[0]==='focus'&&c[1]===id));assert.equal(!!food.node('food-context-settings').open,kind==='food_goal');
 }
 const foodDraft=hook('food',{mealDrafts:{one:{value:'78'}}});assert.equal(await foodDraft.hook.perform({kind:'food_goal'}),false);assert.equal(foodDraft.calls.length,0);
 const foodRace=hook('food');foodRace.env.loadDay=async()=>{foodRace.env.dayRequest++;foodRace.setRevision(1);};assert.equal(await foodRace.hook.perform({kind:'food_goal'}),false);assert.ok(!foodRace.calls.some(c=>c[0]==='focus'));
 const supply=hook('supply');assert.equal(await supply.hook.perform({kind:'supply_plan'}),true);assert.deepEqual(supply.calls.slice(0,2),[['tab','today'],['own-list']]);
 supply.state.me.webapp_access=false;assert.equal(await supply.hook.perform({kind:'supply_plan'}),false);
 console.log(JSON.stringify({passed:true,syntax_scripts:syntax+1,native_action_assertions:actionAssertions,network_or_ai_calls:0}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
