"""Source journal day and save-time provenance; no consumer/provider calls."""
import copy
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from progressor_core import connections, meal_anchors
from progressor_core.adapters import snapshot
from progressor_core.app import Config, create_app
from shared.progressor_client import control_token
from progressor_core.contracts import canonical
from progressor_core.store import Store
from test_integration import fixture, USER, OTHER, KEY, TOKENS


NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
MOSCOW = ZoneInfo('Europe/Moscow')


class MealRecordedTime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.root = Path(self.tmp.name)
        self.paths = fixture(self.root)
        self.store = Store(self.root / 'core.db')
        self.config = Config(str(self.root / 'http.db'), KEY, self.paths, TOKENS, background=False)
        self.original = None
        for source, path in self.paths.items():
            self.store.reconcile(source, snapshot(source, path))

    def tearDown(self):
        import gc
        gc.collect()
        self.tmp.cleanup()

    def saved(self, day=None, recorded=None):
        recorded = recorded if recorded is not None else NOW.astimezone(MOSCOW).replace(tzinfo=None).isoformat()
        day = day or NOW.astimezone(MOSCOW).date().isoformat()
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('DELETE FROM meal_nutrients')
            db.execute('DELETE FROM meals')
            db.execute('INSERT INTO meals VALUES(1,?,?,500,25,15,70,?,0)', (USER, day, recorded))
        data = snapshot('food', self.paths['food'])
        self.store.reconcile('food', data)
        return next(e for e in data['entities'] if e['entity_id'] == 'meal:1')

    def read(self, now=NOW, people=None):
        return meal_anchors.events(self.store, people or [str(USER)], now)['items']

    def change(self, **values):
        old = connections.preferences(self.store, str(USER))
        return connections.save_preferences(self.store, str(USER), values, old['revision'])

    def test_historical_day_keeps_macros_but_never_becomes_a_current_anchor(self):
        meal = self.saved(day='2026-10-19')
        self.assertEqual(self.read(), [])
        self.assertEqual(meal['payload']['source_local_date'], '2026-10-19')
        daily = next(e for e in snapshot('food', self.paths['food'])['entities'] if e['entity_id'].startswith('daily:'))
        self.assertEqual(daily['payload']['source_local_date'], '2026-10-19')
        self.assertEqual(daily['payload']['totals'], {'kcal':500.0, 'protein':25.0, 'fat':15.0, 'carbs':70.0})

    def test_future_diary_day_is_not_a_current_anchor(self):
        self.saved(day='2026-10-21')
        self.assertEqual(self.read(), [])

    def test_source_provenance_is_save_time_and_never_invented_consumption(self):
        meal = self.saved()
        self.assertEqual(meal['payload']['recorded_at'], '2026-10-20T09:00:00Z')
        self.assertEqual(meal['payload']['recorded_at_basis'], 'legacy_server_timezone')
        self.assertIsNone(meal['payload']['consumed_at'])
        self.assertEqual(meal['payload']['consumed_at_basis'], 'not_reported')
        self.assertEqual(len(self.read()), 1)

    def test_moscow_day_is_used_when_utc_day_differs(self):
        meal = self.saved(day='2026-10-20', recorded='2026-10-20T00:01:00+03:00')
        now = datetime(2026, 10, 19, 21, 3, tzinfo=timezone.utc)
        self.assertEqual(meal['occurred_at'], '2026-10-19T21:01:00Z')
        self.assertEqual(len(self.read(now)), 1)

    def test_normal_late_night_entry_remains_fresh_across_midnight(self):
        self.saved(day='2026-10-19', recorded='2026-10-19T23:59:00+03:00')
        now = datetime(2026, 10, 19, 21, 3, tzinfo=timezone.utc)
        self.assertEqual(len(self.read(now)), 1)

    def test_aware_timestamp_converts_to_food_source_day_not_its_input_offset(self):
        self.saved(day='2026-10-20', recorded='2026-10-20T00:02:00+07:00')
        self.assertEqual(self.read(datetime(2026, 10, 19, 17, 3, tzinfo=timezone.utc)), [])
        self.saved(day='2026-10-19', recorded='2026-10-20T00:02:00+07:00')
        self.assertEqual(len(self.read(datetime(2026, 10, 19, 17, 3, tzinfo=timezone.utc))), 1)

    def test_naive_legacy_time_uses_explicit_adapter_source_timezone(self):
        meal = self.saved(recorded='2026-10-20 12:00:00')
        self.assertEqual(meal['occurred_at'], '2026-10-20T09:00:00Z')
        self.assertEqual(len(self.read()), 1)

    def test_missing_recorded_time_cannot_treat_day_midnight_as_a_fresh_meal(self):
        meal = self.saved(recorded='')
        self.assertIsNone(meal['payload']['recorded_at'])
        self.assertEqual(meal['payload']['recorded_at_basis'], 'missing')
        self.assertEqual(self.read(datetime(2026, 10, 19, 21, 1, tzinfo=timezone.utc)), [])

    def test_exact_ten_minute_boundary_and_future_instants(self):
        self.saved(recorded='2026-10-20T08:50:00Z')
        self.assertEqual(len(self.read()), 1)
        self.assertEqual(self.read(NOW + timedelta(microseconds=1)), [])
        self.saved(recorded='2026-10-20T09:00:01Z')
        self.assertEqual(self.read(), [])

    def test_source_off_rest_and_other_owner_still_have_no_events(self):
        self.saved()
        self.assertEqual(self.read(people=[str(OTHER)]), [])
        self.change(paused=True)
        self.assertEqual(self.read(), [])
        self.change(paused=False, sources={'food':False, 'gym':True, 'supply':True})
        self.assertEqual(self.read(), [])

    def test_stale_source_and_expired_supply_access_still_have_no_events(self):
        self.saved()
        with self.store.connection() as db:
            db.execute("UPDATE source_state SET last_success=? WHERE source='food'", (time.time()-121,))
        self.assertEqual(self.read(), [])
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        with sqlite3.connect(self.paths['supply']) as db:
            db.execute("UPDATE users SET premium_until_utc='2020-01-01T00:00:00Z'")
        self.store.reconcile('supply', snapshot('supply', self.paths['supply']))
        self.assertEqual(self.read(), [])

    def test_delete_and_backdate_edit_do_not_leave_an_old_anchor(self):
        self.saved()
        self.assertEqual(len(self.read()), 1)
        with sqlite3.connect(self.paths['food']) as db:
            db.execute("UPDATE meals SET date='2026-10-19',version=version+1")
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.read(), [])
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('DELETE FROM meals')
        self.store.reconcile('food', snapshot('food', self.paths['food']))
        self.assertEqual(self.read(), [])

    def test_malformed_or_unknown_time_basis_fails_closed_without_breaking_batch(self):
        self.saved()
        rows, members, access = connections.permitted_entities(self.store, str(USER), NOW)
        for changed in ({'recorded_at':'invalid'}, {'recorded_at_basis':'unknown'}, {'timezone':'Unknown/Zone'}, {'timezone':None}, {'recorded_at':None}, {'source_local_date':None}):
            values=copy.deepcopy(rows)
            next(e for e in values if e['entity_id']=='meal:1')['payload'].update(changed)
            with patch.object(meal_anchors, 'permitted_entities', return_value=(values,members,access)):
                self.assertEqual(self.read(), [])

    def test_legacy_adapter_payload_has_same_journal_day_protection(self):
        self.saved()
        rows, members, access = connections.permitted_entities(self.store, str(USER), NOW)
        for row in rows:
            if row['entity_id'] == 'meal:1':
                for key in ('recorded_at', 'recorded_at_basis', 'consumed_at', 'consumed_at_basis'):
                    row['payload'].pop(key, None)
        with patch.object(meal_anchors, 'permitted_entities', return_value=(rows,members,access)):
            self.assertEqual(len(self.read()), 1)
            next(e for e in rows if e['entity_id']=='meal:1')['payload']['source_local_date']='2026-10-19'
            self.assertEqual(self.read(), [])

    def test_private_anchor_read_keeps_signature_and_supply_audience_rules(self):
        self.saved(day='2026-10-19')
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        with TestClient(create_app(self.config)) as client, patch.object(meal_anchors, 'datetime', Clock):
            client.app.state.engine.poll()
            route='/internal/v1/connections/meal-events'
            raw=canonical({'people':[str(USER)]}).encode()
            self.assertEqual(client.post(route,content=raw).status_code,401)
            def send(source):
                return client.post(route,content=raw,headers={'X-Progressor-Control':control_token(source,route,raw,KEY)})
            self.assertEqual(send('food').status_code,403)
            result=send('supply')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json(),{'items':[]})


if __name__=='__main__':
    unittest.main()
