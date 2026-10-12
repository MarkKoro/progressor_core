import json,os,sqlite3,tempfile,time,unittest,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from test_integration import fixture,USER,OTHER
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core import connections as links
from progressor_core.connection_changes import hints,recent
from progressor_core.notifications import candidate
from shared import product_links as owner,ai_cache

class SelectedPrivacy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.uid=str(USER);self.coach=str(OTHER);self.now=datetime.now(timezone.utc)
        self.stamp=self.now.isoformat()
        with sqlite3.connect(self.paths['gym']) as db:
            db.execute('ALTER TABLE user_measurements ADD COLUMN extra TEXT')
            db.execute("INSERT INTO user_measurements(user_id,metric,value,created_at) VALUES(7,'body_weight',81,?)",(self.stamp,))
        with sqlite3.connect(self.paths['food']) as db:
            db.executescript("CREATE TABLE progressor_food_profile(user_id INTEGER PRIMARY KEY,profile_json TEXT,updated_at TEXT,sharing_enabled INTEGER);ALTER TABLE meals ADD COLUMN raw_json TEXT;")
            db.execute('INSERT INTO progressor_food_profile VALUES(?,?,?,1)',(USER,json.dumps({'weight_kg':80,'height_cm':180}),self.stamp))
            db.execute('UPDATE meals SET raw_json=?',(json.dumps({'items':[{'name':'Суп'}]}),))
        with sqlite3.connect(self.paths['supply']) as db:
            db.execute('CREATE TABLE user_health_profile(user_id INTEGER PRIMARY KEY,weight_kg REAL,height_cm REAL,created_at_utc TEXT,updated_at_utc TEXT,sex_at_birth TEXT,birth_year INTEGER,diet_type TEXT,training_sessions_per_week INTEGER,training_minutes_per_week INTEGER)')
            db.execute('INSERT INTO user_health_profile(user_id,weight_kg,height_cm,created_at_utc,updated_at_utc) VALUES(55,79,180,?,?)',(self.stamp,self.stamp))
        self.store=Store(self.root/'core.db')
        for s,p in self.paths.items():owner.ensure_schema(p);self.store.reconcile(s,snapshot(s,p))
    def tearDown(self):self.tmp.cleanup()
    def pref(self,**values):return links.save_preferences(self.store,self.uid,values,links.preferences(self.store,self.uid)['revision'])
    def event(self,source,ident,kind,payload):
        with self.store.connection() as db:r=db.execute('SELECT revision FROM entities WHERE source=? AND entity_id=?',(source,ident)).fetchone()
        e={'event_id':str(uuid.uuid4()),'event_type':kind,'schema_version':1,'source':source,'user_id':self.uid,'occurred_at':self.stamp,'correlation_id':'offline-selected',
           'payload':{'entity_id':ident,'revision':r[0]+1 if r else 1,**payload}}
        self.store.accept(e);return e
    def link(self,status='accepted',role=True):
        return self.event('gym','profile:coach:7:8','profile.updated',{'profile_kind':'coach_link','coach_id':self.coach,'link_id':'11','status':status,'coach_enabled':role})
    def test_weight_choice_applies_all_owners_preserves_history_fields_and_goal(self):
        c=links.weight_choices(self.store,self.uid);self.assertTrue(c['conflict'])
        selected=next(i for i in c['items'] if i['source']=='food');op=str(uuid.uuid4())
        links.reconcile_weight(self.store,self.uid,selected['event_id'],c['fingerprint'],op)
        for s,p in self.paths.items():
            sync=links.owner_sync(self.store,s,[self.uid],[]);self.assertEqual(len(sync['commands']),1)
            ack=owner.apply_weight(p,s,sync['commands'][0]);self.assertEqual(ack['status'],'applied')
            self.assertEqual(owner.apply_weight(p,s,sync['commands'][0]),ack)
            links.owner_sync(self.store,s,[],[ack])
        self.assertTrue(links.weight_operation(self.store,self.uid,op)['complete'])
        with sqlite3.connect(self.paths['gym']) as db:self.assertEqual([r[0] for r in db.execute('SELECT value FROM user_measurements ORDER BY id')],[81,80])
        with sqlite3.connect(self.paths['food']) as db:
            p=json.loads(db.execute('SELECT profile_json FROM progressor_food_profile').fetchone()[0]);self.assertEqual(p['height_cm'],180)
            self.assertEqual(db.execute('SELECT kcal FROM goals').fetchone()[0],2200)
        with sqlite3.connect(self.paths['supply']) as db:self.assertEqual(db.execute('SELECT weight_kg,height_cm FROM user_health_profile').fetchone(),(80,180))
    def command(self,source='supply'):
        c=links.weight_choices(self.store,self.uid);s=next(i for i in c['items'] if i['source']=='food')
        links.reconcile_weight(self.store,self.uid,s['event_id'],c['fingerprint'],str(uuid.uuid4()))
        return links.owner_sync(self.store,source,[self.uid],[])['commands'][0]
    def test_newer_owner_profile_is_not_overwritten_by_delayed_weight_command(self):
        c=self.command()
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE user_health_profile SET weight_kg=78,updated_at_utc=?',((self.now+timedelta(seconds=1)).isoformat(),))
        self.assertEqual(owner.apply_weight(self.paths['supply'],'supply',c)['status'],'conflict')
        with sqlite3.connect(self.paths['supply']) as db:self.assertEqual(db.execute('SELECT weight_kg FROM user_health_profile').fetchone()[0],78)
    def test_missing_consent_expiry_wrong_identity_and_ack_rejected(self):
        c=self.command()
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE users SET consent_given=0')
        self.assertEqual(owner.apply_weight(self.paths['supply'],'supply',c)['status'],'consent_required')
        c=self.command('gym');c['expires_at']=time.time()-1
        self.assertEqual(owner.apply_weight(self.paths['gym'],'gym',c)['status'],'expired')
        with self.assertRaises(ValueError):links.owner_sync(self.store,'gym',[],[{'id':c['id'],'user_id':self.coach,'status':'applied'}])
        self.assertFalse(links.weight_operation(self.store,self.coach,c['id'])['items'])
    def test_stale_conflicting_selection_and_op_reuse_rejected(self):
        c=links.weight_choices(self.store,self.uid);s=c['items'][0]
        with self.assertRaises(ValueError):links.reconcile_weight(self.store,self.uid,s['event_id'],'stale',str(uuid.uuid4()))
        op=str(uuid.uuid4());links.reconcile_weight(self.store,self.uid,s['event_id'],c['fingerprint'],op)
        with self.assertRaises(ValueError):links.reconcile_weight(self.store,self.uid,c['items'][1]['event_id'],c['fingerprint'],op)
    def test_coach_requires_explicit_separate_permission_and_aggregate_only(self):
        self.link()
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid,'2026-10-06')
        with self.assertRaises(ValueError):links.save_coach_permission(self.store,self.uid,self.coach,False,True,30)
        links.save_coach_permission(self.store,self.uid,self.coach,True,False,30)
        a=links.coach_nutrition(self.store,self.coach,self.uid,'2026-10-06')
        self.assertEqual(a['totals']['kcal'],1500);self.assertNotIn('top_dishes',a)
        self.assertFalse({'meals','items','nutrients','supply','profile'} & set(a))
        links.save_coach_permission(self.store,self.uid,self.coach,True,True,7)
        a=links.coach_nutrition(self.store,self.coach,self.uid,'2026-10-06');self.assertEqual(a['top_dishes'],[{'name':'Суп','logged_count':3}])
        links.save_coach_permission(self.store,self.uid,self.coach,False,False,7)
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
    def test_link_deactivation_cannot_resurrect_old_permission(self):
        self.link();links.save_coach_permission(self.store,self.uid,self.coach,True,True,90)
        self.link('removed');self.link()
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
    def test_coach_rejects_stale_food_rest_optout_role_and_expiry(self):
        self.link();links.save_coach_permission(self.store,self.uid,self.coach,True,False,7)
        for patch in ({'paused':True},{'paused':False,'sources':{'food':False,'gym':True,'supply':True}}):
            self.pref(**patch)
            with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
        self.pref(sources={'food':True,'gym':True,'supply':True});self.store.failed('food','offline')
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
        self.store.reconcile('food',snapshot('food',self.paths['food']))
        with self.store.connection() as db:db.execute('UPDATE coach_nutrition_permissions SET expires_at=0')
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
        self.link(role=False)
        with self.assertRaises(ValueError):links.save_coach_permission(self.store,self.uid,self.coach,True,False,30)
    def test_coach_losing_paid_access_denies_existing_grant(self):
        self.link();links.save_coach_permission(self.store,self.uid,self.coach,True,True,7)
        with sqlite3.connect(self.paths['gym']) as db:db.execute("UPDATE subscriptions SET expires_at='2000-01-01T00:00:00Z' WHERE user_id=8")
        self.store.reconcile('gym',snapshot('gym',self.paths['gym']))
        with self.assertRaises(PermissionError):links.coach_nutrition(self.store,self.coach,self.uid)
    def new_weight(self,value=78):
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE user_health_profile SET weight_kg=?,updated_at_utc=?',(value,(self.now+timedelta(seconds=1)).isoformat()))
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
    def test_weight_change_optin_no_replay_and_verified_goal_edit_completes(self):
        self.new_weight();self.pref(weight_notifications=True)
        self.assertFalse(hints(self.store,self.uid,'food'))
        self.new_weight(77)
        h=hints(self.store,self.uid,'food')[0];self.assertIn('77',h['message'])
        self.store.mark_hint_seen(self.uid,'food',h['delivery_key']);self.assertTrue(hints(self.store,self.uid,'food'))
        self.event('food','target:'+self.uid,'nutrition_target.changed',{'targets':{'kcal':2000,'protein':100,'fat':80,'carbs':220}})
        self.assertFalse(hints(self.store,self.uid,'food'))
    def test_changes_gated_by_owner_source_and_receiving_access(self):
        self.pref(weight_notifications=True);self.new_weight()
        self.assertTrue(recent(self.store,self.uid)['items']);self.assertFalse(recent(self.store,self.coach)['items'])
        self.store.failed('food','offline');self.assertFalse(hints(self.store,self.uid,'food'))
        self.pref(sources={'food':True,'gym':True,'supply':False});self.assertFalse(recent(self.store,self.uid)['items'])
    def test_weight_reminder_quiet_and_rest_do_not_push(self):
        self.pref(weight_notifications=True);self.new_weight();now=datetime.now(timezone.utc)
        tz='UTC' if 8<=now.hour<22 else 'Asia/Bangkok'
        if not 8<=now.astimezone(__import__('zoneinfo').ZoneInfo(tz)).hour<22:tz='America/New_York'
        p={'timezone':tz,'workout_enabled':False,'nutrient_enabled':False}
        self.assertEqual(candidate(self.store,self.uid,p,now)['kind'],'weight_review')
        self.pref(frequency='quiet');self.assertIsNone(candidate(self.store,self.uid,p,now))
        self.pref(frequency='normal',paused=True);self.assertIsNone(candidate(self.store,self.uid,p,now))

    def test_meal_events_minimal_fresh_paid_and_rest_optout_denied(self):
        from progressor_core.meal_anchors import events
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE meals SET created_at=?',(self.now.isoformat(),))
        self.store.reconcile('food',snapshot('food',self.paths['food']))
        value=events(self.store,[self.uid,self.coach],self.now)
        self.assertEqual(len(value['items']),1);self.assertEqual(value['items'][0]['user_id'],self.uid)
        self.assertEqual(set(value['items'][0]['meals'][0]),{'entity_id','occurred_at'})
        self.pref(paused=True);self.assertFalse(events(self.store,[self.uid],self.now)['items'])
        self.pref(paused=False,sources={'food':False,'gym':True,'supply':True});self.assertFalse(events(self.store,[self.uid],self.now)['items'])
        self.pref(sources={'food':True,'gym':True,'supply':True});self.store.failed('food','offline')
        self.assertFalse(events(self.store,[self.uid],self.now)['items'])

    def test_revoke_reenable_changes_ai_cache_permission_revision(self):
        from progressor_core.ai_context import build_ai_context
        first=build_ai_context(self.store,self.uid,'gym',self.now)
        self.pref(sources={'food':False,'gym':True,'supply':True})
        self.pref(sources={'food':True,'gym':True,'supply':True})
        second=build_ai_context(self.store,self.uid,'gym',self.now)
        self.assertNotEqual(ai_cache.key(first),ai_cache.key(second))

    def test_goal_related_native_hint_read_not_completion_and_no_entity_type_error(self):
        self.event('food','target:'+self.uid,'nutrition_target.changed',{'targets':{'kcal':1900,'protein':100,'fat':70,'carbs':200}})
        for target in ('gym','supply'):
            item=hints(self.store,self.uid,target)[0]
            self.assertEqual(item['action']['kind'],'gym_plan' if target=='gym' else 'supply_plan')
            self.store.mark_hint_seen(self.uid,target,item['delivery_key']);self.assertTrue(hints(self.store,self.uid,target))
        self.stamp=(self.now+timedelta(seconds=3)).isoformat()
        self.event('gym','workout:selected-finished','workout.completed',{'completed_at':self.stamp,'source_local_date':self.now.date().isoformat(),'timezone':'UTC','workout_type':'strength','duration_seconds':None,'strength_sets':3,'session_complete':True})
        self.assertFalse(hints(self.store,self.uid,'gym'));self.assertTrue(hints(self.store,self.uid,'supply'))

    def test_quiet_retains_read_hint_and_limits_different_new_hint_across_products(self):
        from progressor_core.context import build_context
        self.pref(weight_notifications=True,frequency='quiet');self.new_weight(78)
        first=build_context(self.store,self.uid,target='food')['inline_hint'];self.assertTrue(first)
        self.store.mark_hint_seen(self.uid,'food',first['delivery_key'])
        self.assertEqual(build_context(self.store,self.uid,target='food')['inline_hint']['delivery_key'],first['delivery_key'])
        self.new_weight(77);self.assertIsNone(build_context(self.store,self.uid,target='food')['inline_hint'])
        self.pref(frequency='normal');self.assertIsNotNone(build_context(self.store,self.uid,target='food')['inline_hint'])

class ResponseCache(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'cache.db')
    def tearDown(self):self.tmp.cleanup()
    def test_scope_owner_ttl_and_changed_data_do_not_match(self):
        k=ai_cache.key({'weight':80,'observed_at':10,'generated_at':1});ai_cache.put(self.path,'1','food',k,{'ok':1},60,100)
        self.assertEqual(ai_cache.get(self.path,'1','food',k,159),{'ok':1})
        for uid,scope,stamp in (('2','food',101),('1','gym',101),('1','food',160)):self.assertIsNone(ai_cache.get(self.path,uid,scope,k,stamp))
        self.assertNotEqual(k,ai_cache.key({'weight':80,'observed_at':11}))
        self.assertEqual(k,ai_cache.key({'weight':80,'observed_at':10,'generated_at':2}))
    def test_owner_retention_is_bounded_and_purge_is_scoped(self):
        for i in range(20):ai_cache.put(self.path,'1','food',ai_cache.key({'i':i}),i,3600,100+i)
        k=ai_cache.key({'other':1});ai_cache.put(self.path,'2','food',k,2,3600,130)
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute("SELECT count(*) FROM progressor_ai_cache WHERE user_id='1'").fetchone()[0],12)
        ai_cache.purge(self.path,'1');self.assertEqual(ai_cache.get(self.path,'2','food',k,140),2)
    def test_permission_and_prompt_changes_invalidate_cache(self):
        base={'model':'one','prompt':'v2','sources':{'food':{'consent':True,'totals':100}}};k=ai_cache.key(base)
        for changed in ({**base,'prompt':'v3'},{**base,'sources':None},{**base,'sources':{'food':{'consent':False,'totals':100}}},{**base,'model':'two'}):self.assertNotEqual(k,ai_cache.key(changed))
