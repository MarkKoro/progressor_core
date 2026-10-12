import json,os,sqlite3,tempfile,unittest,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from test_integration import fixture,USER
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core import connections as links
from progressor_core.weekly_plan import review,notification
from progressor_core.training_rhythm import proposal,confirm,active,disable
from shared.day_goal import redistribute,goal_key

NOW=datetime(2026,10,12,7,tzinfo=timezone.utc)

class Connections(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db');self.uid=str(USER)
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
    def tearDown(self):self.tmp.cleanup()
    def change(self,**patches):
        p=links.preferences(self.store,self.uid);return links.save_preferences(self.store,self.uid,patches,p['revision'])
    def event(self,source,ident,stamp,payload):
        with self.store.connection() as db:
            r=db.execute('SELECT revision FROM entities WHERE source=? AND entity_id=?',(source,ident)).fetchone()
        rev=r[0]+1 if r else 1
        if ident.startswith('workout:'):payload={'workout_type':'strength','duration_seconds':None,'strength_sets':0,**payload}
        self.store.accept({'event_id':str(uuid.uuid4()),'event_type':'profile.updated' if ident.startswith('profile:') else 'workout.completed' if source=='gym' else 'nutrition_target.changed' if ident.startswith('target:') else 'daily_nutrition.updated',
            'schema_version':1,'source':source,'user_id':self.uid,'occurred_at':stamp.isoformat(),'correlation_id':'offline-selected',
            'payload':{'entity_id':ident,'revision':rev,**payload}})
    def days(self,confirmed=5):
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('DELETE FROM meals');db.execute('DELETE FROM meal_nutrients')
            db.execute('CREATE TABLE progressor_day_closure(user_id INTEGER,day TEXT,meal_versions TEXT,confirmed_at REAL,method TEXT)')
            for i in range(7):
                day=(NOW.date()-timedelta(days=i+1)).isoformat();ident=i+30
                db.execute('INSERT INTO meals VALUES(?,?,?,1800,70,60,225,?,0)',(ident,USER,day,day+' 19:00:00'))
                if i<confirmed:db.execute('INSERT INTO progressor_day_closure VALUES(?,?,?,?,?)',(USER,day,json.dumps([[ident,0]]),NOW.timestamp(),'explicit_button'))
        self.store.reconcile('food',snapshot('food',self.paths['food']))
    def workouts(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM day_completion_history')
        self.store.reconcile('gym',snapshot('gym',self.paths['gym']))
        for i,day in enumerate(('2026-09-24','2026-09-29','2026-10-01','2026-10-06','2026-10-08')):
            stamp=datetime.fromisoformat(day+'T12:00:00+00:00')
            self.event('gym','workout:rhythm'+str(i),stamp,{'completed_at':stamp.isoformat(),'timezone':'Europe/Moscow','program_id':1,'day_index':1,'session_id':i+100,'session_complete':True,'strength_sets':5})
    def test_preferences_are_cas_and_rest_preserves_subscription_and_choices(self):
        before=links.permitted_entities(self.store,self.uid,NOW)[2]
        p=self.change(paused=True,weekly_plan=True,notifications=False)
        self.assertTrue(p['rest_active']);self.assertTrue(p['subscription_time_continues'])
        self.assertEqual(before,links.permitted_entities(self.store,self.uid,NOW)[2])
        with self.assertRaises(ValueError):links.save_preferences(self.store,self.uid,{'hints':False},0)
        p=self.change(paused=False);self.assertTrue(p['weekly_plan']);self.assertFalse(p['notifications'])
    def test_preferences_reject_unknown_invalid_schedule_and_boolean_values(self):
        for fields in ({'weekly_plan':1},{'weekly_day':'daily'},{'weekly_hour':True},{'weekly_hour':22},{'unknown':True},{'sources':{'food':False}}):
            with self.assertRaises(ValueError):self.change(**fields)
    def test_disabled_or_failed_sources_are_absent(self):
        self.change(sources={'food':True,'gym':False,'supply':False});self.workouts()
        self.assertNotEqual(proposal(self.store,self.uid,NOW)['status'],'proposal')
        self.store.failed('food','offline');self.assertFalse(review(self.store,self.uid,NOW)['available'])
    def test_weekly_uses_confirmed_days_and_existing_goal(self):
        self.days();r=review(self.store,self.uid,NOW)
        self.assertEqual(r['confirmed_days'],5);self.assertEqual(r['logged_days'],7)
        self.assertEqual(r['remaining_to_personal_goal']['protein'],30)
        self.assertNotIn('дефицит',r['text']);self.assertEqual(r['averages_on_confirmed_days']['kcal'],1800)
    def test_weekly_missing_or_changed_data_never_calls_it_undereating(self):
        self.days(0);self.assertIsNone(review(self.store,self.uid,NOW)['remaining_to_personal_goal'])
        self.event('food','target:'+self.uid,NOW-timedelta(days=1),{'targets':{'kcal':2200,'protein':100,'fat':80,'carbs':250}})
        self.assertFalse(review(self.store,self.uid,NOW)['goal_stable'])
    def test_weekly_is_opt_in_local_time_quiet_and_rest_gated(self):
        self.days();prefs={'timezone':'Europe/Moscow'}
        self.assertIsNone(notification(self.store,self.uid,prefs,NOW));self.change(weekly_plan=True)
        n=notification(self.store,self.uid,prefs,NOW);self.assertEqual(n['kind'],'weekly_plan')
        self.assertIsNone(notification(self.store,self.uid,{'timezone':'Pacific/Honolulu'},NOW))
        self.change(paused=True);self.assertIsNone(notification(self.store,self.uid,prefs,NOW))
    def test_weekly_diet_and_exclusions_filter_examples(self):
        self.days();self.change(diet='vegan');r=review(self.store,self.uid,NOW)
        self.assertTrue(r['suggestions']);self.assertFalse(any(w in ' '.join(r['suggestions']) for w in ('рыба','яйца','творог','птица')))
        self.change(excluded_food_groups=['soy']);self.assertNotIn('Тофу', ' '.join(review(self.store,self.uid,NOW)['suggestions']))

    def test_confirmed_rhythm_new_goal_then_old_values_never_resurrect(self):
        self.workouts();p=proposal(self.store,self.uid,NOW);confirm(self.store,self.uid,p['fingerprint'],p['base_goal_key'],100,NOW)
        for calories in (2000,2200):
            self.event('food','target:'+self.uid,NOW,{'targets':{'kcal':calories,'protein':100,'fat':80,'carbs':250}})
            self.assertIsNone(active(self.store,self.uid,NOW))

    def test_confirmed_rhythm_extra_weekday_rest_and_stale_source_use_base(self):
        self.workouts();p=proposal(self.store,self.uid,NOW);confirm(self.store,self.uid,p['fingerprint'],p['base_goal_key'],100,NOW)
        self.change(paused=True);self.assertIsNone(active(self.store,self.uid,NOW));self.change(paused=False)
        stamp=NOW+timedelta(hours=1)
        self.event('gym','workout:outside',stamp,{'completed_at':stamp.isoformat(),'timezone':'UTC','program_id':1,'session_complete':True})
        self.assertIsNone(active(self.store,self.uid,stamp))
    def test_rhythm_proposes_after_two_weeks_but_never_applies_without_confirmation(self):
        self.workouts();p=proposal(self.store,self.uid,NOW)
        self.assertEqual(p['status'],'proposal');self.assertEqual(p['weekdays'],[1,3]);self.assertIsNone(active(self.store,self.uid,NOW))
        r=confirm(self.store,self.uid,p['fingerprint'],p['base_goal_key'],100,NOW)
        self.assertAlmostEqual(sum(d['kcal'] for d in r['days']),7*2200,places=2)
        self.assertTrue(all(d['protein']==100 and d['fat']==80 for d in r['days']))
        self.assertEqual(r['days'][1]['kcal'],2300);self.assertLess(r['days'][0]['kcal'],2200)
    def test_rhythm_stale_selection_expiry_new_goal_and_optout_restore_base(self):
        self.workouts();p=proposal(self.store,self.uid,NOW)
        with self.assertRaises(ValueError):confirm(self.store,self.uid,'old',p['base_goal_key'],100,NOW)
        confirm(self.store,self.uid,p['fingerprint'],p['base_goal_key'],100,NOW)
        self.assertIsNone(active(self.store,self.uid,NOW+timedelta(days=29)))
        self.change(sources={'gym':False,'food':True,'supply':True});self.assertIsNone(active(self.store,self.uid,NOW))
        self.change(sources={'gym':True,'food':True,'supply':True})
        self.event('food','target:'+self.uid,NOW,{'targets':{'kcal':2000,'protein':100,'fat':80,'carbs':200}})
        self.assertIsNone(active(self.store,self.uid,NOW));disable(self.store,self.uid)
    def test_changed_program_or_variable_days_do_not_form_habit(self):
        self.workouts();stamp=NOW-timedelta(days=2)
        self.event('gym','workout:other',stamp,{'completed_at':stamp.isoformat(),'timezone':'Europe/Moscow','program_id':2,'session_complete':True})
        self.assertNotEqual(proposal(self.store,self.uid,NOW)['status'],'proposal')
    def test_redistribution_rejects_invalid_unknown_and_too_low_carbs(self):
        base={'kcal':2200,'protein':100,'fat':80,'carbs':250}
        for weekdays,extra in (([1,1],100),([7],100),([True],100),([1],99)):
            with self.assertRaises(ValueError):redistribute(base,weekdays,extra)
        with self.assertRaises(ValueError):redistribute({**base,'carbs':40},[1,3],100)
        self.assertEqual(goal_key(base),goal_key({k:float(v) for k,v in base.items()}))
