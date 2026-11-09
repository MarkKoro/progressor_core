import json,os,sqlite3,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from test_integration import fixture,USER,NOW
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core.context import build_context
from progressor_core.notifications import candidate
from shared.nutrition_plan import normalize_profile,calculate_plan


PROFILE={'sex_at_birth':'male','age_years':36,'height_cm':180,'weight_kg':80,'activity':'moderate','goal':'maintain','training':'strength'}


class ProfilesNotifications(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db')
        with sqlite3.connect(self.paths['gym']) as db: db.execute('UPDATE day_completion_history SET completed_at=?',((NOW-timedelta(hours=1)).isoformat(),))
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('CREATE TABLE progressor_food_profile(user_id INTEGER PRIMARY KEY,profile_json TEXT,updated_at TEXT,sharing_enabled INTEGER)')
            db.execute('INSERT INTO progressor_food_profile VALUES(?,?,?,1)',(USER,json.dumps(PROFILE),(NOW-timedelta(days=1)).isoformat()))
            db.execute("INSERT INTO meals VALUES(10,?, ?,500,20,10,70,?,0)",(USER,NOW.date().isoformat(),NOW.date().isoformat()+' 13:00:00'))
        self.sync()
        self.prefs={'workout_enabled':True,'nutrient_enabled':False,'timezone':'Europe/Moscow','enabled_at':(NOW-timedelta(hours=3)).timestamp()}
    def tearDown(self): self.tmp.cleanup()
    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
    def context(self):return build_context(self.store,str(USER),NOW,target='food')
    def event(self,source,fields,stamp=None):
        ident='profile:health:manual' if source=='supply' else 'profile:nutrition:manual'
        self.store.accept({'event_id':source+'manual','event_type':'profile.updated','schema_version':1,'source':source,'user_id':str(USER),'occurred_at':(stamp or NOW-timedelta(days=1)).isoformat(),'correlation_id':'test',
            'payload':{'entity_id':ident,'revision':1,'profile_kind':'reported_health' if source=='supply' else 'reported_nutrition','reported_profile':fields}})
    def notify(self,prefs=None,now=NOW):return candidate(self.store,str(USER),prefs or self.prefs,now)

    def test_formula_is_repeatable_goal_sensitive_and_no_eatback(self):
        a=calculate_plan(PROFILE);self.assertEqual(a,calculate_plan(PROFILE))
        self.assertEqual(a['targets']['kcal'],2725);self.assertEqual(a['targets']['protein'],128)
        self.assertTrue(a['includes_usual_activity'])
        self.assertLess(calculate_plan({**PROFILE,'goal':'lose'})['targets']['kcal'],a['targets']['kcal'])
        self.assertGreater(calculate_plan({**PROFILE,'goal':'gain'})['targets']['kcal'],a['targets']['kcal'])
    def test_missing_minor_constraints_and_unknown_are_not_invented(self):
        self.assertEqual(calculate_plan({'weight_kg':80})['status'],'incomplete_profile')
        for p in ({'age_years':17},{'has_special_constraints':True},{'diet_type':'low_carb'}):
            self.assertEqual(calculate_plan({**PROFILE,**p})['status'],'manual_goal_required')
        self.assertNotIn('weight_kg',normalize_profile({'weight_kg':True}))
        self.assertEqual(normalize_profile({'weight':'80,5'})['weight_kg'],80.5)
        self.assertNotIn('health',normalize_profile({'health':'PRIVATE MEDICAL NOTES'}))
    def test_food_profile_priority_and_missing_supply_field_fallback(self):
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE progressor_food_profile SET profile_json=?',(json.dumps({'age_years':36,'weight_kg':80}),))
        self.sync();self.event('supply',{'height_cm':180,'weight_kg':81,'sex_at_birth':'male','birth_year':1990})
        p=self.context()['profile'];self.assertEqual(p['values']['weight_kg'],80);self.assertEqual(p['provenance']['weight_kg']['source'],'food')
        self.assertEqual(p['values']['height_cm'],180);self.assertEqual(p['provenance']['height_cm']['source'],'supply')
        self.assertEqual(p['conflicts'],[])
    def test_consent_revocation_removes_food_profile_without_paid_cache_change(self):
        self.assertTrue(self.context()['access']['domains']['food'])
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE progressor_food_profile SET sharing_enabled=0')
        self.sync();c=self.context();self.assertTrue(c['access']['domains']['food']);self.assertEqual(c['profile']['values'],{})
    def test_conflicts_stop_calculation_not_overwrite_sources(self):
        self.event('supply',{'weight_kg':120,'height_cm':180,'birth_year':1990})
        c=self.context();self.assertEqual(c['profile']['values']['weight_kg'],80)
        self.assertTrue(c['profile']['conflicts']);self.assertEqual(c['profile']['nutrition_plan_preview']['status'],'conflicting_profile')
        self.assertEqual(c['nutrition']['targets']['kcal'],2200)
    def test_old_and_unpaid_profiles_never_enter_resolution(self):
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE progressor_food_profile SET updated_at=?',((NOW-timedelta(days=91)).isoformat(),))
        self.sync();self.event('supply',{'weight_kg':80,'birth_year':1990})
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE users SET premium_until_utc=NULL')
        self.sync();self.event('supply',{'weight_kg':80,'birth_year':1990})
        self.assertEqual(self.context()['profile']['values'],{})
    def test_notification_uses_goal_minus_logged_macros_not_extra_exercise(self):
        n=self.notify();self.assertEqual(n['kind'],'post_workout');self.assertIn('1700 ккал',n['text'])
        self.assertIn('белки 80 г, жиры 70 г, углеводы 180 г',n['text'])
        self.assertIsNone(self.context()['activity']['calorie_target_adjustment'])
    def test_notification_does_not_write_recommendation_metadata(self):
        with patch.object(self.store,'remember',wraps=self.store.remember) as remember:
            self.assertEqual(self.notify()['kind'],'post_workout')
            remember.assert_not_called()
            self.context()
            remember.assert_called_once()
    def test_explicit_optout_recent_delay_and_old_bootstrap_skip(self):
        self.assertIsNone(self.notify({**self.prefs,'workout_enabled':False}))
        self.assertIsNone(self.notify({**self.prefs,'enabled_at':NOW.timestamp()}))
        with sqlite3.connect(self.paths['gym']) as db:db.execute('UPDATE day_completion_history SET completed_at=?',((NOW-timedelta(minutes=5)).isoformat(),))
        self.sync();self.assertIsNone(self.notify())
    def test_seen_and_dismissed_are_account_and_target_scoped(self):
        hint=self.context()['inline_hint'];self.store.mark_hint_seen(str(USER+1),'food',hint['delivery_key'])
        self.assertIsNotNone(self.notify())
        self.store.mark_hint_seen(str(USER),'gym',hint['delivery_key']);self.assertIsNone(self.notify())
        self.store.dismiss_hints(str(USER),'food');self.assertIsNone(self.notify())
    def test_quiet_hours_unpaid_and_stale_never_send(self):
        self.assertIsNone(self.notify({**self.prefs,'timezone':'Pacific/Honolulu'}))
        self.store.failed('gym','outage');self.assertIsNone(self.notify())
        self.sync()
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE users SET is_premium=0')
        self.sync();self.assertIsNone(self.notify())
    def test_missing_logged_food_not_zero_intake(self):
        with sqlite3.connect(self.paths['food']) as db:db.execute('DELETE FROM meals WHERE id=10')
        self.sync();n=self.notify();self.assertIn('ещё нет записанных блюд',n['text']);self.assertNotIn('2200 ккал',n['text'])
        self.assertIsNone(self.context()['nutrition']['today']['totals'])
    def test_backfill_and_old_workout_never_push(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute('UPDATE day_completion_history SET completed_at=?',((NOW-timedelta(hours=3)).isoformat(),))
        self.sync();self.assertIsNone(self.notify())
