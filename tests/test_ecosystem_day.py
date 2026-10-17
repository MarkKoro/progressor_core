"""Factual journeys, source health, permission boundaries and notification completion."""
import copy
import gc
import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_integration import fixture, USER, OTHER, NOW, KEY, TOKENS
from progressor_core.adapters import snapshot
from progressor_core.app import Config, create_app
from progressor_core.auth import sign_assertion
from progressor_core.context import build_context
from progressor_core.connections import preferences, save_preferences
from progressor_core.contracts import validate_payload
from progressor_core.daily_overview import daily_overview, connection_health
from progressor_core.notifications import candidate
from progressor_core.store import Store
from shared.progressor_client import canonical, control_token


class EcosystemDay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.root = Path(self.tmp.name)
        self.paths = fixture(self.root)
        self.store = Store(self.root / 'core.sqlite3')
        self.uid = str(USER)
        self.sync()
        self.workout()
        self.prefs = {'workout_enabled': True, 'nutrient_enabled': False, 'timezone': 'Europe/Moscow',
                      'enabled_at': (NOW - timedelta(hours=3)).timestamp()}

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def sync(self):
        for source, path in self.paths.items(): self.store.reconcile(source, snapshot(source, path))

    def workout(self, complete=True, at=None):
        row = next(e for e in self.store.data(self.uid)[0] if e['entity_id'].startswith('workout:'))
        payload = {**row['payload'], 'revision': row['revision'] + 1,
                   'session_complete': complete, 'completed_at': (at or NOW - timedelta(hours=1)).isoformat()}
        self.store.accept({'event_id': uuid.uuid4().hex, 'event_type': 'workout.updated', 'source': 'gym',
                          'user_id': self.uid, 'schema_version': 1, 'occurred_at': payload['completed_at'],
                          'correlation_id': 'test', 'payload': payload})

    def meal(self, at=None, day=None):
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('INSERT INTO meals VALUES(10,?,?,500,20,10,70,?,0)',
                       (USER, day or NOW.date().isoformat(), (at or NOW - timedelta(minutes=10)).isoformat()))
        self.store.reconcile('food', snapshot('food', self.paths['food']))

    def change(self, **patches):
        p = preferences(self.store, self.uid)
        return save_preferences(self.store, self.uid, patches, p['revision'])

    def context(self): return build_context(self.store, self.uid, NOW, target='food')
    def day(self, target='food'): return daily_overview(self.store, self.uid, NOW, target=target)
    def notify(self): return candidate(self.store, self.uid, self.prefs, NOW)

    def test_post_workout_meal_completes_journey_and_stops_only_obsolete_hint(self):
        self.assertEqual(self.notify()['kind'], 'post_workout')
        self.meal()
        c = self.context()
        self.assertEqual(c['workout_follow_up'], 'food_recorded_after_workout')
        self.assertFalse(any(h['key'] == 'workout_today.v1' for h in c['hints']))
        self.assertIsNone(self.notify())
        self.assertEqual(c['nutrition']['targets']['kcal'], 2200)
        self.assertIn('уже записали еду', self.day()['relationship'])

    def test_meal_before_workout_future_or_wrong_diary_day_does_not_complete_journey(self):
        for at, day in [(NOW - timedelta(hours=2), None), (NOW + timedelta(hours=1), None),
                        (NOW - timedelta(minutes=5), (NOW - timedelta(days=1)).date().isoformat())]:
            self.meal(at, day)
            self.assertEqual(self.context()['workout_follow_up'], 'food_review_available')
            self.assertIsNotNone(self.notify())
            with sqlite3.connect(self.paths['food']) as db: db.execute('DELETE FROM meals WHERE id=10')
            self.store.reconcile('food', snapshot('food', self.paths['food']))

    def test_edit_and_delete_recompute_latest_source_fact_without_extra_domain_writes(self):
        self.meal()
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('UPDATE meals SET created_at=?,version=version+1 WHERE id=10', ((NOW - timedelta(hours=2)).isoformat(),))
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.context()['workout_follow_up'], 'food_review_available')
        with sqlite3.connect(self.paths['food']) as db: db.execute('DELETE FROM meals WHERE id=10')
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertIsNone(self.context()['nutrition']['today']['latest_meal_at'])
        self.assertIsNone(self.day()['sections'][1]['totals'])

    def test_unfinished_workout_does_not_trigger_post_workout_card_or_notification(self):
        self.workout(False)
        self.assertEqual(self.context()['workout_follow_up'], 'training_in_progress')
        self.assertFalse(any(h['key'] == 'workout_today.v1' for h in self.context()['hints']))
        self.assertIsNone(self.notify())
        gym = next(r for r in self.day()['sections'] if r['source'] == 'gym')
        self.assertEqual((gym['recorded_sessions'], gym['completed_sessions']), (1, 0))

    def test_confirmed_day_stops_reminder_new_meal_reopens_day(self):
        self.meal(NOW - timedelta(hours=2))
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('CREATE TABLE progressor_day_closure(user_id INTEGER,day TEXT,meal_versions TEXT)')
            db.execute('INSERT INTO progressor_day_closure VALUES(?,?,?)', (USER, NOW.date().isoformat(), '[[10,0]]'))
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.context()['workout_follow_up'], 'food_day_confirmed')
        self.assertIsNone(self.notify())
        with sqlite3.connect(self.paths['food']) as db: db.execute('UPDATE meals SET version=1 WHERE id=10')
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.context()['workout_follow_up'], 'food_review_available')

    def test_old_payload_without_timestamp_stays_compatible_and_unknown(self):
        original = next(e for e in self.store.data(self.uid)[0] if e['entity_id'].startswith('daily:'))
        payload = copy.deepcopy(original['payload']); payload.pop('latest_meal_at', None)
        validate_payload('daily_nutrition.updated', payload)
        payload['latest_meal_at'] = '2026-10-07T10:00:00'
        with self.assertRaises(ValueError): validate_payload('daily_nutrition.updated', payload)

    def test_health_explains_source_off_stale_missing_access_and_consent_without_facts(self):
        self.store.failed('gym', 'PRIVATE_INTERNAL_ERROR')
        value = self.day()
        self.assertEqual(next(r for r in value['health']['items'] if r['source'] == 'gym')['status'], 'stale')
        self.assertNotIn('PRIVATE_INTERNAL_ERROR', json.dumps(value))
        self.assertNotIn('gym', [r['source'] for r in value['sections']])
        self.change(sources={'gym': True, 'food': True, 'supply': False})
        self.assertEqual(next(r for r in self.day()['health']['items'] if r['source'] == 'supply')['status'], 'disabled')
        self.change(sources={'gym': True, 'food': True, 'supply': True})
        with sqlite3.connect(self.paths['supply']) as db: db.execute('UPDATE users SET consent_given=0')
        self.store.reconcile('supply', snapshot('supply', self.paths['supply']))
        self.assertEqual(next(r for r in self.day()['health']['items'] if r['source'] == 'supply')['status'], 'consent_required')
        self.assertNotIn('supply', [r['source'] for r in self.day()['sections']])
        with sqlite3.connect(self.paths['food']) as db: db.execute('UPDATE users SET is_premium=0')
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.day()['sections'], [])

    def test_pause_hints_off_and_account_missing_do_not_create_zero_health_or_subscription_change(self):
        access = self.context()['access']
        self.change(paused=True)
        self.assertEqual(self.day()['sections'], [])
        self.assertTrue(all(r['status'] == 'paused' for r in self.day()['health']['items']))
        self.assertEqual(self.context()['access'], access)
        self.change(paused=False, hints=False)
        self.assertTrue(self.day()['sections'])
        self.assertFalse(self.day()['health']['hints_enabled'])
        other = connection_health(self.store, str(OTHER), NOW)
        self.assertEqual(next(r for r in other['items'] if r['source'] == 'food')['status'], 'not_connected')

    def test_supply_counts_owned_entire_local_day_beyond_recent_90_without_adherence_inference(self):
        with sqlite3.connect(self.paths['supply']) as db: db.execute("UPDATE users SET tz_name='Pacific/Kiritimati'")
        self.store.reconcile('supply', snapshot('supply', self.paths['supply']))
        source_day = (NOW + timedelta(hours=14)).date().isoformat()
        for i in range(134):
            payload = {'entity_id': f'intake:many:{i}', 'revision': 1, 'status': 'skipped' if i == 132 else 'taken',
                       'source_local_date': source_day, 'timezone': 'Pacific/Kiritimati'}
            self.store.accept({'event_id': f'many-{i}', 'event_type': 'supplement.taken', 'source': 'supply',
                              'user_id': str(OTHER) if i == 133 else self.uid, 'schema_version': 1,
                              'occurred_at': NOW.isoformat(), 'correlation_id': 'test', 'payload': payload})
        supply = next(r for r in self.day()['sections'] if r['source'] == 'supply')
        self.assertEqual((supply['taken_records'], supply['skipped_records']), (132, 1))
        self.assertEqual(supply['day'], source_day)
        self.assertIn('неизвестны', supply['text'])

    def test_daily_reuses_request_projection_and_omits_labs_doses_and_other_journal_rows(self):
        with (patch.object(self.store, 'data', side_effect=AssertionError('full journal read')),
              patch.object(self.store, 'context_snapshot', side_effect=AssertionError('full context calculation')),
              patch.object(self.store, 'daily_snapshot', wraps=self.store.daily_snapshot) as read):
            value = self.day()
        self.assertEqual(read.call_count, 1)
        self.assertNotIn('lab_reports', value)
        self.assertNotIn('reported_dose_text', json.dumps(value))

    def test_inline_food_sources_use_same_diet_and_exclusions_as_atlas(self):
        from progressor_core.native_insights import native_hints
        nutrient=lambda unit,value:{'unit':unit,'observed_days':5,'observed_meals':10,
            'observed_components':10,'assessed_components':10,'average_on_observed_days':value}
        data={'sources':{s:{'status':'ok'} for s in ('food','gym','supply')},'activity':None,
              'supply':{'active_supplements':[]},'nutrition':{'targets':{'protein':100},'history':{'7':{
                  'logged_days':5,'logged_meals':10,'averages_on_logged_days':{'protein':40},'provenance':[],
                  'nutrients':{'iron':nutrient('mg',1),'vitamin_b12':nutrient('ug',.1)}}}}}
        values=native_hints(data,[],NOW,NOW.date(),food_preferences={'diet':'vegan','excluded_food_groups':['soy','nuts']})
        message=' '.join(h['message'] for h in values).lower()
        for unwanted in ('рыба','лосось','яйца','молоко','говядина','тофу','орехи'):self.assertNotIn(unwanted,message)
        b12=next(h for h in values if h['key']=='food_sources_vitamin_b12.v1')
        self.assertIn('подтверждённых пищевых примеров пока нет',b12['message'])
        self.assertTrue(any(h['key']=='logged_protein.v2' for h in values))


class DailyAPI(unittest.TestCase):
    def test_signed_public_identity_and_native_source_bound_target(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR')) as root:
            root = Path(root)
            config = Config(str(root / 'core.db'), KEY, fixture(root), TOKENS, background=False)
            with TestClient(create_app(config)) as client:
                client.app.state.engine.poll()
                headers = {'X-Progressor-Auth': sign_assertion({'id': USER}, int(time.time()), 'core', KEY)}
                path = '/api/v1/me/connections/today?target=food'
                self.assertEqual(client.get(path).status_code, 401)
                self.assertEqual(client.get('/api/v1/me/connections/today?target=invalid', headers=headers).status_code, 422)
                result = client.get(path + '&user_id=' + str(OTHER), headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual({r['source'] for r in result.json()['sections']}, {'gym', 'food', 'supply'})
                private = '/internal/v1/connections/today'
                raw = canonical({'user_id': str(USER), 'target': 'food'}).encode()
                self.assertEqual(client.post(private, content=raw).status_code, 401)
                with patch('progressor_core.daily_overview.daily_overview', return_value={'test': True}) as read:
                    r = client.post(private, content=raw, headers={'X-Progressor-Control': control_token('gym', private, raw, KEY)})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(read.call_args.kwargs['target'], 'gym')
