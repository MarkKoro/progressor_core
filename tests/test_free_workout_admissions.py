"""Owned SQLite admission/transaction/reset scenarios; no providers or delivery."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from progressor_core import free_workout_notifications as policy
from progressor_core.store import Store


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace('+00:00', 'Z')


def item(stamp=200, *, proof=True, complete=True, owner='1', entity='workout:session:1'):
    day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat() if stamp is not None else '1970-01-01'
    value = iso(stamp) if stamp is not None else iso(190)
    payload = {'session_id': int(entity.rsplit(':', 1)[-1]), 'day_index': 0,
        'source_local_date': day, 'timezone': 'UTC', 'completed_at': value,
        'timestamp_basis': 'source_utc' if stamp is not None else 'session_local_day',
        'recorded_at': value, 'duration_seconds': None, 'strength_sets': 2,
        'workout_type': 'strength', 'session_complete': complete,
        'backfilled': not proof, 'activity_time_basis': 'source_last_activity' if proof else 'recorded_only',
        'activity_day_basis': 'owner_validated_session_day' if proof else 'not_recorded',
        'activity_clock': {'version': 1, 'clock_kind': 'native_touch' if proof else 'recorded_only',
            'source_last_activity': stamp, 'activity_at': iso(stamp) if stamp is not None else None,
            'source_local_date': day, 'activity_timezone': 'UTC' if proof else None}}
    if not proof:
        payload.pop('timezone')
    return {'entity_id': entity, 'user_id': owner, 'event_type': 'workout.completed' if complete else 'workout.updated',
        'occurred_at': value, 'payload': payload}


class FreeWorkoutAdmissions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'core.sqlite3'
        self.clock = patch.object(policy.time, 'time', return_value=100)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.identity_clock = patch('progressor_core.store.now_utc', return_value=iso(50))
        self.identity_clock.start(); self.addCleanup(self.identity_clock.stop)
        self.store = Store(self.path)
        with self.store.connection() as db:
            db.execute('INSERT INTO identities VALUES(?,?)', ('1', iso(50)))

    def observe(self, value, now=300):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            policy.observe_snapshot(db, {'entities': [value]}, {}, now=now)

    def allowed(self, value, now=300):
        with self.store.connection() as db:
            return policy.allowed(db, value['user_id'], value['entity_id'], value['payload'], now=now)

    def rows(self):
        with self.store.connection() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM free_workout_notification_admissions ORDER BY user_id,entity_id,clock_bucket')]

    def snapshot(self, values):
        return {'entities': values, 'memberships': [{'user_id': '1', 'local_id': '1'}]}

    def test_new_partial_touch_admits_before_completion_without_requiring_read(self):
        value = item(200, complete=False)
        self.observe(value)
        self.assertTrue(self.allowed(value))
        completed = item(200)
        self.observe(completed, 310)
        self.assertTrue(self.allowed(completed, 310))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0][4:], (300.0, 'admitted', 'native_touch'))

    def test_pre_epoch_equal_and_future_clocks_terminally_denied(self):
        for stamp in (99, 100, 301):
            value = item(stamp)
            self.observe(value)
            self.assertFalse(self.allowed(value))
            self.observe(value, 500)
            self.assertFalse(self.allowed(value, 500))
        self.assertEqual({row[5] for row in self.rows()}, {'denied'})

    def test_same_bucket_proof_repair_never_promotes(self):
        self.observe(item(200, proof=False))
        self.observe(item(200), 310)
        self.assertFalse(self.allowed(item(200), 310))
        self.assertEqual(self.rows()[0][5], 'denied')
        self.assertEqual(self.rows()[0][4], 300)

    def test_successful_witness_invalidation_revokes_then_same_clock_repair_stays_blocked(self):
        self.observe(item(200))
        self.assertTrue(self.allowed(item(200)))
        self.observe(item(200, proof=False), 310)
        self.assertFalse(self.allowed(item(200), 310))
        self.observe(item(200), 320)
        self.assertFalse(self.allowed(item(200), 320))
        self.assertEqual(self.rows()[0][4:], (300.0, 'revoked', 'not_native_touch'))

    def test_missing_clock_marker_denies_old_repair_but_new_touch_can_qualify(self):
        self.observe(item(None, proof=False))
        self.observe(item(250), 350)
        self.assertFalse(self.allowed(item(250), 350))
        self.observe(item(320), 350)
        self.assertTrue(self.allowed(item(320), 350))
        self.assertEqual(len(self.rows()), 3)

    def test_successful_deletion_revokes_and_reappearance_same_clock_stays_revoked(self):
        value = item(200)
        self.observe(value)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            policy.observe_snapshot(db, {'entities': []}, {value['entity_id']: {'user_id': '1', 'deleted': 0}}, now=310)
        self.observe(value, 320)
        self.assertFalse(self.allowed(value, 320))
        self.observe(item(315), 320)
        self.assertTrue(self.allowed(item(315), 320))
        self.assertEqual({row[5] for row in self.rows()}, {'revoked', 'admitted'})

    def test_failed_source_and_ordinary_read_leave_ledger_exact(self):
        value = item(200)
        self.observe(value)
        before = self.rows()
        self.store.failed('gym', 'synthetic_failure')
        self.assertTrue(self.allowed(value))
        self.assertEqual(self.rows(), before)

    def test_read_missing_receipt_and_identity_never_writes(self):
        value = item(200)
        before = self.rows()
        self.assertFalse(self.allowed(value))
        with self.store.connection() as db:
            db.execute("DELETE FROM identities WHERE user_id='1'")
            before_changes = db.total_changes
            self.assertFalse(policy.allowed(db, '1', value['entity_id'], value['payload'], now=300))
            self.assertEqual(db.total_changes, before_changes)
            self.assertFalse(db.execute("SELECT 1 FROM identities WHERE user_id='1'").fetchone())
        self.assertEqual(self.rows(), before)

    def test_identity_floor_rejects_retained_admission_and_future_invalid_identity(self):
        value = item(200); self.observe(value)
        for identity in (iso(200), iso(250), iso(400), 'naive', '1970-01-01T00:00:50', '1970-01-01T00:00:50.0000001Z'):
            with self.store.connection() as db:
                db.execute('UPDATE identities SET created_at=? WHERE user_id=?', (identity, '1'))
            self.assertFalse(self.allowed(value))

    def test_owner_delete_cleanup_retains_other_owner_and_immutable_epoch(self):
        value = item(200); self.observe(value)
        with self.store.connection() as db:
            db.execute('INSERT INTO identities VALUES(?,?)', ('2', iso(50)))
        self.observe(item(200, owner='2'))
        with self.store.connection() as db:
            db.execute("DELETE FROM identities WHERE user_id='1'")
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)
        self.assertEqual({row[0] for row in self.rows()}, {'2'})
        self.assertTrue(self.allowed(item(200, owner='2')))

    def test_restart_keeps_epoch_and_identity(self):
        self.observe(item(200))
        with patch.object(policy.time, 'time', return_value=500):
            Store(self.path)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)
            self.assertEqual(db.execute("SELECT created_at FROM identities WHERE user_id='1'").fetchone()[0], iso(50))
        self.assertTrue(self.allowed(item(200), 500))

    def test_same_hash_reconcile_recreates_identity_before_receipt_observation(self):
        value = item(200)
        with patch.object(policy.time, 'time', return_value=300):
            self.assertEqual(self.store.reconcile('gym', self.snapshot([value])), 1)
        with self.store.connection() as db:
            db.execute("DELETE FROM identities WHERE user_id='1'")
        self.assertEqual(self.rows(), [])
        with patch.object(policy.time, 'time', return_value=400), patch('progressor_core.store.now_utc', return_value=iso(400)):
            self.assertEqual(self.store.reconcile('gym', self.snapshot([value])), 0)
        self.assertFalse(self.allowed(value, 500))
        self.assertEqual(self.rows()[0][5:], ('denied', 'pre_policy_or_identity'))
        newer = item(450)
        with patch.object(policy.time, 'time', return_value=500):
            self.assertEqual(self.store.reconcile('gym', self.snapshot([newer])), 1)
        self.assertTrue(self.allowed(newer, 500))

    def test_mid_reconcile_error_rolls_back_receipt_and_entity_and_membership(self):
        before = self.rows()
        value = item(200)
        invalid = {**item(210, entity='workout:session:2'), 'occurred_at': 'invalid'}
        with patch.object(policy.time, 'time', return_value=300):
            with self.assertRaises(ValueError):
                self.store.reconcile('gym', self.snapshot([value, invalid]))
        self.assertEqual(self.rows(), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entities').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM memberships').fetchone()[0], 0)

    def test_direct_accept_cannot_admit_and_later_same_hash_reconcile_can_observe(self):
        value = item(200)
        event = {'event_id': 'direct', 'event_type': value['event_type'], 'schema_version': 1,
            'source': 'gym', 'user_id': '1', 'occurred_at': value['occurred_at'], 'correlation_id': 'direct',
            'payload': {**value['payload'], 'entity_id': value['entity_id'], 'revision': 1}}
        self.store.accept(event)
        self.assertFalse(self.allowed(value))

    def test_numeric_malformed_owner_or_entity_has_no_admission(self):
        value = item(200)
        for owner, entity in [('01', value['entity_id']), ('1', 'workout:1'), ('1', 'workout:session:01'), ('1', 'workout:session:１')]:
            other = {**value, 'user_id': owner, 'entity_id': entity}
            self.observe(other)
            self.assertFalse(self.allowed(other))
        self.assertEqual(self.rows(), [])

    def test_equality_in_microsecond_bucket_is_conservatively_denied(self):
        with self.store.connection() as db:
            db.execute('UPDATE identities SET created_at=? WHERE user_id=?', (iso(200.000001), '1'))
        value = item(200.0000006)
        self.observe(value)
        self.assertFalse(self.allowed(value))

    def test_missing_or_malformed_existing_policy_is_never_reinitialized(self):
        for statement in [
            'CREATE TABLE free_workout_notification_policy(bad TEXT)',
            'CREATE VIEW FREE_WORKOUT_NOTIFICATION_POLICY AS SELECT 1 AS bad',
            policy.POLICY_SQL,
        ]:
            with self.subTest(statement=statement):
                path = Path(self.temp.name) / ('malformed-' + str(len(list(Path(self.temp.name).iterdir()))) + '.sqlite3')
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(statement)
                with patch.object(policy.time, 'time', return_value=700):
                    other = Store(path)
                with other.connection() as db:
                    self.assertFalse(policy.allowed(db, '1', 'workout:session:1', item(200)['payload'], now=800))
                    self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='free_workout_notification_admissions'").fetchone())

    def test_singleton_row_loss_and_corrupt_epoch_fail_closed_without_reset(self):
        self.observe(item(200))
        with self.store.connection() as db:
            db.execute('DELETE FROM free_workout_notification_policy')
        with patch.object(policy.time, 'time', return_value=500):
            Store(self.path)
        self.assertFalse(self.allowed(item(200), 500))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM free_workout_notification_policy').fetchone()[0], 0)

    def test_reserved_table_and_trigger_same_name_is_ambiguous_and_not_repaired(self):
        self.observe(item(200))
        with self.store.connection() as db:
            db.execute('CREATE TRIGGER free_workout_notification_policy AFTER INSERT ON identities BEGIN SELECT 1; END')
        Store(self.path)
        self.assertFalse(self.allowed(item(200)))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='free_workout_notification_policy'").fetchone()[0], 2)

    def test_sqlite_authorizer_read_error_fails_closed_without_writes(self):
        self.observe(item(200))
        with self.store.connection() as db:
            before = db.total_changes
            db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and args[0] == 'sqlite_master' else sqlite3.SQLITE_OK)
            self.assertFalse(policy.allowed(db, '1', 'workout:session:1', item(200)['payload'], now=300))
            self.assertEqual(db.total_changes, before)
            db.set_authorizer(None)

    def test_large_unchanged_snapshot_uses_batched_pk_probes_without_ledger_writes(self):
        values = [item(None if index % 3 == 0 else 200 + index / 10000,
            proof=index % 3 == 1, entity='workout:session:' + str(index + 1)) for index in range(800)]
        previous = {value['entity_id']: {'user_id':'1', 'deleted':0, 'hash':policy.digest(value)} for value in values}
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            policy.observe_snapshot(db, {'entities': values}, {}, now=300)
            # Unrelated lifetime history must not be loaded by the probes.
            db.executemany('INSERT INTO free_workout_notification_admissions VALUES(?,?,?,?,?,?,?)',
                [('2','workout:session:9000',iso(1 + n/10000),iso(1 + n/10000),100,'denied','history') for n in range(5000)])
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            before, traced = db.total_changes, []
            db.set_trace_callback(traced.append)
            policy.observe_snapshot(db, {'entities': values}, previous, now=400)
            db.set_trace_callback(None)
            self.assertEqual(db.total_changes, before)
            probes = [sql for sql in traced if sql.lstrip().startswith('WITH wanted')]
            self.assertEqual(len(probes), 7)
            self.assertFalse(any('INSERT' in sql.upper() or 'UPDATE' in sql.upper() for sql in traced))
            self.assertFalse(any('SELECT created_at' in sql or 'SELECT clock_bucket,first_observed_at' in sql for sql in traced))

    def test_probe_and_latest_marker_query_plans_use_point_indexes(self):
        self.observe(item(200))
        with self.store.connection() as db:
            probe = db.execute('EXPLAIN QUERY PLAN ' + policy.receipt_probe_sql(2),
                ('1','workout:session:1',iso(200),'1','workout:session:2',iso(201))).fetchall()
            details = [row[3] for row in probe]
            self.assertTrue(any('SEARCH a USING COVERING INDEX sqlite_autoindex_free_workout_notification_admissions_1 (user_id=? AND entity_id=? AND clock_bucket=?)' in detail for detail in details), details)
            self.assertFalse(any('SCAN a' in detail for detail in details), details)
            marker = db.execute('''EXPLAIN QUERY PLAN SELECT clock_bucket,first_observed_at,decision
                FROM free_workout_notification_admissions INDEXED BY free_workout_notification_unknown_floor
                WHERE user_id=? AND entity_id=? AND source_activity_at IS NULL
                ORDER BY first_observed_at DESC,clock_bucket DESC LIMIT 1''',('1','workout:session:1')).fetchall()
            details = [row[3] for row in marker]
            self.assertTrue(any('SEARCH free_workout_notification_admissions USING INDEX free_workout_notification_unknown_floor (user_id=? AND entity_id=?)' in detail for detail in details), details)
            self.assertFalse(any('SCAN free_workout_notification_admissions' in detail or 'TEMP B-TREE' in detail for detail in details), details)

    def test_unchanged_snapshot_missing_receipt_is_observed_before_hash_skip(self):
        value = item(200)
        with patch.object(policy.time, 'time', return_value=300):
            self.store.reconcile('gym', self.snapshot([value]))
        with self.store.connection() as db:
            db.execute('DELETE FROM free_workout_notification_admissions')
        with patch.object(policy.time, 'time', return_value=310):
            self.assertEqual(self.store.reconcile('gym', self.snapshot([value])), 0)
        self.assertTrue(self.allowed(value, 310))
        self.assertEqual(len(self.rows()), 1)

    def test_repeated_identical_explicit_tombstone_does_not_grow_receipts_or_floor(self):
        value = item(200)
        self.observe(value)
        tombstone = {**value, 'event_type':'workout.deleted', 'payload':{'deleted':True}}
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            policy.observe_snapshot(db, {'entities':[tombstone]}, {}, now=310)
        before = self.rows()
        previous = {value['entity_id']:{'user_id':'1','deleted':0,'hash':policy.digest(tombstone)}}
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            changes = db.total_changes
            policy.observe_snapshot(db, {'entities':[tombstone]}, previous, now=400)
            self.assertEqual(db.total_changes, changes)
        self.assertEqual(self.rows(), before)

    def test_index_migration_keeps_epoch_and_malformed_index_does_not_reset_policy(self):
        with self.store.connection() as db:
            db.execute('DROP INDEX free_workout_notification_unknown_floor')
        with patch.object(policy.time, 'time', return_value=500):
            Store(self.path)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)
            db.execute('DROP INDEX free_workout_notification_unknown_floor')
            db.execute('CREATE INDEX free_workout_notification_unknown_floor ON free_workout_notification_admissions(reason)')
        Store(self.path)
        self.assertFalse(self.allowed(item(200)))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)

    def test_context_projection_omits_unknown_vectors_but_raw_journal_and_events_keep_them(self):
        value = item(200, proof=False)
        metrics = {'schema_version':1,'working_sets':2,'repetitions':20,'external_volume_kg':200,
            'exercises':{'1':{'sets':2,'reps':20,'hold_seconds':0,'external_volume_kg':200}}}
        value['payload']['strength_metrics'] = metrics
        self.store.reconcile('gym', self.snapshot([value]))
        projection = self.store.context_snapshot('1', workout_day='1970-01-01')[0][0]
        self.assertEqual(len(projection), 1)
        self.assertNotIn('strength_metrics', projection[0]['payload'])
        raw = self.store.data('1')[0]
        self.assertEqual(raw[0]['payload']['strength_metrics'], metrics)
        with self.store.connection() as db:
            event = json.loads(db.execute('SELECT envelope FROM events').fetchone()[0])
            self.assertEqual(event['payload']['strength_metrics'], metrics)

    def test_known_free_and_programmed_vectors_keep_existing_in_out_window_behavior(self):
        metrics = {'schema_version':1,'working_sets':2,'repetitions':20,'external_volume_kg':200,
            'exercises':{'1':{'sets':2,'reps':20,'hold_seconds':0,'external_volume_kg':200}}}
        free = item(200)
        free['payload']['strength_metrics'] = metrics
        # Native programmed records do not carry free-activity proof metadata.
        programmed = {'entity_id':'workout:2','user_id':'1','event_type':'workout.completed',
            'occurred_at':iso(210),'payload':{'session_id':2,'day_index':1,
                'source_local_date':'1970-01-01','timezone':'UTC','completed_at':iso(210),
                'duration_seconds':None,'strength_sets':2,'workout_type':'strength',
                'session_complete':True,'backfilled':False}}
        programmed['payload']['strength_metrics'] = metrics
        self.store.reconcile('gym', self.snapshot([free,programmed]))
        for day, present in [('1970-01-01',True),('1971-01-01',False)]:
            projection = self.store.context_snapshot('1', workout_day=day)[0][0]
            self.assertEqual(len(projection), 2)
            for entity in projection:
                self.assertEqual('strength_metrics' in entity['payload'],present)
        self.assertTrue(all('strength_metrics' in e['payload'] for e in self.store.data('1')[0]))


    def test_schema_quoted_literals_keep_exact_bytes_and_malformed_policy_fails_closed(self):
        # The new comparison changes only outside-quote whitespace. Case,
        # inner spacing, doubled quotes and quoted identifiers stay exact.
        self.assertEqual(policy._sql("  SELECT\n 'a  b''C'  \tFROM [t  x] ; "), "SELECT 'a  b''C' FROM [t  x] ;".rstrip(';'))
        for left, right in [("SELECT 'admitted'", "SELECT 'ADMITTED'"),
                            ("SELECT 'a  b'", "SELECT 'a b'"),
                            ("SELECT 'a''B'", "SELECT 'a''b'"),
                            ('SELECT "A  B"', 'SELECT "A B"')]:
            self.assertNotEqual(policy._sql(left), policy._sql(right))
        with self.assertRaises(ValueError):
            policy._sql("SELECT 'unterminated")
        # Fresh canonical adoption is covered by setUp; retained startup keeps
        # the epoch and a real admission, without touching either ledger.
        self.observe(item(200))
        with self.store.connection() as db:
            retained = (db.execute('SELECT * FROM free_workout_notification_policy').fetchall(),
                        db.execute('SELECT * FROM free_workout_notification_admissions').fetchall())
            db.execute('BEGIN IMMEDIATE')
            before = db.total_changes
            self.assertTrue(policy.initialize(db, now=500))
            self.assertEqual(db.total_changes, before)
            self.assertTrue(policy.allowed(db, '1', 'workout:session:1', item(200)['payload'], now=500))
            self.assertEqual((db.execute('SELECT * FROM free_workout_notification_policy').fetchall(),
                              db.execute('SELECT * FROM free_workout_notification_admissions').fetchall()), retained)
        malformed = Path(self.temp.name) / 'quoted-check.sqlite3'
        bad_sql = policy.ADMISSIONS_SQL.replace("'admitted'", "'ADMITTED'")
        old_sql = lambda value: ' '.join(value.split()).casefold().removeprefix(' ').rstrip(';')
        self.assertEqual(old_sql(bad_sql), old_sql(policy.ADMISSIONS_SQL))
        with closing(sqlite3.connect(malformed)) as db:
            db.execute('CREATE TABLE identities(user_id TEXT PRIMARY KEY,created_at TEXT NOT NULL)')
            db.execute('INSERT INTO identities VALUES(?,?)', ('1', iso(50)))
            for statement in (policy.POLICY_SQL, bad_sql, policy.OWNER_TRIGGER_SQL, policy.MARKER_INDEX_SQL):
                db.execute(statement)
            db.execute('INSERT INTO free_workout_notification_policy VALUES(1,1,100)')
            db.commit()
            # Demonstrate the old validator's false positive on actual stored
            # SQLite DDL; the malformed CHECK rejects its canonical write.
            with patch.object(policy, '_sql', old_sql):
                self.assertEqual(policy._policy(db, 500), 100)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO free_workout_notification_admissions VALUES(?,?,?,?,?,?,?)',
                           ('1','workout:session:1',iso(200),iso(200),300,'admitted','native_touch'))
            db.rollback()
            db.execute('BEGIN IMMEDIATE')
            before = db.total_changes
            self.assertFalse(policy.initialize(db, now=500))
            self.assertFalse(policy.allowed(db, '1', 'workout:session:1', item(200)['payload'], now=500))
            policy.observe_snapshot(db, {'entities':[item(200)]}, {}, now=500)
            self.assertEqual(db.total_changes, before)
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchall(), [(100.0,)])
            self.assertEqual(db.execute('SELECT * FROM free_workout_notification_admissions').fetchall(), [])
            db.commit()
        # Retained malformed free policy must not stop ordinary Core journals.
        other = Store(malformed)
        programmed = {'entity_id':'workout:2','user_id':'1','event_type':'workout.completed',
            'occurred_at':iso(210),'payload':{'session_id':2,'day_index':1,
                'source_local_date':'1970-01-01','timezone':'UTC','completed_at':iso(210),
                'duration_seconds':None,'strength_sets':2,'workout_type':'strength',
                'session_complete':True,'backfilled':False}}
        other.reconcile('gym', self.snapshot([programmed,item(200)]))
        self.assertEqual({e['entity_id'] for e in other.data('1')[0]}, {'workout:2','workout:session:1'})
        with other.connection() as db:
            self.assertEqual(db.execute('SELECT adopted_at FROM free_workout_notification_policy').fetchone()[0], 100)
            self.assertEqual(db.execute('SELECT count(*) FROM free_workout_notification_admissions').fetchone()[0], 0)
            self.assertFalse(policy.allowed(db, '1', 'workout:session:1', item(200)['payload'], now=500))


if __name__ == '__main__':
    unittest.main()
