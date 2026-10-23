"""Owner reset and response publication serialize in the canonical cache write.

Private SQLite only. The predicate is trusted local code, not a client callback.
"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from shared import ai_cache as cache


class CachePublication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'owner.sqlite3')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(cache.SCHEMA)
            db.execute('CREATE TABLE owner_resets(owner TEXT PRIMARY KEY, epoch INTEGER NOT NULL)')
            db.execute("INSERT INTO owner_resets VALUES('one',0)")

    def tearDown(self):
        self.temp.cleanup()

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM progressor_ai_cache ORDER BY user_id,key').fetchall()

    def put(self, **kwargs):
        return cache.put(self.path, 'one', 'analysis', 'a' * 64, {'result': 1}, now=1000, **kwargs)

    def expected_zero(self, db):
        self.assertTrue(db.in_transaction)
        return db.execute("SELECT epoch FROM owner_resets WHERE owner='one'").fetchone()[0] == 0

    def test_legacy_caller_and_hit_keep_existing_ttl(self):
        self.assertTrue(self.put(ttl=60))
        before = self.rows()
        self.assertEqual(cache.get(self.path, 'one', 'analysis', 'a' * 64, now=1059), {'result': 1})
        self.assertEqual(self.rows(), before)
        self.assertIsNone(cache.get(self.path, 'one', 'analysis', 'a' * 64, now=1060))

    def test_denied_publication_keeps_expired_and_foreign_entries_exact(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO progressor_ai_cache VALUES(?,?,?,?,?,?)', ('other','analysis','b' * 64,'{}',1,2))
        before = self.rows()
        seen = []
        def denied(db):
            seen.append(db.in_transaction)
            return False
        self.assertFalse(self.put(publish_if=denied))
        self.assertEqual(seen, [True])
        self.assertEqual(self.rows(), before)

    def test_predicate_exception_rolls_back_and_releases_connection(self):
        self.assertTrue(self.put())
        before = self.rows()
        def failed(db):
            self.assertTrue(db.in_transaction)
            raise ValueError('synthetic predicate failure')
        with self.assertRaises(ValueError):
            self.put(publish_if=failed)
        self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.path, timeout=.1)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE owner_resets SET epoch=1 WHERE owner='one'")

    def test_reset_committed_before_late_provider_result_denies_publication(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE owner_resets SET epoch=1 WHERE owner='one'")
        self.assertFalse(self.put(publish_if=self.expected_zero))
        self.assertEqual(self.rows(), [])

    def test_publication_first_then_waiting_owner_reset_removes_its_result(self):
        entered, release, reset_attempted = threading.Event(), threading.Event(), threading.Event()
        errors, published = [], []
        def fence(db):
            entered.set()
            if not release.wait(4):
                raise AssertionError('synthetic publication release timed out')
            return self.expected_zero(db)
        def publish():
            try:
                published.append(self.put(publish_if=fence))
            except BaseException as exc:
                errors.append(exc)
        def reset():
            try:
                reset_attempted.set()
                with closing(sqlite3.connect(self.path, timeout=4)) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute("UPDATE owner_resets SET epoch=1 WHERE owner='one'")
                    db.execute("DELETE FROM progressor_ai_cache WHERE user_id='one'")
            except BaseException as exc:
                errors.append(exc)
        publisher, resetter = threading.Thread(target=publish), threading.Thread(target=reset)
        publisher.start()
        try:
            self.assertTrue(entered.wait(4))
            resetter.start()
            self.assertTrue(reset_attempted.wait(4))
        finally:
            release.set()
            publisher.join(5)
            if resetter.ident is not None:
                resetter.join(5)
        self.assertFalse(publisher.is_alive() or resetter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(published, [True])
        self.assertEqual(self.rows(), [])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT epoch FROM owner_resets WHERE owner='one'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
