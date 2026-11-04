"""Synthetic real-SQLite notification contract checks; no delivery/API."""
import copy
import hashlib
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from progressor_core import notifications
from progressor_core.workout_notification_compat import (
    POLICY_OBJECTS, legacy_programmed_workout, suppress_free_notifications)


NOW=datetime(2026,10,26,12,tzinfo=timezone.utc)
OWNER='900000000001'
KEY='workout_today.v1:2026-10-26'
EXPECTED_POST={'kind':'post_workout','day':'2026-10-26','delivery_key':KEY,
 'text':'Тренировка записана в Gym. До вашей текущей цели в журнале Food осталось: 1000 ккал; белки 50 г, жиры 20 г, углеводы 130 г. Это разница с вашей целью по записанным блюдам, а не назначение дополнительной еды. Обычная активность уже может входить в цель.',
 'action':'open_food'}


class SyntheticStore:
    def __init__(self,path):
        self.path=Path(path)
        self.queries=[]
        self.changed=0
        self.failure=False
        self.dismissed=False
        self.seen=set()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE sentinel(value INTEGER); INSERT INTO sentinel VALUES(7);')
    @contextmanager
    def connection(self):
        if self.failure:raise sqlite3.OperationalError('synthetic inspection unavailable')
        db=sqlite3.connect(self.path)
        db.set_trace_callback(self.queries.append)
        try:
            with db:yield db
        finally:
            self.changed+=db.total_changes
            db.close()
    def hints_dismissed(self,user,target):return self.dismissed
    def hint_was_seen(self,user,target,key):return (target,key)in self.seen
    def install(self,sql):
        with closing(sqlite3.connect(self.path))as db,db:db.executescript(sql)
    def digest(self):return hashlib.sha256(self.path.read_bytes()).hexdigest()


class OwnedCase(unittest.TestCase):
    def setUp(self):
        self.scratch=Path(os.getenv('PROGRESSOR_TEST_TMP_DIR') or tempfile.gettempdir()).resolve(strict=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='shim-',dir=self.scratch)
        self.directory=Path(self.tmp.name).resolve(strict=True)
        self.assertTrue(self.directory.is_relative_to(self.scratch))
        self.store=SyntheticStore(self.directory/'core.sqlite3')
    def tearDown(self):
        self.assertTrue(self.directory.resolve(strict=True).is_relative_to(self.scratch))
        self.tmp.cleanup()


class Inspection(OwnedCase):
    def test_absent_policy_is_a_single_read_and_does_not_create_anything(self):
        before=self.store.digest()
        self.assertFalse(suppress_free_notifications(self.store))
        self.assertEqual(len(self.store.queries),1)
        self.assertIn('sqlite_master',self.store.queries[0])
        self.assertEqual(self.store.changed,0)
        self.assertEqual(before,self.store.digest())

    def test_either_empty_reserved_table_suppresses_without_initializing_rows(self):
        for name in POLICY_OBJECTS:
            with self.subTest(name=name):
                self.store.install('CREATE TABLE '+name+'(wrong_column TEXT);')
                before=self.store.digest()
                self.assertTrue(suppress_free_notifications(self.store))
                self.assertEqual(self.store.changed,0)
                self.assertEqual(before,self.store.digest())
                with closing(sqlite3.connect(self.store.path))as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM '+name).fetchone()[0],0)
                self.store.install('DROP TABLE '+name+';')

    def test_malformed_policy_unknown_version_and_deleted_rows_stay_suppressed(self):
        name=POLICY_OBJECTS[0]
        self.store.install('CREATE TABLE '+name+'(protocol,adopted_at); INSERT INTO '+name+" VALUES(999,'invalid');")
        self.assertTrue(suppress_free_notifications(self.store))
        self.store.install('DELETE FROM '+name+';')
        self.assertTrue(suppress_free_notifications(self.store))
        self.assertEqual(self.store.changed,0)

    def test_case_insensitive_reserved_name_and_every_object_type_fail_closed(self):
        statements=(
            'CREATE TABLE FREE_WORKOUT_NOTIFICATION_POLICY(arbitrary);',
            'CREATE VIEW FREE_WORKOUT_NOTIFICATION_ADMISSIONS AS SELECT * FROM missing_table;',
            'CREATE INDEX FREE_WORKOUT_NOTIFICATION_POLICY ON sentinel(value);',
            'CREATE TRIGGER FREE_WORKOUT_NOTIFICATION_ADMISSIONS AFTER INSERT ON sentinel BEGIN SELECT 1; END;')
        drops=('DROP TABLE FREE_WORKOUT_NOTIFICATION_POLICY;',
               'DROP VIEW FREE_WORKOUT_NOTIFICATION_ADMISSIONS;',
               'DROP INDEX FREE_WORKOUT_NOTIFICATION_POLICY;',
               'DROP TRIGGER FREE_WORKOUT_NOTIFICATION_ADMISSIONS;')
        for sql,drop in zip(statements,drops):
            with self.subTest(sql=sql):
                self.store.install(sql)
                before=self.store.digest()
                self.assertTrue(suppress_free_notifications(self.store))
                self.assertEqual(before,self.store.digest())
                self.store.install(drop)
        self.assertEqual(self.store.changed,0)

    def test_similar_names_do_not_activate_the_policy(self):
        self.store.install('CREATE TABLE free_workout_notification_policy_extra(x);'
                           'CREATE TABLE old_free_workout_notification_admissions(x);')
        self.assertFalse(suppress_free_notifications(self.store))

    def test_sqlite_inspection_error_is_conservative(self):
        self.store.failure=True
        self.assertTrue(suppress_free_notifications(self.store))

    def test_only_exact_ascii_numeric_programmed_shape_is_legacy(self):
        for value in ('workout:1','workout:10','workout:9223372036854775807'):
            self.assertTrue(legacy_programmed_workout({'entity_id':value}),value)
        for value in (None,True,7,'','workout:0','workout:01','workout:-1',
                      'workout:+1','workout:1\n','workout:1:extra','workout:session:1',
                      'workout:session:01','workout:abc:1','workout:١','workout:１',
                      'WORKOUT:1',' workout:1'):
            self.assertFalse(legacy_programmed_workout({'entity_id':value}),repr(value))


def workout(entity_id='workout:session:7',**extra):
    return {'entity_id':entity_id,'completed_at':(NOW-timedelta(hours=1)).isoformat(),
            'session_complete':True,'backfilled':False,'energy_estimate':None,**extra}


class Routing(OwnedCase):
    def call(self,module=notifications,*,workouts=None,policy=None,prefs=None,context=None,weekly=None):
        p={'rest_active':False,'notifications':True,'hints':True,'frequency':'normal',
           'weight_notifications':False,'last_pause_started_at':0,**(policy or {})}
        settings={'workout_enabled':True,'nutrient_enabled':False,'timezone':'Europe/Moscow',
                  'enabled_at':(NOW-timedelta(days=3)).timestamp(),**(prefs or {})}
        c={'access':{'domains':{'food':True}},'memberships':['food','gym'],
           'sources':{'food':{'status':'ok'},'gym':{'status':'ok'}},
           'activity':{'workouts':copy.deepcopy([workout()]if workouts is None else workouts)},
           'hints':[{'key':'workout_today.v1','delivery_key':KEY,'targets':['food','gym']}],
           'nutrition':{'targets':{'kcal':2200},'today':{'remaining_to_personal_goal':{
               'kcal':1000,'protein':50,'fat':20,'carbs':130}}},**(context or {})}
        with patch.object(module,'build_context',return_value=c),\
             patch('progressor_core.connections.preferences',return_value=p),\
             patch('progressor_core.weekly_plan.notification',return_value=weekly):
            return module.candidate(self.store,OWNER,settings,NOW)
    def activate(self):self.store.install('CREATE TABLE '+POLICY_OBJECTS[0]+'(arbitrary);')
    def test_full_reader_absent_policy_keeps_only_numeric_legacy_compatibility(self):
        before=self.store.digest()
        for ident in ('workout:session:7','workout:10','workout:old:7',None):
            with self.subTest(entity_id=ident):
                expected=EXPECTED_POST if ident=='workout:10' else None
                self.assertEqual(self.call(workouts=[workout(ident)]),expected)
        self.assertEqual(self.store.changed,0)
        self.assertEqual(self.store.digest(),before)

    def test_present_policy_suppresses_genuine_and_unclassified_free_candidates(self):
        self.activate()
        for ident in ('workout:session:7','workout:session:01','workout:7:suffix',
                      'workout:0','workout:01','workout:١',None):
            with self.subTest(entity_id=ident):
                self.assertIsNone(self.call(notifications,workouts=[workout(ident)]))

    def test_admissions_only_and_unknown_schema_do_not_fail_open(self):
        self.store.install('CREATE VIEW Free_Workout_Notification_Admissions AS SELECT * FROM nonexistent;')
        self.assertIsNone(self.call())

    def test_numeric_only_is_exactly_unchanged_without_policy_inspection(self):
        self.activate()
        self.store.queries.clear()
        self.assertEqual(self.call(workouts=[workout('workout:10')]),EXPECTED_POST)
        self.assertEqual(self.store.queries,[])

    def test_mixed_workout_list_keeps_numeric_trigger_but_free_cannot_trigger_alone(self):
        self.activate()
        rows=[workout(),workout('workout:10')]
        self.assertEqual(self.call(workouts=rows),EXPECTED_POST)
        self.assertIsNone(self.call(workouts=[rows[0]]))

    def test_partial_free_still_suppresses_numeric_followup_as_before(self):
        self.activate()
        self.assertIsNone(self.call(workouts=[workout(session_complete=False),workout('workout:10')]))

    def test_inspection_failure_suppresses_free_and_preserves_numeric_in_mixed_list(self):
        self.store.failure=True
        self.assertIsNone(self.call())
        self.assertEqual(self.call(workouts=[workout(),workout('workout:10')]),EXPECTED_POST)
        self.assertEqual(self.call(workouts=[workout('workout:10')]),EXPECTED_POST)

    def test_workout_optout_and_no_workout_do_not_inspect_policy(self):
        self.activate()
        self.store.queries.clear()
        self.assertIsNone(self.call(prefs={'workout_enabled':False}))
        self.assertIsNone(self.call(workouts=[]))
        self.assertEqual(self.store.queries,[])

    def test_weekly_priority_and_weight_priority_are_exactly_unchanged(self):
        self.activate()
        self.store.queries.clear()
        weekly={'kind':'weekly_plan','delivery_key':'weekly_plan:2026-W44','text':'synthetic weekly'}
        self.assertEqual(self.call(weekly=weekly),weekly)
        weight={'key':'change_weight.v1','delivery_key':'weight:1','targets':['food'],
                'title':'Вес изменился','message':'Проверьте цель.'}
        self.assertEqual(self.call(policy={'weight_notifications':True},context={'hints':[weight]}),
                         {'kind':'weight_review','day':'2026-10-26','delivery_key':'weight:1',
                          'text':'Вес изменился\n\nПроверьте цель.','action':'open_food'})
        self.assertEqual(self.store.queries,[])

    def test_nutrient_candidate_unchanged_and_remains_available_after_free_is_suppressed(self):
        self.activate()
        nutrient={'key':'food_sources_vitamin_b12.v1','delivery_key':'food_sources_b12:1',
                  'targets':['food'],'title':'Пищевые источники','message':'Проверьте записи.'}
        expected={'kind':'nutrient_review','day':'2026-10-26','delivery_key':'food_sources_b12:1',
                  'text':'Пищевые источники\n\nПроверьте записи.\n\nПроверьте полноту дневника. Это оценка источников в записанных блюдах; по ней нельзя установить дефицит организма или выбрать дозу добавки.',
                  'action':'open_food'}
        self.assertEqual(self.call(prefs={'workout_enabled':False,'nutrient_enabled':True},context={'hints':[nutrient]}),expected)
        self.assertEqual(self.call(prefs={'nutrient_enabled':True},context={'hints':[nutrient]}),expected)

    def test_original_access_quiet_rest_and_own_optin_guards_are_not_bypassed(self):
        self.activate()
        rows=[workout('workout:10')]
        variants=(
          {'policy':{'rest_active':True}},
          {'policy':{'notifications':False}},
          {'policy':{'hints':False}},
          {'prefs':{'timezone':'Pacific/Honolulu'}},
          {'prefs':{'enabled_at':NOW.timestamp()}},
          {'context':{'access':{'domains':{'food':False}}}},
          {'context':{'sources':{'food':{'status':'degraded'}}}},
          {'context':{'workout_follow_up':'food_day_confirmed'}})
        for extra in variants:
            with self.subTest(extra=extra):self.assertIsNone(self.call(workouts=rows,**extra))
        self.store.seen.add(('food',KEY))
        self.assertIsNone(self.call(workouts=rows))
        self.store.seen.clear();self.store.dismissed=True
        self.assertIsNone(self.call(workouts=rows))

    def test_unknown_free_never_reads_admission_or_writes_during_candidate_calculation(self):
        self.activate()
        before=self.store.digest();self.store.queries.clear()
        self.assertIsNone(self.call(workouts=[workout(),workout('workout:session:8')]))
        self.assertEqual(len(self.store.queries),0)
        self.assertEqual(self.store.changed,0)
        self.assertEqual(self.store.digest(),before)


if __name__=='__main__':unittest.main()
