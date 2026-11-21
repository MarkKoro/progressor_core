"""Explicit, own-account plan review is separate from recorded native activity."""
import concurrent.futures
import gc
import json
import math
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from test_integration import fixture, USER, OTHER, KEY, TOKENS
from progressor_core.app import Config, create_app
from progressor_core.auth import sign_assertion
from progressor_core.connection_changes import recent
from progressor_core.connections import preferences, save_preferences
from progressor_core.store import Store


class HintReviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        root = Path(self.tmp.name)
        paths = fixture(root)
        self.now = datetime.now(timezone.utc)
        with sqlite3.connect(paths['supply']) as db:
            db.execute('CREATE TABLE user_health_profile(user_id INTEGER PRIMARY KEY,weight_kg REAL,height_cm REAL,created_at_utc TEXT,updated_at_utc TEXT,sex_at_birth TEXT,birth_year INTEGER,diet_type TEXT,training_sessions_per_week INTEGER,training_minutes_per_week INTEGER)')
            db.execute('INSERT INTO user_health_profile(user_id,weight_kg,height_cm,created_at_utc,updated_at_utc) VALUES(55,79,180,?,?)',
                       (self.now.isoformat(), self.now.isoformat()))
        self.config = Config(str(root / 'core.sqlite3'), KEY, paths, TOKENS, background=False)
        self.client = TestClient(create_app(self.config))
        self.client.__enter__()
        self.client.app.state.engine.poll()
        self.store = self.client.app.state.engine.store
        self.goal()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        gc.collect()
        self.tmp.cleanup()

    def headers(self, user=USER, audience='core', expired=False):
        stamp = int(time.time()) - (1000 if expired else 0)
        return {'X-Progressor-Auth': sign_assertion({'id': user}, stamp, audience, KEY, now=stamp)}

    def event(self, source, ident, kind, payload, stamp=None):
        with self.store.connection() as db:
            row = db.execute('SELECT revision FROM entities WHERE source=? AND entity_id=?',
                             (source, ident)).fetchone()
        event = {'event_id': str(uuid.uuid4()), 'event_type': kind, 'schema_version': 1,
                 'source': source, 'user_id': str(USER),
                 'occurred_at': (stamp or datetime.now(timezone.utc)).isoformat(),
                 'correlation_id': 'isolated-explicit-review',
                 'payload': {**payload, 'entity_id': ident, 'revision': row[0] + 1 if row else 1}}
        self.store.accept(event)
        return event

    def goal(self, kcal=1900):
        return self.event('food', 'target:' + str(USER), 'nutrition_target.changed',
                          {'targets': {'kcal': kcal, 'protein': 100, 'fat': 70, 'carbs': 200}})

    def pref(self, **patch):
        if 'sources' in patch:
            patch['sources'] = {**preferences(self.store, str(USER))['sources'], **patch['sources']}
        return save_preferences(self.store, str(USER), patch,
                                preferences(self.store, str(USER))['revision'])

    def context(self, target='gym'):
        response = self.client.get('/api/v1/me/context', params={'target': target}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def change(self, target='gym', kind='change_goal.v1'):
        return next(h for h in self.context(target)['hints'] if h['key'] == kind)

    def review(self, hint, target='gym', **kwargs):
        return self.client.post('/api/v1/me/hints/reviewed',
                                json={'target': target, 'delivery_key': hint['delivery_key']},
                                headers=kwargs.get('headers', self.headers()))

    def receipts(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM hint_reviews')]

    def profile(self, source, **patch):
        with self.store.connection() as db:
            row = db.execute("SELECT entity_id,payload FROM entities WHERE user_id=? AND source=? AND entity_id GLOB 'profile:*' AND json_extract(payload,'$.profile_kind') IS NULL",
                             (str(USER), source)).fetchone()
        return self.event(source, row['entity_id'], 'profile.updated', {**json.loads(row['payload']), **patch})

    def test_get_seen_workout_and_intake_are_not_review_receipts(self):
        hint = self.change()
        self.assertTrue(hint['reviewable'])
        self.assertEqual(self.receipts(), [])
        self.client.post('/api/v1/me/hints/seen', json={'target': 'gym', 'delivery_key': hint['delivery_key']}, headers=self.headers())
        stamp = datetime.now(timezone.utc)
        self.event('gym', 'workout:after-goal', 'workout.completed',
                   {'completed_at': stamp.isoformat(), 'source_local_date': stamp.date().isoformat(),
                    'timezone': 'UTC', 'workout_type': 'strength', 'duration_seconds': None,
                    'strength_sets': 3, 'session_complete': True}, stamp)
        self.event('supply', 'intake:after-goal', 'supplement.taken',
                   {'source_local_date': stamp.date().isoformat(), 'timezone': 'UTC', 'status': 'taken', 'supplement_id': '5'}, stamp)
        for target in ('gym', 'supply'):
            self.assertEqual(self.change(target)['delivery_key'], hint['delivery_key'])
        self.assertEqual(self.receipts(), [])

    def test_explicit_review_persists_on_reload_and_only_exact_target_and_change(self):
        hint = self.change()
        with self.store.connection() as db:
            before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        result = self.review(hint)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['delivery_key'], hint['delivery_key'])
        self.assertTrue(result.json()['reviewed'])
        self.assertGreater(result.json()['reviewed_at'], 0)
        self.assertTrue(math.isfinite(result.json()['reviewed_at']))
        self.assertFalse(any(h['delivery_key'] == hint['delivery_key'] for h in self.context()['hints']))
        self.assertEqual(self.change('supply')['delivery_key'], hint['delivery_key'])
        reloaded = Store(self.config.db_path)
        self.assertEqual(reloaded.reviewed_hint_keys(str(USER), 'gym'), {hint['delivery_key']})
        self.assertEqual(reloaded.reviewed_hint_keys(str(OTHER), 'gym'), set())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], before)
        self.goal(1800)
        newer = self.change()
        self.assertNotEqual(newer['delivery_key'], hint['delivery_key'])
        self.assertEqual(self.review(hint).status_code, 422)
        self.assertEqual(self.change()['delivery_key'], newer['delivery_key'])

    def test_response_lost_and_concurrent_double_click_keep_one_receipt_and_time(self):
        hint = self.change()
        first = self.review(hint).json()  # Server committed; caller may lose this response.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.review(hint), range(2)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertTrue(all(r.json() == first for r in results))
        self.assertEqual(len(self.receipts()), 1)

    def test_concurrent_initial_double_click_creates_one_receipt(self):
        hint = self.change()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.review(hint), range(2)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(len(self.receipts()), 1)

    def test_duplicate_store_receipt_executes_no_mutation(self):
        hint = self.change()
        original = self.review(hint).json()['reviewed_at']
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            changes = db.total_changes
            self.assertEqual(self.store.mark_hint_reviewed(str(USER), 'gym', hint['delivery_key'], db=db), original)
            self.assertEqual(db.total_changes, changes)

    def test_auth_other_account_and_wrong_target_cannot_confirm(self):
        hint = self.change()
        url = '/api/v1/me/hints/reviewed'
        body = {'target': 'gym', 'delivery_key': hint['delivery_key']}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        for headers in (self.headers(audience='gym'), self.headers(expired=True), {'X-Progressor-Auth': 'invalid'}):
            self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 401)
        self.assertEqual(self.review(hint, headers=self.headers(OTHER)).status_code, 422)
        self.assertEqual(self.review(hint, target='food').status_code, 422)
        self.assertEqual(self.receipts(), [])

    def test_body_is_bounded_and_rejects_injected_owner_and_non_string_keys(self):
        hint = self.change()
        url = '/api/v1/me/hints/reviewed'
        for body in (None, [], {}, {'target': 'gym'}, {'target': [], 'delivery_key': 'x'},
                     {'target': 'gym', 'delivery_key': []}, {'target': 'gym', 'delivery_key': 'x' * 161},
                     {'target': 'gym', 'delivery_key': hint['delivery_key'], 'user_id': str(OTHER)}):
            self.assertEqual(self.client.post(url, json=body, headers=self.headers()).status_code, 422)
        self.assertEqual(self.client.post(url, content='x' * 513, headers=self.headers()).status_code, 413)
        self.assertEqual(self.receipts(), [])

    def test_non_reviewable_real_native_hint_cannot_be_confirmed(self):
        stamp = datetime.now(timezone.utc)
        self.event('gym', 'workout:980001', 'workout.completed',
                   {'completed_at': stamp.isoformat(), 'source_local_date': stamp.date().isoformat(),
                    'timezone': 'UTC', 'workout_type': 'strength', 'duration_seconds': None,
                    'strength_sets': 3, 'session_complete': True}, stamp)
        hint = next(h for h in self.context('food')['hints'] if h['key'] == 'workout_today.v1')
        self.assertFalse(hint.get('reviewable', False))
        self.assertEqual(self.review(hint, 'food').status_code, 422)
        self.assertEqual(self.receipts(), [])

    def test_rest_opt_out_and_disabled_source_or_target_revalidate_open_hint(self):
        hint = self.change()
        for patch in ({'paused': True}, {'hints': False}, {'goal_links': False},
                      {'sources': {'food': False}}, {'sources': {'gym': False}}):
            with self.subTest(patch=patch):
                self.pref(**patch)
                self.assertEqual(self.review(hint).status_code, 422)
                self.pref(paused=False, hints=True, goal_links=True,
                          sources={'food': True, 'gym': True, 'supply': True})
        self.config.enabled_domains = ('food', 'supply')
        self.assertEqual(self.review(hint).status_code, 422)
        self.config.enabled_domains = ('gym', 'supply')
        self.assertFalse(any(h['key'] == 'change_goal.v1' for h in self.context()['hints']))
        self.assertEqual(self.review(hint).status_code, 422)
        self.config.enabled_domains = ('gym', 'food', 'supply')
        self.store.enabled_sources = {'gym', 'supply'}
        self.assertEqual(self.review(hint).status_code, 422)
        self.assertEqual(self.receipts(), [])

    def test_stale_and_expired_source_or_target_revalidate_open_hint(self):
        hint = self.change()
        for source in ('food', 'gym'):
            with self.subTest(source=source):
                with self.store.connection() as db:
                    db.execute('UPDATE source_state SET last_success=? WHERE source=?', (time.time() - 300, source))
                self.assertEqual(self.review(hint).status_code, 422)
                with self.store.connection() as db:
                    db.execute('UPDATE source_state SET last_success=? WHERE source=?', (time.time(), source))
                self.profile(source, paid_until='2000-01-01T00:00:00Z')
                self.assertEqual(self.review(hint).status_code, 422)
                self.profile(source, paid_until='2030-01-01T00:00:00Z')
        self.assertEqual(self.receipts(), [])

    def test_supply_consent_rechecked_for_both_target_and_weight_source(self):
        hint = self.change('supply')
        self.profile('supply', consent_given=False)
        self.assertFalse(any(h['key'] == 'change_goal.v1' for h in self.context('supply')['hints']))
        self.assertEqual(self.review(hint, 'supply').status_code, 422)
        self.profile('supply', consent_given=True)
        self.pref(weight_notifications=True)
        self.event('supply', 'profile:health:55', 'profile.updated',
                   {'profile_kind': 'reported_health', 'reported_profile': {'weight_kg': 78, 'height_cm': 180}})
        weight = self.change('food', 'change_weight.v1')
        self.assertEqual(weight['action'], {'kind': 'food_goal', 'label': 'Проверить цель питания'})
        self.profile('supply', consent_given=False)
        self.assertEqual(self.review(weight, 'food').status_code, 422)
        self.assertEqual(self.receipts(), [])

    def test_deleted_or_aged_source_change_is_not_reviewable(self):
        hint = self.change()
        with self.store.connection() as db:
            db.execute('UPDATE connection_changes SET observed_at=?', (time.time() - 3 * 86400,))
        self.assertEqual(self.review(hint).status_code, 422)
        self.goal(1800)
        hint = self.change()
        self.event('food', 'target:' + str(USER), 'entity.deleted', {'deleted': True})
        self.assertEqual(self.review(hint).status_code, 422)
        self.assertFalse(any(h['key'] == 'change_goal.v1' for h in self.context()['hints']))

    def test_recent_change_precision_tolerance_does_not_include_future_changes(self):
        now = datetime.now(timezone.utc)
        with self.store.connection() as db:
            db.execute('UPDATE connection_changes SET observed_at=?', (now.timestamp() + .0000005,))
        self.assertTrue(recent(self.store, str(USER), now)['items'])
        with self.store.connection() as db:
            db.execute('UPDATE connection_changes SET observed_at=?', (now.timestamp() + 1,))
        self.assertFalse(recent(self.store, str(USER), now)['items'])

    def test_new_source_revision_and_rejected_replay_preserve_original_receipt(self):
        hint = self.change()
        original = self.review(hint).json()
        # Even a new revision with unchanged goal values invalidates the old
        # event lineage. It does not manufacture another goal-change trigger.
        self.goal()
        self.assertEqual(self.review(hint).status_code, 422)
        self.assertFalse(any(h['key'] == 'change_goal.v1' for h in self.context()['hints']))
        self.assertEqual(self.receipts()[0]['reviewed_at'], original['reviewed_at'])

    def test_existing_receipt_cannot_bypass_revoked_consent_rest_or_staleness(self):
        hint = self.change('supply')
        original = self.review(hint, 'supply').json()
        self.profile('supply', consent_given=False)
        self.assertEqual(self.review(hint, 'supply').status_code, 422)
        self.profile('supply', consent_given=True)
        self.pref(paused=True)
        self.assertEqual(self.review(hint, 'supply').status_code, 422)
        self.pref(paused=False)
        with self.store.connection() as db:
            db.execute('UPDATE source_state SET last_success=? WHERE source=?', (time.time() - 300, 'food'))
        self.assertEqual(self.review(hint, 'supply').status_code, 422)
        self.assertEqual(len(self.receipts()), 1)
        self.assertEqual(self.receipts()[0]['reviewed_at'], original['reviewed_at'])

    def test_explicit_weight_review_and_actual_goal_edit_are_separate_valid_outcomes(self):
        self.pref(weight_notifications=True)
        def weight(value):
            self.event('supply', 'profile:health:55', 'profile.updated',
                       {'profile_kind': 'reported_health', 'reported_profile': {'weight_kg': value, 'height_cm': 180}})
            return self.change('food', 'change_weight.v1')
        first = weight(78)
        self.assertEqual(self.review(first, 'food').status_code, 200)
        self.assertFalse(any(h['key'] == 'change_weight.v1' for h in self.context('food')['hints']))
        second = weight(77)
        self.assertNotEqual(first['delivery_key'], second['delivery_key'])
        self.goal(1800)
        self.assertFalse(any(h['key'] == 'change_weight.v1' for h in self.context('food')['hints']))
        self.assertEqual(self.review(second, 'food').status_code, 422)
        self.assertEqual(len(self.receipts()), 1)

    def test_cleanup_is_write_only_bounded_to_90_days_and_leaves_other_records(self):
        hint = self.change()
        with self.store.connection() as db:
            db.execute('INSERT INTO hint_reviews VALUES(?,?,?,?)', (str(USER), 'food', 'old', time.time() - 91 * 86400))
            db.execute('INSERT INTO hint_reviews VALUES(?,?,?,?)', (str(OTHER), 'food', 'recent', time.time()))
        self.context()
        self.assertEqual(len(self.receipts()), 2)
        self.assertEqual(self.review(hint).status_code, 200)
        rows = self.receipts()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['delivery_key'] for r in rows}, {'recent', hint['delivery_key']})

