"""Optional historical Supply metadata never relocates an owned intake."""
from contextlib import closing
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from test_integration import fixture, USER
from progressor_core.adapters import snapshot
from progressor_core.context import build_context
from progressor_core.contracts import validate_payload
from progressor_core.daily_overview import daily_overview
from progressor_core.meal_anchors import events as meal_events
from progressor_core.store import Store

NOW = datetime(2026, 10, 6, 9, 5, tzinfo=timezone.utc)
FIRST = datetime(2026, 10, 6, 8, tzinfo=timezone.utc).timestamp()
SECOND = datetime(2026, 10, 6, 10, tzinfo=timezone.utc).timestamp()
SCHEMA = '''CREATE TABLE progressor_timezone_history(
user_id TEXT NOT NULL,changed_at REAL NOT NULL,before_zone TEXT NOT NULL,
after_zone TEXT NOT NULL,PRIMARY KEY(user_id,changed_at));'''


class SupplyIntakeTimezones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        self.root = Path(self.tmp.name)
        self.paths = fixture(self.root)
        self.path = Path(self.paths['supply'])

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def write(self, sql, values=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql, values)

    def ledger(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA)

    def transition(self, at=FIRST, before='UTC', after='UTC+03:00', owner=None):
        self.write('INSERT INTO progressor_timezone_history VALUES(?,?,?,?)',
                   (str(USER if owner is None else owner), at, before, after))

    def intake(self):
        value = next(e for e in snapshot('supply', self.path)['entities']
                     if e['entity_id'].startswith('intake:'))
        validate_payload(value['event_type'], {**value['payload'], 'entity_id':value['entity_id']})
        return value

    def unknown(self):
        value = self.intake()
        self.assertNotIn('timezone', value['payload'])
        self.assertEqual(value['payload']['timezone_basis'], 'not_recorded')
        return value

    def known(self, expected):
        value = self.intake()
        self.assertEqual(value['payload']['timezone'], expected)
        self.assertEqual(value['payload']['timezone_basis'], 'owner_transition_ledger')
        return value

    def test_no_ledger_optional_metadata_reconciles_context_daily_and_food_anchor(self):
        original = self.unknown()
        with closing(sqlite3.connect(self.path)) as db:
            before = list(db.iterdump())
        store = Store(self.root/'core.sqlite3')
        store.owner_policy_gate = None
        for source, path in self.paths.items():
            store.reconcile(source, snapshot(source, path))
        context = build_context(store, str(USER), NOW)
        self.assertEqual(context['supply']['recorded_intake_count'], 1)
        self.assertEqual(context['supply']['recent_intakes'][0]['source_local_date'], '2026-10-06')
        self.assertNotIn('timezone', context['supply']['recent_intakes'][0])
        summary = daily_overview(store, str(USER), NOW)
        supply = next(row for row in summary['sections'] if row['source']=='supply')
        self.assertEqual((supply['day'], supply['timezone'], supply['taken_records']),
                         ('2026-10-06', 'UTC+03:00', 1))
        anchored = meal_events(store, [str(USER)], NOW)
        self.assertEqual(len(anchored['items']), 1)
        self.assertEqual(anchored['items'][0]['meals'][0]['occurred_at'], '2026-10-06T09:00:00Z')
        self.assertEqual(self.intake(), original)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_empty_ledger_is_unknown_and_current_profile_zone_is_retained(self):
        self.ledger();self.unknown()
        profile = next(e for e in snapshot('supply', self.path)['entities']
                       if e['entity_id']=='profile:55')
        self.assertEqual(profile['payload']['timezone'], 'UTC+03:00')
        self.assertEqual(profile['payload']['paid_until'], '2030-01-01T00:00:00Z')

    def test_before_first_transition_is_unknown_before_and_after_later_change(self):
        self.write("UPDATE users SET tz_name='UTC' WHERE id=55")
        before = self.unknown()
        self.ledger();self.transition(SECOND, 'UTC', 'Asia/Bangkok')
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        self.assertEqual(self.unknown(), before)

    def test_proven_interval_stays_stable_across_later_transition_and_return(self):
        self.ledger();self.transition()
        before = self.known('UTC+03:00')
        self.transition(SECOND, 'UTC+03:00', 'Asia/Bangkok')
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        self.assertEqual(self.known('UTC+03:00'), before)
        self.transition(SECOND+3600, 'Asia/Bangkok', 'UTC+03:00')
        self.write("UPDATE users SET tz_name='UTC+03:00' WHERE id=55")
        self.assertEqual(self.known('UTC+03:00'), before)

    def test_other_telegram_owner_and_internal_id_cannot_supply_lineage(self):
        self.ledger()
        self.transition(owner=55)  # Internal Supply id is not the Telegram id.
        self.transition(owner=USER+1)
        self.unknown()

    def test_broken_transition_chain_is_unknown_without_hiding_intake(self):
        self.ledger();self.transition()
        self.transition(SECOND, 'Europe/London', 'Asia/Bangkok')
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        value = self.unknown()
        self.assertEqual(value['occurred_at'], '2026-10-06T09:00:00Z')
        self.assertEqual(value['payload']['source_local_date'], '2026-10-06')
        self.assertEqual(value['payload']['status'], 'taken')

    def test_current_zone_mismatch_fails_closed_to_unknown(self):
        self.ledger();self.transition()
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        self.unknown()

    def test_invalid_zone_timestamp_and_noop_rows_do_not_become_proof(self):
        self.ledger()
        for at, before, after in ((FIRST,'Mars/Phobos','UTC+03:00'),
                                 (float('inf'),'UTC','UTC+03:00'),
                                 (-1,'UTC','UTC+03:00'),
                                 (FIRST,'UTC+03:00','UTC+03:00')):
            with self.subTest(row=(at,before,after)):
                self.write('DELETE FROM progressor_timezone_history')
                self.transition(at,before,after)
                self.unknown()

    def test_cutover_in_recorded_second_is_unknown_but_next_second_is_known(self):
        self.ledger();self.transition()
        self.transition(SECOND-3600+.5, 'UTC+03:00', 'Asia/Bangkok')
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        self.unknown()  # 09:00:00 could be before or after09:00:00.5.
        self.write("UPDATE supplement_day_state SET created_at='2026-10-06T09:00:01Z'")
        self.known('Asia/Bangkok')
        self.write("UPDATE supplement_day_state SET created_at='2026-10-06T08:00:00Z'")
        self.unknown()  # Exact first-transition second also has no native order.
        self.write("UPDATE supplement_day_state SET created_at='2026-10-06T08:00:01Z'")
        self.known('UTC+03:00')

    def test_unknown_legacy_does_not_erase_reported_dose_or_recompute_day(self):
        self.write("ALTER TABLE supplement_day_state ADD COLUMN dose_snapshot_json TEXT")
        self.write('UPDATE supplement_day_state SET dose_snapshot_json=?', (json.dumps(['2 таблетки']),))
        value = self.unknown()
        self.assertEqual(value['entity_id'], 'intake:55:5:2026-10-06')
        self.assertEqual(value['payload']['reported_doses'], ['2 таблетки'])
        self.assertEqual(value['payload']['source_local_date'], '2026-10-06')
        self.assertEqual(value['occurred_at'], '2026-10-06T09:00:00Z')

    def test_failed_owner_transition_transaction_does_not_change_projection(self):
        self.ledger();self.transition();before = self.known('UTC+03:00')
        self.write("CREATE TRIGGER fail_zone BEFORE UPDATE OF tz_name ON users BEGIN SELECT RAISE(ABORT,'fixture abort'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO progressor_timezone_history VALUES(?,?,?,?)',
                           (str(USER), SECOND, 'UTC+03:00', 'Asia/Bangkok'))
                db.execute("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        self.assertEqual(self.known('UTC+03:00'), before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM progressor_timezone_history').fetchone()[0], 1)

    def test_historical_metadata_repair_is_not_a_current_profile_zone_change(self):
        self.ledger();self.transition()
        self.transition(SECOND, 'UTC+03:00', 'Asia/Bangkok')
        self.write("UPDATE users SET tz_name='Asia/Bangkok' WHERE id=55")
        current = snapshot('supply', self.path)
        # Exact old metadata shape reproduced by the separately retained actual
        # frozen adapter: its old intake used the current profile's zone.
        legacy = json.loads(json.dumps(current))
        old = next(e for e in legacy['entities'] if e['entity_id'].startswith('intake:'))
        old['payload'].pop('timezone_basis')
        old['payload']['timezone'] = 'Asia/Bangkok'
        store = Store(self.root/'upgrade.sqlite3');store.owner_policy_gate = None
        store.reconcile('supply', legacy)
        store.reconcile('supply', current)
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM connection_changes WHERE kind='timezone'").fetchone()[0], 0)
        self.write("UPDATE users SET tz_name='Europe/Berlin' WHERE id=55")
        store.reconcile('supply', snapshot('supply', self.path))
        with store.connection() as db:
            rows = db.execute("SELECT body FROM connection_changes WHERE kind='timezone'").fetchall()
        self.assertEqual(len(rows), 1)
        value = json.loads(rows[0][0])
        self.assertEqual((value['before'], value['after']), ('Asia/Bangkok', 'Europe/Berlin'))


if __name__ == '__main__':
    unittest.main()
