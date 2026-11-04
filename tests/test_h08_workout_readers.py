"""Owned synthetic snapshots; no provider, API, sender or production database."""
import copy
import sqlite3
import sys
import types
import unittest
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from progressor_core.adapters import gym
from progressor_core.workout_time import GymFreeTime, canonical_clock, free_activity_instant, recorded_activity_at, known_workout, completed_window, _calendar_zone, TIME_COVERAGE
from progressor_core.contracts import validate_payload
from progressor_core.journey import workout_follow_up
from progressor_core.native_insights import enrich_workouts
from progressor_core.ai_context import build_ai_context
from progressor_core.notifications import candidate

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def payload(at=None, *, complete=True, session=1):
    at = at or NOW - timedelta(hours=1)
    stamp = at.timestamp(); value = canonical_clock(stamp); day = at.date().isoformat()
    return dict(entity_id='workout:session:' + str(session), session_id=session, day_index=0, program_id=None,
        source_local_date=day, timezone='UTC', completed_at=value, recorded_at=value,
        activity_time_basis='source_last_activity', activity_day_basis='owner_validated_session_day',
        activity_clock=dict(version=1, clock_kind='native_touch', source_last_activity=stamp,
            activity_at=value, source_local_date=day, activity_timezone='UTC'),
        backfilled=False, timestamp_basis='source_utc', session_complete=complete, strength_sets=1, strength_metrics={}, workout_type='strength')


def event(p, identity=None):
    return dict(source='gym', entity_id=identity or p['entity_id'], payload=p, event_id='event-' + (identity or p['entity_id']))


class SourceClock(unittest.TestCase):
    def fixture(self):
        db = sqlite3.connect(':memory:'); self.addCleanup(db.close); db.row_factory = sqlite3.Row
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,tz TEXT,created_at TEXT);
          CREATE TABLE sessions(id INTEGER PRIMARY KEY,user_id INTEGER,date TEXT,day_index INTEGER,system_id INTEGER);
          CREATE TABLE day_completion_history(id INTEGER,user_id INTEGER,system_id INTEGER,day_index INTEGER,completed_at TEXT);
          CREATE TABLE sets(session_id INTEGER,user_exercise_id INTEGER,reps INTEGER,seconds INTEGER,weight_kg REAL,is_warmup INTEGER);
          CREATE TABLE running_entries(session_id INTEGER,user_exercise_id INTEGER,is_draft INTEGER,duration_sec REAL,duration_ms REAL);
          CREATE TABLE session_exercises(session_id INTEGER,user_exercise_id INTEGER,is_done INTEGER,done_at TEXT);
          CREATE TABLE user_measurements(id INTEGER,user_id INTEGER,metric TEXT,value REAL,created_at TEXT);
          CREATE TABLE progressor_free_sessions(session_id INTEGER PRIMARY KEY,last_activity REAL,status TEXT,completed_at TEXT,completion_basis TEXT,last_finished_at REAL);
          CREATE TABLE progressor_free_activity_proof(session_id INTEGER PRIMARY KEY,last_activity REAL,source_local_date TEXT,activity_timezone TEXT,proof_version INTEGER,clock_kind TEXT);''')
        at = datetime(2026,10,23,23,50,tzinfo=timezone.utc); stamp = at.timestamp()
        db.execute("INSERT INTO users VALUES(7,123,'Asia/Bangkok','2026-01-01T00:00:00Z')")
        db.execute("INSERT INTO sessions VALUES(1,7,'2026-10-23',0,NULL)")
        db.execute('INSERT INTO sets VALUES(1,9,10,0,50,0)')
        db.execute('INSERT INTO session_exercises VALUES(1,9,1,?)', (at.isoformat(),))
        db.execute("INSERT INTO progressor_free_sessions VALUES(1,?,'finished',?,'explicit_finish',?)", (stamp,at.isoformat(),stamp+20))
        db.execute("INSERT INTO progressor_free_activity_proof VALUES(1,?,'2026-10-23','UTC',1,'native_touch')", (stamp,))
        return db, at

    def workout(self, db):
        item = next(e for e in gym(db)['entities'] if e['entity_id'] == 'workout:session:1')
        p = item['payload']; p['entity_id'] = item['entity_id']
        return p

    def test_travel_preserves_actual_utc_day_and_native_rows(self):
        db, at = self.fixture(); before = list(db.iterdump())
        p = self.workout(db)
        self.assertEqual(p['completed_at'], '2026-10-23T23:50:00Z')
        self.assertEqual(p['recorded_at'], p['completed_at']); self.assertEqual(p['source_local_date'], '2026-10-23')
        self.assertEqual(p['timezone'], 'UTC'); self.assertIs(free_activity_instant(p).tzinfo, timezone.utc)
        self.assertEqual(list(db.iterdump()), before)

    def test_partial_latest_touch_ignores_first_mark_clock(self):
        db, at = self.fixture()
        db.execute("UPDATE progressor_free_sessions SET status='active',completed_at=NULL")
        db.execute("UPDATE session_exercises SET done_at='2026-10-23T00:00:00Z'")
        p = self.workout(db)
        self.assertEqual(p['completed_at'], canonical_clock(at.timestamp()))
        self.assertFalse(p['session_complete']); self.assertIsNotNone(free_activity_instant(p))

    def test_missing_proof_does_not_redate_or_infer_touch(self):
        db, at = self.fixture(); db.execute('DELETE FROM progressor_free_activity_proof')
        p = self.workout(db)
        self.assertEqual(p['completed_at'], canonical_clock(at.timestamp()))
        self.assertNotIn('timezone', p); self.assertEqual(p['activity_time_basis'], 'recorded_only')
        self.assertIsNone(free_activity_instant(p)); self.assertEqual(recorded_activity_at(p), p['completed_at'])

    def test_ledger_alone_proves_zone_not_action_kind(self):
        db, at = self.fixture(); db.execute('DELETE FROM progressor_free_activity_proof')
        db.execute('CREATE TABLE progressor_timezone_history(user_id TEXT,changed_at REAL,before_zone TEXT,after_zone TEXT)')
        db.executemany('INSERT INTO progressor_timezone_history VALUES(?,?,?,?)', [('123',at.timestamp()-100,'Europe/London','UTC'),('123',at.timestamp()+100,'UTC','Asia/Bangkok')])
        p = self.workout(db)
        self.assertEqual(p['timezone'], 'UTC'); self.assertEqual(p['activity_day_basis'], 'owner_transition_ledger')
        self.assertIsNone(free_activity_instant(p))

    def test_unbounded_prefix_and_equal_microsecond_transition_unknown(self):
        for delta in (-100, 0):
            with self.subTest(delta=delta):
                db, at = self.fixture(); db.execute('DELETE FROM progressor_free_activity_proof')
                db.execute('CREATE TABLE progressor_timezone_history(user_id TEXT,changed_at REAL,before_zone TEXT,after_zone TEXT)')
                db.execute('INSERT INTO progressor_timezone_history VALUES(?,?,?,?)',('123',at.timestamp()-delta,'UTC','Asia/Bangkok'))
                self.assertNotIn('timezone', self.workout(db))

    def test_mismatched_proof_and_finish_serialization_reject_timing(self):
        for sql in ("UPDATE progressor_free_activity_proof SET last_activity=last_activity+1", "UPDATE progressor_free_activity_proof SET source_local_date='2026-10-22'", "UPDATE progressor_free_activity_proof SET activity_timezone=''", "UPDATE progressor_free_activity_proof SET clock_kind='finish'", "UPDATE progressor_free_activity_proof SET proof_version=2", "UPDATE progressor_free_sessions SET completed_at='2026-10-23T23:50:00Z'"):
            with self.subTest(sql=sql):
                db, _ = self.fixture(); db.execute(sql); self.assertIsNone(free_activity_instant(self.workout(db)))

    def test_no_state_finish_marks_are_only_recorded(self):
        db, _ = self.fixture(); db.execute('DELETE FROM progressor_free_sessions'); db.execute('DELETE FROM progressor_free_activity_proof')
        p = self.workout(db)
        self.assertEqual(p['recorded_at'], '2026-10-23T23:50:00Z'); self.assertEqual(p['activity_time_basis'], 'recorded_only')
        self.assertIsNone(recorded_activity_at(p)); self.assertIsNone(free_activity_instant(p))

    def test_no_native_clock_keeps_calendar_envelope_explicitly_unknown(self):
        db, _ = self.fixture(); db.execute('DELETE FROM progressor_free_sessions'); db.execute('UPDATE session_exercises SET done_at=NULL')
        p = self.workout(db)
        self.assertIsNone(p['recorded_at']); self.assertEqual(p['activity_time_basis'], 'not_recorded')
        self.assertEqual(p['timestamp_basis'], 'session_local_day'); self.assertIsNone(recorded_activity_at(p))

    def test_malformed_optional_sidecar_does_not_drop_saved_history(self):
        db, _ = self.fixture(); db.execute('DROP TABLE progressor_free_activity_proof'); db.execute('CREATE TABLE progressor_free_activity_proof(x TEXT)')
        p = self.workout(db); self.assertEqual(p['completed_at'], '2026-10-23T23:50:00Z'); self.assertIsNone(free_activity_instant(p))
        db, at = self.fixture(); db.execute('DROP TABLE progressor_free_activity_proof')
        db.execute('CREATE TABLE progressor_free_activity_proof(session_id INTEGER,last_activity REAL,source_local_date TEXT,activity_timezone TEXT,proof_version INTEGER,clock_kind TEXT)')
        db.executemany("INSERT INTO progressor_free_activity_proof VALUES(1,?,'2026-10-23','UTC',1,'native_touch')",[(at.timestamp(),),(at.timestamp(),)])
        self.assertIsNone(free_activity_instant(self.workout(db)))


class KnownSelectors(unittest.TestCase):
    def test_native_offset_grammar_is_shared_by_proof_and_ledger(self):
        for name in ('UTC+14:00','UTC-03:30','UTC','GMT','Asia/Bangkok'):
            with self.subTest(name=name):
                at = NOW - timedelta(hours=1)
                p = payload(at)
                day = at.astimezone(_calendar_zone(name)).date().isoformat()
                p.update(timezone=name,source_local_date=day)
                p['activity_clock'].update(activity_timezone=name,source_local_date=day)
                self.assertEqual(free_activity_instant(p),at)
        for name in ('UTC+14:01','UTC-15:00','UTC+02:60','GMT+03:00','+03:00'):
            with self.subTest(name=name):
                with self.assertRaises((ValueError,KeyError)):
                    _calendar_zone(name)
                p = payload();p['timezone']=name;p['activity_clock']['activity_timezone']=name
                self.assertIsNone(free_activity_instant(p))

    def test_optional_wire_metadata_is_validated_without_breaking_old_envelopes(self):
        p = payload();p['strength_metrics']=None
        validate_payload('workout.completed',p)
        old = copy.deepcopy(p)
        for key in ('activity_clock','activity_time_basis','activity_day_basis'):
            old.pop(key)
        validate_payload('workout.completed',old)
        for mutate in (
            lambda p:p['activity_clock'].update(version=2),
            lambda p:p.update(day_index=False),
            lambda p:p.update(timestamp_basis='session_local_day'),
            lambda p:p['activity_clock'].update(activity_at=None),
        ):
            bad=copy.deepcopy(p);mutate(bad)
            with self.assertRaises(ValueError):validate_payload('workout.completed',bad)
        unknown=copy.deepcopy(p)
        unknown.update(backfilled=True,activity_time_basis='recorded_only',activity_day_basis='not_recorded')
        unknown.pop('timezone')
        unknown['activity_clock'].update(clock_kind='recorded_only',activity_timezone=None)
        validate_payload('workout.completed',unknown)
        unknown['source_local_date']='20261027';unknown['activity_clock']['source_local_date']='20261027'
        with self.assertRaises(ValueError):validate_payload('workout.completed',unknown)

    def test_daily_unknown_empty_view_explains_known_time_coverage(self):
        from progressor_core.daily_overview import daily_overview
        unknown=payload();unknown.pop('activity_clock')
        store=types.SimpleNamespace(daily_snapshot=lambda *a:(([event(unknown)],[],{}),[]))
        health={'items':[{'source':'gym','status':'ready'}]}
        with patch('progressor_core.daily_overview.preferences',return_value={}),patch('progressor_core.daily_overview.connection_health',return_value=health):
            value=daily_overview(store,'123',NOW)
        section=value['sections'][0]
        self.assertEqual(section['recorded_sessions'],0)
        self.assertIn('известным временем',section['text'])
        self.assertNotIn('тренировочных записей пока нет',section['text'])
        self.assertEqual(section['time_coverage'],TIME_COVERAGE)

    def test_existing_rendered_day_and_week_coverage_is_visible_only_with_gym_permission(self):
        from progressor_core.connections import weekly_overview
        from progressor_core.daily_overview import daily_overview
        for permitted in (True,False):
            with self.subTest(permitted=permitted):
                context={'nutrition':None,'activity':None,'supply':None,'sources':{},'memberships':['gym'] if permitted else []}
                with patch('progressor_core.context.build_context',return_value=context),patch('progressor_core.connections.permitted_entities',return_value=([],[],{})):
                    weekly=weekly_overview(types.SimpleNamespace(),'123',NOW)
                self.assertEqual(TIME_COVERAGE in weekly['coverage'],permitted)
                self.assertEqual(weekly['workouts'] is not None,permitted)
                store=types.SimpleNamespace(daily_snapshot=lambda *a:(([],[],{}),[]))
                health={'items':[{'source':'gym','status':'ready' if permitted else 'disabled'}]}
                with patch('progressor_core.daily_overview.preferences',return_value={}),patch('progressor_core.daily_overview.connection_health',return_value=health):
                    daily=daily_overview(store,'123',NOW)
                self.assertEqual(TIME_COVERAGE in daily['coverage'],permitted)
                self.assertEqual(bool(daily['sections']),permitted)

    def test_ai_compact_summary_retains_proof_provenance_without_exercise_vectors(self):
        p=payload();p['strength_metrics']={'working_sets':1,'repetitions':10,'external_volume_kg':100,
            'exercises':{'7':{'hold_seconds':15}}}
        rows=[event(p)]
        store=types.SimpleNamespace(context_snapshot=lambda *a,**kw:((rows,[],{}),{}))
        context={'access':{'domains':{'food':True}},'memberships':['food','gym'],
            'sources':{'gym':{'status':'ok','last_success':1}},'activity':{'workouts':[],'uncertainty':'owned recorded scope'}}
        with patch('progressor_core.ai_context.build_context',return_value=context),patch('progressor_core.connections.preferences',return_value={'revision':1}):
            value=build_ai_context(store,'123','food',NOW)
        compact=value['data']['gym']['completed_workouts_14_days']
        self.assertEqual(len(compact),1)
        self.assertEqual({k:compact[0][k] for k in ('activity_time_basis','activity_day_basis','timezone')},
            {'activity_time_basis':'source_last_activity','activity_day_basis':'owner_validated_session_day','timezone':'UTC'})
        self.assertEqual(value['data']['gym']['time_coverage'],TIME_COVERAGE)
        self.assertNotIn('exercises',compact[0]['strength_metrics'])
        self.assertEqual(compact[0]['strength_metrics']['hold_seconds'],15)

    def test_strict_proof_fields_not_boolean_shortcut(self):
        p = payload(); self.assertIsNotNone(free_activity_instant(p))
        for field, value in [('session_id',True),('day_index',False),('backfilled',True),('activity_time_basis','recorded_only'),('activity_day_basis','owner_transition_ledger'),('completed_at','2026-10-27T12:00:00Z')]:
            with self.subTest(field=field):
                bad=copy.deepcopy(p);bad[field]=value;self.assertIsNone(free_activity_instant(bad))
        for raw in (True,-1,float('inf'),float('nan')):
            bad=copy.deepcopy(p);bad['activity_clock']['source_last_activity']=raw;self.assertIsNone(free_activity_instant(bad))

    def test_only_exact_numeric_programmed_legacy_exemption(self):
        for identity in ('workout:1','workout:923'):
            p=payload();p.pop('activity_clock');p['entity_id']=identity
            self.assertTrue(known_workout(event(p)))
        for identity in ('workout:01','workout:0','workout:-1','workout:١','workout:explicit','workout:session:01','workout:session:1x'):
            p=payload();p['entity_id']=identity;self.assertFalse(known_workout(event(p)))

    def test_shared_ai_window_excludes_unknown_partial_future_and_is_bounded(self):
        rows=[event(payload(NOW-timedelta(hours=i),session=i)) for i in range(1,26)]
        rows += [event(payload(NOW+timedelta(seconds=1),session=30)),event(payload(complete=False,session=31))]
        unknown=payload(session=32);unknown.pop('activity_clock');rows.append(event(unknown))
        old=payload(NOW-timedelta(days=15),session=33);rows.append(event(old))
        selected=completed_window(rows,NOW)
        self.assertEqual(len(selected),20);self.assertEqual({e['payload']['session_id'] for e in selected},set(range(1,21)))

    def test_ai_enrichment_and_emission_use_same_shared_ids(self):
        rows=[event(payload(NOW-timedelta(hours=i),session=i)) for i in range(1,25)]
        rows += [event(payload(NOW+timedelta(days=1),session=30)),event(payload(complete=False,session=31))]
        store=types.SimpleNamespace(context_snapshot=lambda *a,**kw:((rows,[],{}),{}))
        context={'access':{'domains':{'food':True}},'memberships':['food','gym'],'sources':{'gym':{'status':'ok','last_success':1}},'activity':{'workouts':[],'uncertainty':'synthetic recorded scope'}}
        with patch('progressor_core.ai_context.build_context',return_value=context),patch('progressor_core.connections.preferences',return_value={'revision':1}),patch('progressor_core.ai_context.enrich_workouts',wraps=enrich_workouts) as enrich:
            result=build_ai_context(store,'123','food',NOW)
        ids=enrich.call_args.kwargs['selected_ids'];shown=result['data']['gym']['completed_workouts_14_days']
        self.assertEqual(len(shown),20);self.assertEqual(ids,{e['entity_id'] for e in completed_window(rows,NOW)})
        self.assertEqual({p['completed_at'] for p in shown},{e['payload']['completed_at'] for e in completed_window(rows,NOW)})

    def test_partial_unknown_and_future_do_not_become_load_baselines(self):
        current=event(payload(session=1)); partial=event(payload(NOW-timedelta(days=1),complete=False,session=2))
        unknown=event(payload(NOW-timedelta(days=2),session=3));unknown['payload'].pop('activity_clock')
        future=event(payload(NOW+timedelta(days=1),session=4))
        with patch('progressor_core.native_insights.compare_load',return_value={}) as compare:
            enrich_workouts([current,partial,unknown,future],NOW,selected_ids={current['entity_id']})
        self.assertEqual(compare.call_args.args[1],[])

    def test_journey_requires_known_complete_nonfuture_record(self):
        base={'sources':{'food':{'status':'ok'}},'nutrition':{'today':{}}}
        for p in (payload(complete=False),payload(NOW+timedelta(seconds=1))):
            result=workout_follow_up({**base,'activity':{'workouts':[p]}},NOW)
            self.assertNotEqual(result,'food_review_available')
        unknown=payload();unknown.pop('activity_clock')
        self.assertEqual(workout_follow_up({**base,'activity':{'workouts':[unknown]}},NOW),'no_completed_workout')
        self.assertEqual(workout_follow_up({**base,'activity':{'workouts':[payload()]}},NOW),'food_review_available')


class CandidateAdmissionBoundary(unittest.TestCase):
    """Real candidate plus mocked admission dependency; writer integration separate."""
    def call(self, records, *, admitted=True, patch_context=None, patch_policy=None, seen=False, connection_error=None, patch_native=None):
        p={'rest_active':False,'notifications':True,'hints':True,'frequency':'normal','weight_notifications':False,'last_pause_started_at':0}
        p.update(patch_policy or {})
        c={'activity':{'workouts':records},'access':{'domains':{'food':True}},'memberships':['food','gym'],
           'sources':{'food':{'status':'ok'}},'hints':[{'key':'workout_today.v1','delivery_key':'workout_today.v1:2026-10-27','targets':['food','gym']}],
           'workout_follow_up':'food_review_available','nutrition':{'today':{},'targets':None}}
        c.update(patch_context or {})
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        def connection():
            if connection_error is not None:raise connection_error
            return nullcontext(db)
        store=types.SimpleNamespace(connection=connection,hints_dismissed=lambda *a:False,hint_was_seen=lambda *a:seen)
        calls=[]
        def allowed(*args,**kwargs):calls.append((args,kwargs));return admitted
        stub=types.SimpleNamespace(allowed=allowed)
        with patch.dict(sys.modules,{'progressor_core.free_workout_notifications':stub}),patch('progressor_core.connections.preferences',return_value=p),patch('progressor_core.notifications.build_context',return_value=c),patch('progressor_core.weekly_plan.notification',return_value=None):
            result=candidate(store,'123',{'workout_enabled':True,'timezone':'UTC','enabled_at':0,**(patch_native or {})},NOW)
        return result,calls

    def test_sqlite_connection_open_error_suppresses_only_free_path(self):
        error=sqlite3.OperationalError('owned synthetic connection-open failure')
        result,calls=self.call([payload()],connection_error=error)
        self.assertIsNone(result);self.assertEqual(calls,[])
        programmed=payload();programmed['entity_id']='workout:17';programmed.pop('activity_clock')
        result,calls=self.call([payload(),programmed],connection_error=error)
        self.assertEqual(result['kind'],'post_workout');self.assertEqual(calls,[])
        nutrient={'key':'food_sources_iron.v1','delivery_key':'food_sources_iron.v1:2026-10-27','targets':['food'],
            'title':'Owned nutrient control','message':'Recorded food control'}
        result,calls=self.call([payload()],connection_error=error,patch_context={'hints':[nutrient]},patch_native={'nutrient_enabled':True})
        self.assertEqual(result['kind'],'nutrient_review');self.assertEqual(calls,[])
        with self.assertRaises(TypeError):
            self.call([payload()],connection_error=TypeError('programming error control'))

    def test_free_needs_terminal_admission_and_scalar_current_time(self):
        result,calls=self.call([payload()]);self.assertEqual(result['kind'],'post_workout')
        self.assertEqual(calls[0][1]['now'],NOW.timestamp())
        self.assertIsNone(self.call([payload()],admitted=False)[0])

    def test_numeric_programmed_does_not_require_free_admission(self):
        p=payload();p['entity_id']='workout:17';p.pop('activity_clock')
        result,calls=self.call([p],admitted=False)
        self.assertEqual(result['kind'],'post_workout');self.assertEqual(calls,[])

    def test_partial_seen_rest_pause_and_meal_guards_still_win(self):
        self.assertIsNone(self.call([payload(complete=False)])[0])
        self.assertIsNone(self.call([payload()],seen=True)[0])
        self.assertIsNone(self.call([payload()],patch_policy={'rest_active':True})[0])
        self.assertIsNone(self.call([payload()],patch_policy={'last_pause_started_at':NOW.timestamp()})[0])
        self.assertIsNone(self.call([payload()],patch_context={'workout_follow_up':'food_recorded_after_workout'})[0])

    def test_unknown_malformed_and_future_free_never_trigger(self):
        for p in (payload(NOW+timedelta(seconds=1)),payload(NOW-timedelta(hours=3))):
            self.assertIsNone(self.call([p])[0])
        p=payload();p.pop('activity_clock');result,calls=self.call([p]);self.assertIsNone(result);self.assertEqual(calls,[])


if __name__ == '__main__':
    unittest.main()
