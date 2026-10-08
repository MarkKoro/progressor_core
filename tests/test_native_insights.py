import json,os,sqlite3,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from test_integration import fixture,USER,NOW
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core.context import build_context
from progressor_core.ai_context import build_ai_context


class NativeContext(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db');self.sync()
    def tearDown(self):self.tmp.cleanup()
    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
    def context(self,target):return build_context(self.store,str(USER),NOW,target=target)
    def detailed_gym(self):
        with sqlite3.connect(self.paths['gym']) as db:
            for col,spec in (('user_exercise_id','INTEGER'),('reps','INTEGER'),('seconds','INTEGER'),('weight_kg','REAL')):
                db.execute(f'ALTER TABLE sets ADD COLUMN {col} {spec}')
            db.execute('UPDATE sets SET user_exercise_id=700,reps=10,seconds=0,weight_kg=75')
            db.execute('CREATE TABLE workout_session_details(session_id INTEGER PRIMARY KEY,history_id INTEGER,duration_seconds INTEGER,recorded_at TEXT)')
            db.execute("INSERT INTO workout_session_details VALUES(20,10,3600,'2026-10-07T09:00:00Z')")
            for i,day in enumerate(('2026-10-01','2026-10-03','2026-10-05'),100):
                db.execute('INSERT INTO day_completion_history VALUES(?,7,1,1,?)',(i,day+'T09:00:00Z'))
                db.execute('INSERT INTO sessions VALUES(?,7,?,1,1)',(i,day))
                db.execute('INSERT INTO sets(id,session_id,is_warmup,user_exercise_id,reps,seconds,weight_kg) VALUES(?,?,0,700,10,0,50)',(i,i))
        self.sync()
    def profile(self):
        p={'entity_id':'profile:health:test','revision':1,'profile_kind':'reported_health','reported_profile':{'birth_year':1990,'weight_kg':80}}
        self.store.accept({'event_id':'reported-profile-test','event_type':'profile.updated','schema_version':1,'source':'supply','user_id':str(USER),'occurred_at':(NOW-timedelta(days=1)).isoformat(),'correlation_id':'test','payload':p})

    def test_workout_card_only_after_completion_and_current_day(self):
        self.assertEqual(self.context('food')['inline_hint']['key'],'workout_today.v1')
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM day_completion_history')
        self.sync();self.assertIsNone(self.context('food')['inline_hint'])

    def test_load_comparison_and_energy_arrive_without_llm(self):
        self.detailed_gym();self.profile()
        c=self.context('food');w=c['activity']['workouts'][0]
        self.assertEqual(w['load_comparison']['status'],'higher_recorded_load')
        self.assertEqual(w['energy_estimate']['gross_kcal_range'],[280,480])
        self.assertIn('200–400',c['inline_hint']['message'])
        self.assertIsNone(c['activity']['calorie_target_adjustment'])

    def test_later_profile_weight_is_not_assigned_to_older_workout(self):
        self.detailed_gym();self.profile()
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM user_measurements')
        self.sync();self.profile()
        old=self.context('food')['activity']['workouts'][0]
        self.assertIsNotNone(old['energy_estimate'])
        later={'entity_id':'profile:health:test','revision':2,'profile_kind':'reported_health','reported_profile':{'birth_year':1990,'weight_kg':120}}
        self.store.accept({'event_id':'later-profile-test','event_type':'profile.updated','schema_version':1,'source':'supply','user_id':str(USER),'occurred_at':NOW.isoformat(),'correlation_id':'test','payload':later})
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])

    def test_missing_age_or_unpaid_supply_never_borrows_profile(self):
        self.detailed_gym()
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])
        self.profile()
        with sqlite3.connect(self.paths['supply']) as db:db.execute("UPDATE users SET premium_until_utc=NULL")
        self.sync();self.profile()
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])
        self.assertIsNone(self.context('supply')['inline_hint'])

    def test_old_duplicate_completion_does_not_double_count(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute("INSERT INTO day_completion_history VALUES(11,7,1,1,'2026-10-07T09:01:00Z')")
        self.sync();self.assertEqual(self.context('food')['activity']['completed_workout_count'],1)

    def test_dismissal_is_account_and_target_scoped_survives_read(self):
        self.store.dismiss_hints(str(USER),'food')
        self.assertIsNone(self.context('food')['inline_hint'])
        self.assertIsNotNone(self.context('supply')['inline_hint'])
        self.assertFalse(self.store.hints_dismissed(str(USER+1),'food'))
        self.assertTrue(Store(self.root/'core.db').hints_dismissed(str(USER),'food'))

    def test_stale_sources_have_no_inline_claims(self):
        self.store.failed('gym','test')
        self.assertIsNone(self.context('food')['inline_hint'])
        self.store.failed('food','test')
        self.assertIsNone(self.context('supply')['inline_hint'])

    def test_partial_micronutrient_history_is_not_deficiency(self):
        c=self.context('supply')
        self.assertFalse(any(h['key'].startswith('food_sources_') for h in c['hints']))
        self.assertNotIn('недостаток железа',json.dumps(c['hints'],ensure_ascii=False))

    def test_complete_estimated_food_sources_have_manual_action_not_diagnosis(self):
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('DELETE FROM meal_nutrients');db.execute('DELETE FROM meals')
            for i in range(10):
                day=(NOW-timedelta(days=i//2+1)).date().isoformat()
                db.execute('INSERT INTO meals VALUES(?,?,?,750,40,25,100,?,0)',(i+1,USER,day,day+' 12:00:00'))
                for code,value,unit in (('iron',1,'mg'),('vitamin_b12',0.3,'ug')):
                    db.execute("INSERT INTO meal_nutrients VALUES(?,?,?,?,'ai_estimate','low','estimated',0,1,?)",(i+1,code,value,unit,NOW.isoformat()))
        self.sync();c=self.context('supply')
        self.assertEqual(c['inline_hint']['key'],'food_sources_iron.v1')
        self.assertEqual(c['inline_hint']['secondary_action']['kind'],'supply_catalog')
        self.assertIn('не устанавливает дефицит',c['inline_hint']['details'])
        self.assertNotIn('дозировка',c['inline_hint']['message'])
        with sqlite3.connect(self.paths['food']) as db:
            db.execute("DELETE FROM meal_nutrients WHERE nutrient_code='iron' AND meal_id IN (1,2,3)")
        self.sync();self.assertFalse(any(h['key']=='food_sources_iron.v1' for h in self.context('supply')['hints']))

    def test_ai_context_has_bounded_metrics_without_exercise_vectors(self):
        self.detailed_gym();self.profile()
        c=build_ai_context(self.store,str(USER),'food',NOW)
        self.assertEqual(c['prompt_version'],'progressor.cross_context.v2')
        workouts=c['data']['gym']['completed_workouts_14_days']
        self.assertLessEqual(len(workouts),20)
        self.assertNotIn('exercises',workouts[-1]['strength_metrics'])
        self.assertEqual(workouts[-1]['strength_metrics']['external_volume_kg'],750)
