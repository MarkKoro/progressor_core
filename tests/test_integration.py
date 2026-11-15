import base64
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
import concurrent.futures
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from progressor_core.adapters import snapshot, read_only
from progressor_core.app import Config, Engine, create_app
from progressor_core.auth import sign_assertion, verify_assertion, telegram_user
from progressor_core.context import build_context
from progressor_core.contracts import digest, subject
from shared.domain_bridge import install_auth_bridge, current_claims, verify

USER = 2**60 + 123
OTHER = 2**60 + 456
KEY = 'integration-test-key-' + 'x' * 64
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
TOKENS = {s: s + '-dummy-bot-token' for s in ('gym','food','supply')}


def launch(user=USER, source='gym', auth_date=None):
    import time
    data = {'user': json.dumps({'id': user, 'first_name': 'Test'}, separators=(',', ':')), 'auth_date': str(auth_date or int(time.time())), 'query_id':'synthetic-launch'}
    secret = hmac.new(b'WebAppData', TOKENS[source].encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def fixture(root):
    paths = {s: str(root / (s + '.sqlite3')) for s in ('gym','food','supply')}
    with sqlite3.connect(paths['gym']) as db:
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER UNIQUE,tz TEXT,created_at TEXT);
        CREATE TABLE day_completion_history(id INTEGER PRIMARY KEY,user_id INTEGER,system_id INTEGER,day_index INTEGER,completed_at TEXT);
        CREATE TABLE sessions(id INTEGER PRIMARY KEY,user_id INTEGER,date TEXT,day_index INTEGER,system_id INTEGER);
        CREATE TABLE sets(id INTEGER PRIMARY KEY,session_id INTEGER,is_warmup INTEGER);
        CREATE TABLE running_entries(id INTEGER PRIMARY KEY,session_id INTEGER,is_draft INTEGER,duration_sec INTEGER,duration_ms INTEGER);
        CREATE TABLE user_measurements(id INTEGER PRIMARY KEY,user_id INTEGER,metric TEXT,value REAL,created_at TEXT);
        CREATE TABLE subscriptions(user_id INTEGER,expires_at TEXT,status TEXT);''')
        db.executemany('INSERT INTO users VALUES(?,?,?,?)', [(7,USER,'Asia/Bangkok','2026-01-01T00:00:00Z'),(8,OTHER,'UTC','2026-01-01T00:00:00Z')])
        db.execute("INSERT INTO day_completion_history VALUES(10,7,1,1,'2026-10-07T09:00:00Z')")
        db.execute("INSERT INTO sessions VALUES(20,7,'2026-10-07',1,1)")
        db.execute('INSERT INTO sets VALUES(30,20,0)')
        db.executemany("INSERT INTO subscriptions VALUES(?,'2030-01-01T00:00:00Z','active')",[(7,),(8,)])
    with sqlite3.connect(paths['food']) as db:
        db.executescript('''CREATE TABLE users(telegram_id INTEGER PRIMARY KEY,created_at TEXT,is_premium INTEGER DEFAULT 1,premium_until TEXT DEFAULT '2030-01-01T00:00:00Z');
        CREATE TABLE meals(id INTEGER PRIMARY KEY,user_id INTEGER,date TEXT,kcal REAL,protein REAL,fat REAL,carbs REAL,created_at TEXT,version INTEGER);
        CREATE TABLE goals(user_id INTEGER PRIMARY KEY,kcal INTEGER,protein REAL,fat REAL,carbs REAL,updated_at TEXT);
        CREATE TABLE meal_nutrients(meal_id INTEGER,nutrient_code TEXT,value REAL,unit TEXT,source TEXT,confidence TEXT,reference TEXT,meal_version INTEGER,revision INTEGER,updated_at TEXT);''')
        db.execute("INSERT INTO users(telegram_id,created_at) VALUES(?,'2026-01-01 00:00:00')", (USER,))
        for i, day in enumerate(('2026-10-04','2026-10-05','2026-10-06'),1):
            db.execute('INSERT INTO meals VALUES(?,?,?,1500,40,50,200,?,0)', (i,USER,day,day+' 12:00:00'))
        db.execute("INSERT INTO goals VALUES(?,2200,100,80,250,'2026-01-01 00:00:00')", (USER,))
        db.executemany("INSERT INTO meal_nutrients VALUES(?,'iron',?,'mg','food_label','user_reported','label',0,1,'2026-10-06T00:00:00Z')", [(1,10),(3,0)])
    with sqlite3.connect(paths['supply']) as db:
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,tg_user_id INTEGER UNIQUE,tz_name TEXT,created_at TEXT,consent_given INTEGER,is_banned INTEGER,deleted_at_utc TEXT,premium_until_utc TEXT DEFAULT '2030-01-01T00:00:00Z');
        CREATE TABLE user_supplements(id INTEGER PRIMARY KEY,user_id INTEGER,supplement_id INTEGER,is_active INTEGER,enabled INTEGER,user_frozen INTEGER,created_at TEXT);
        CREATE TABLE supplement_day_state(user_id INTEGER,supplement_id INTEGER,day TEXT,status TEXT,created_at TEXT);
        CREATE TABLE lab_reports(id INTEGER PRIMARY KEY,user_id INTEGER,report_date TEXT,parse_status TEXT,updated_at_utc TEXT,created_at_utc TEXT);
        CREATE TABLE lab_results(id INTEGER PRIMARY KEY,report_id INTEGER,user_id INTEGER);''')
        db.execute("INSERT INTO users(id,tg_user_id,tz_name,created_at,consent_given,is_banned,deleted_at_utc) VALUES(55,?,'UTC+03:00','2026-01-01T00:00:00Z',1,0,'')", (USER,))
        db.execute("INSERT INTO user_supplements VALUES(1,55,5,1,1,0,'2026-01-01T00:00:00Z')")
        db.execute("INSERT INTO supplement_day_state VALUES(55,5,'2026-10-06','taken','2026-10-06T09:00:00Z')")
    return paths


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.root = Path(self.tmp.name)
        self.paths = fixture(self.root)
        self.config = Config(str(self.root/'core.sqlite3'), KEY, self.paths, TOKENS, {s:'ingest-'+s for s in TOKENS}, background=False)
        self.engine = Engine(self.config)
        self.engine.poll()

    def tearDown(self):
        import gc
        gc.collect()
        permitted = os.environ.get('PROGRESSOR_TEST_TMP_DIR')
        if permitted and not self.root.absolute().is_relative_to(Path(permitted).absolute()):
            raise RuntimeError('test_cleanup_outside_scratch')
        self.tmp.cleanup()

    def context(self, user=USER):
        return build_context(self.engine.store, str(user), NOW)

    def event(self, revision=1, kind='workout.completed'):
        return {'event_id':'explicit-'+str(revision), 'event_type':kind, 'schema_version':1,'source':'gym','user_id':str(USER),'occurred_at':'2026-10-07T10:00:00Z','correlation_id':'test-correlation','payload':{'entity_id':'workout:explicit','revision':revision,'completed_at':'2026-10-07T10:00:00Z','source_local_date':'2026-10-07','timezone':'UTC','workout_type':'strength','duration_seconds':None,'energy_kcal_range':None,'strength_sets':3}}

    def test_gym_event_core_food_activity(self):
        activity = self.context()['activity']
        self.assertEqual(activity['completed_workout_count'], 1)
        self.assertEqual(activity['workouts'][0]['duration_seconds'], None)
        self.assertEqual(activity['calorie_target_adjustment'], None)
        self.assertTrue(activity['provenance'])

    def test_food_history_core_supply_recommendation(self):
        data = self.context()
        self.assertEqual(data['nutrition']['history']['7']['logged_days'],3)
        self.assertEqual(len(data['recommendations']),1)
        self.assertEqual(data['recommendations'][0]['calculation']['logged_protein_average_g'],40)
        self.assertEqual(data['recommendations'][0]['confidence'],'limited')
        self.assertIn('нельзя установить клинический дефицит',data['recommendations'][0]['uncertainty'])
        self.assertEqual(data['notification_delivery'],'webapp_only')

    def test_supply_internal_id_mapping(self):
        data = self.context()
        self.assertEqual(data['supply']['active_supplement_count'],1)
        self.assertEqual(data['supply']['recorded_intake_count'],1)
        self.assertEqual(data['memberships'],['food','gym','supply'])

    def test_historical_mapping_64bit_subject(self):
        _, members, _ = self.engine.store.data(str(USER))
        self.assertEqual({m['source']:m['local_id'] for m in members},{'gym':'7','food':str(USER),'supply':'55'})
        self.assertEqual(self.context()['user_id'],str(USER))
        for bad in (True, 0, -1, 1.1, '001',str(2**63)):
            with self.assertRaises(ValueError): subject(bad)

    def test_only_one_product(self):
        data = self.context(OTHER)
        self.assertEqual(data['memberships'],['gym'])
        self.assertIsNone(data['nutrition'])
        self.assertEqual(data['recommendations'],[])

    def test_duplicate_no_effect(self):
        event = self.event()
        self.assertEqual(self.engine.store.accept(event),'accepted')
        self.assertEqual(self.engine.store.accept(event),'duplicate')
        with self.engine.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events WHERE event_id=?',(event['event_id'],)).fetchone()[0],1)

    def test_concurrent_duplicate_deliveries_are_atomic(self):
        event=self.event()
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            statuses=list(pool.map(lambda _: self.engine.store.accept(event),range(12)))
        self.assertEqual(statuses.count('accepted'),1)
        self.assertEqual(statuses.count('duplicate'),11)

    def test_typed_payload_rejected_before_projection(self):
        for field,value in [('completed_at','unparseable'),('workout_type','made-up'),('duration_seconds',-1),('strength_sets',True),('revision',2**63),('entity_id','daily:spoof')]:
            event=self.event(); event['payload'][field]=value
            with self.assertRaises((ValueError,TypeError)): self.engine.store.accept(event)
        self.assertEqual(self.context()['activity']['completed_workout_count'],1)

    def test_automatic_ai_coverage_reaches_supply_context(self):
        with sqlite3.connect(self.paths['food']) as db:
            db.execute("ALTER TABLE meal_nutrients ADD COLUMN coverage_json TEXT DEFAULT '{}'")
            db.execute("UPDATE meal_nutrients SET source='ai_estimate',confidence='low',coverage_json=? WHERE meal_id=1",(json.dumps({'observed_components':1,'total_components':2}),))
        self.engine.poll()
        iron=self.context()['nutrition']['history']['7']['nutrients']['iron']
        self.assertEqual(iron['name'],'Железо')
        self.assertEqual(iron['observed_components'],2)
        self.assertEqual(iron['assessed_components'],3)
        self.assertIn('ai_estimate:low',iron['qualities'])

    def test_supply_lab_consent_and_internal_subject(self):
        with sqlite3.connect(self.paths['supply']) as db:
            db.execute("INSERT INTO lab_reports VALUES(9,55,'2026-10-01','manual','2026-10-01T10:00:00Z','2026-10-01T10:00:00Z')")
        self.engine.poll()
        self.assertEqual(self.context()['supply']['lab_report_count'],1)
        self.assertIsNone(self.context(OTHER)['supply'])
        with sqlite3.connect(self.paths['supply']) as db: db.execute('UPDATE users SET consent_given=0')
        self.engine.poll()
        self.assertEqual(self.context()['supply']['lab_report_count'],0)

    def test_bridge_bad_configuration_keeps_native_routes(self):
        app=FastAPI()
        with patch.dict(os.environ,{'PROGRESSOR_AUTH_ENABLED':'1','PROGRESSOR_SIGNING_KEY_FILE':str(self.root/'missing.key')}): install_auth_bridge(app,'food')
        @app.get('/native')
        def native(): return {'native':True}
        with TestClient(app) as client: self.assertEqual(client.get('/native').status_code,200)

    def test_paid_gym_food_without_supply_hides_supply_entirely(self):
        with sqlite3.connect(self.paths['supply']) as db: db.execute("UPDATE users SET premium_until_utc='2020-01-01T00:00:00Z'")
        self.engine.poll(); data=self.context()
        self.assertIsNone(data['supply']); self.assertNotIn('supply',data['sources'])
        self.assertEqual(data['memberships'],['food','gym']); self.assertTrue(data['recommendations'])

    def test_free_target_cannot_obtain_paid_cross_product_hints(self):
        with sqlite3.connect(self.paths['gym']) as db: db.execute('DELETE FROM subscriptions')
        self.engine.poll()
        data=build_context(self.engine.store,str(USER),NOW,target='gym')
        self.assertIsNone(data['supply']); self.assertIsNone(data['nutrition'])
        self.assertEqual(data['recommendations'],[])

    def test_native_subscription_expiry_hides_history_and_profile(self):
        data=build_context(self.engine.store,str(USER),datetime(2031,1,1,tzinfo=timezone.utc))
        self.assertEqual(data['memberships'],[])
        self.assertIsNone(data['nutrition']); self.assertIsNone(data['supply'])

    def test_duplicate_changed_content_rejected(self):
        event = self.event(); self.engine.store.accept(event)
        event['payload']['strength_sets'] = 99
        with self.assertRaisesRegex(ValueError,'event_id_conflict'): self.engine.store.accept(event)

    def test_out_of_order_cannot_resurrect_deleted(self):
        deletion = self.event(3,'workout.deleted'); self.engine.store.accept(deletion)
        self.assertEqual(self.engine.store.accept(self.event(2)),'out_of_order')
        data,_,_ = self.engine.store.data(str(USER))
        self.assertFalse(any(e['entity_id']=='workout:explicit' for e in data))

    def test_failed_source_is_not_deletion(self):
        original = len(self.engine.store.data(str(USER))[0])
        self.engine.config.source_paths['food'] = str(self.root/'missing.sqlite3')
        self.engine.poll()
        self.assertEqual(len(self.engine.store.data(str(USER))[0]),original)
        self.assertEqual(self.context()['nutrition']['reason'],'stale_food_source')
        self.assertEqual(self.context()['recommendations'],[])

    def test_each_source_degrades_independently(self):
        for source in ('gym','food','supply'):
            with self.subTest(source=source):
                self.engine.store.failed(source,'source_unavailable')
                data = self.context()
                self.assertEqual(data['sources'][source]['status'],'degraded')
                self.engine.store.reconcile(source,snapshot(source,self.paths[source]))

    def test_timezone_day_boundary(self):
        event = self.event(); event['payload']['entity_id'] = 'workout:983001'; event['occurred_at'] = event['payload']['completed_at'] = '2026-10-06T21:30:00Z'
        self.engine.store.accept(event)
        data = self.context()
        self.assertEqual(data['activity']['date'],'2026-10-07')
        self.assertEqual(data['activity']['completed_workout_count'],2)

    def test_nutrients_unknown_vs_zero_coverage(self):
        iron = self.context()['nutrition']['history']['7']['nutrients']['iron']
        self.assertEqual(iron['sum_on_observed_days'],10)
        self.assertEqual(iron['average_on_observed_days'],5)
        self.assertEqual(iron['observed_days'],2)
        self.assertEqual(iron['logged_days'],3)
        self.assertNotIn('vitamin_d',self.context()['nutrition']['history']['7']['nutrients'])

    def test_portion_update_invalidates_old_observations(self):
        with sqlite3.connect(self.paths['food']) as db: db.execute('UPDATE meals SET version=1 WHERE id=1')
        self.engine.poll()
        iron = self.context()['nutrition']['history']['7']['nutrients']['iron']
        self.assertEqual(iron['observed_days'],1)
        self.assertEqual(iron['average_on_observed_days'],0)

    def test_successful_deletion_reconciles_and_recommendation_invalidates(self):
        first = self.context()['recommendations'][0]['id']
        with sqlite3.connect(self.paths['food']) as db: db.execute('DELETE FROM meals')
        self.engine.poll()
        self.assertEqual(self.context()['recommendations'],[])
        with self.engine.store.connection() as db: self.assertEqual(db.execute('SELECT active FROM recommendations WHERE id=?',(first,)).fetchone()[0],0)

    def test_source_databases_remain_unchanged(self):
        before = {s:hashlib.sha256(Path(p).read_bytes()).hexdigest() for s,p in self.paths.items()}
        self.engine.poll()
        after = {s:hashlib.sha256(Path(p).read_bytes()).hexdigest() for s,p in self.paths.items()}
        self.assertEqual(before,after)
        with read_only(self.paths['food']) as db:
            with self.assertRaises(sqlite3.OperationalError): db.execute('DELETE FROM meals')

    def test_core_rollback_replay_compatibility(self):
        first = self.context()['recommendations'][0]['id']
        second = Engine(self.config); second.poll()
        self.assertEqual(build_context(second.store,str(USER),NOW)['recommendations'][0]['id'],first)
        with second.store.connection() as db: self.assertEqual(db.execute('SELECT count(*) FROM recommendations WHERE id=?',(first,)).fetchone()[0],1)

    def test_launch_auth_all_bots_and_cross_user_isolation(self):
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll()
            for source in TOKENS:
                response = client.post('/api/v1/sessions',json={'source':source,'init_data':launch(source=source)})
                self.assertEqual(response.status_code,200)
                tokens = response.json()['assertions']
                headers = {'X-Progressor-Auth':tokens['core']}
                data = client.get('/api/v1/me/context?day=2026-10-07&user_id='+str(OTHER),headers=headers).json()
                self.assertEqual(data['user_id'],str(USER))
                self.assertEqual(verify(tokens['food'],'food',KEY)['sub'],str(USER))
                self.assertEqual(client.get('/api/v1/me/context',headers={'X-Progressor-Auth':tokens['gym']}).status_code,401)

    def test_home_screen_rollout_is_off_by_default_and_limited_to_listed_owners(self):
        import dataclasses
        cases = [((), False, False), ((str(USER),), True, False), (('*',), True, True)]
        for listed, owner, other in cases:
            with TestClient(create_app(dataclasses.replace(self.config, home_users=listed))) as client:
                for user, expected in ((USER, owner), (OTHER, other)):
                    body = client.post('/api/v1/sessions',json={'source':'food','init_data':launch(user=user,source='food')}).json()
                    self.assertIs(body['home'], expected, (listed, user))
                self.assertEqual(client.get('/assets/home.v1.js').status_code, 200)

    def test_day_links_route_is_owner_scoped_and_read_only(self):
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll()
            tokens = client.post('/api/v1/sessions',json={'source':'food','init_data':launch(source='food')}).json()['assertions']
            self.assertEqual(client.get('/api/v1/me/connections/links?target=food').status_code,401)
            self.assertEqual(client.get('/api/v1/me/connections/links?target=nope',headers={'X-Progressor-Auth':tokens['core']}).status_code,422)
            with client.app.state.engine.store.connection() as db: before=db.execute("SELECT count(*) FROM recommendations").fetchone()[0]
            body = client.get('/api/v1/me/connections/links?target=food&user_id='+str(OTHER),headers={'X-Progressor-Auth':tokens['core']}).json()
            self.assertEqual(body['schema_version'],1)
            self.assertEqual(set(body),{'schema_version','day','cards','streak','week','coverage','goal','goal_label','rest_active','preferences_revision'})
            with client.app.state.engine.store.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM recommendations").fetchone()[0],before)

    def test_sunday_evening_week_summary_uses_the_weekly_review_opt_in(self):
        from progressor_core.notifications import candidate
        prefs={'nutrient_enabled':True,'enabled_at':0,'timezone':'Europe/Moscow'}
        sunday=datetime(2026,10,11,15,0,tzinfo=timezone.utc)  # 18:00 in Moscow
        item=candidate(self.engine.store,str(USER),prefs,now=sunday)
        self.assertIsNotNone(item)
        self.assertEqual((item['kind'],item['delivery_key'],item['action']),('nutrient_review','week_summary:2026-W41','open_food'))
        self.assertTrue(item['text'].startswith('Итог недели'))
        self.assertIn('не оценка здоровья',item['text'])
        for moment,options in ((sunday.replace(hour=8),prefs),(sunday-timedelta(days=1),prefs),(sunday,{**prefs,'nutrient_enabled':False})):
            other=candidate(self.engine.store,str(USER),options,now=moment)
            self.assertFalse(other and other['delivery_key'].startswith('week_summary'),(moment,options))

    def test_launch_signature_tampering_duplicate_expiration(self):
        for raw in (launch()+'&user=%7B%22id%22%3A1%7D',launch().replace('synthetic-launch','tampered'),launch(auth_date=1)):
            with self.assertRaises((ValueError,KeyError)): telegram_user(raw,TOKENS['gym'])

    def test_assertions_expiration_tampering_audience(self):
        token = sign_assertion({'id':USER},10000,'food',KEY,now=10000)
        self.assertEqual(verify_assertion(token,'food',KEY,now=10001)['sub'],str(USER))
        for check in (lambda:verify(token,'gym',KEY,10001),lambda:verify(token,'food',KEY,10901),lambda:verify(token[:-1]+('0' if token[-1]!='0' else '1'),'food',KEY,10001)):
            with self.assertRaises(ValueError): check()

    def test_producer_auth_unknown_version_dlq(self):
        with TestClient(create_app(self.config)) as client:
            self.assertEqual(client.post('/api/v1/events',json=self.event()).status_code,401)
            headers={'X-Progressor-Source':'gym','X-Progressor-Source-Key':'ingest-gym'}
            event=self.event(); event['schema_version']=2
            self.assertEqual(client.post('/api/v1/events',json=event,headers=headers).status_code,422)
            with client.app.state.engine.store.connection() as db: self.assertEqual(db.execute('SELECT count(*) FROM dead_letters').fetchone()[0],1)

    def test_native_domain_works_without_core_and_context_does_not_leak(self):
        key_file=self.root/'signing.key'; key_file.write_text(KEY)
        app=FastAPI()
        with patch.dict(os.environ,{'PROGRESSOR_AUTH_ENABLED':'1','PROGRESSOR_SIGNING_KEY_FILE':str(key_file)}): install_auth_bridge(app,'food')
        @app.get('/native')
        def native(request: Request):
            identity=current_claims()
            return {'mode':'shared' if identity else 'native','user_id':identity['sub'] if identity else None}
        with TestClient(app) as client:
            self.assertEqual(client.get('/native').json()['mode'],'native')
            import time
            token=sign_assertion({'id':USER},int(time.time()),'food',KEY)
            self.assertEqual(client.get('/native',headers={'X-Progressor-Auth':token}).json()['user_id'],str(USER))
            self.assertEqual(client.get('/native').json()['mode'],'native')
            self.assertEqual(client.get('/native',headers={'X-Progressor-Auth':'tampered'}).status_code,401)


if __name__=='__main__': unittest.main()
