import asyncio,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from shared.progressor_client import publish_source_snapshot,source_snapshot_worker
from progressor_core.adapters import snapshot

class SourceSnapshots(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.live=self.root/'live.sqlite3';self.target=self.root/'published/source.sqlite3'
        self.writer=sqlite3.connect(self.live)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('CREATE TABLE marker(id INTEGER PRIMARY KEY,value TEXT)')
        self.writer.execute("INSERT INTO marker VALUES(1,'before')");self.writer.commit()
    def tearDown(self):self.writer.close();self.tmp.cleanup()
    def test_wal_rows_and_atomic_replacement_preserve_reader(self):
        publish_source_snapshot(self.live,self.target)
        old=sqlite3.connect(self.target.as_uri()+'?mode=ro',uri=True)
        old.execute('BEGIN');self.assertEqual(old.execute('SELECT value FROM marker').fetchone()[0],'before')
        self.writer.execute("UPDATE marker SET value='after'");self.writer.commit()
        publish_source_snapshot(self.live,self.target)
        try:
            self.assertEqual(old.execute('SELECT value FROM marker').fetchone()[0],'before')
            with sqlite3.connect(self.target.as_uri()+'?mode=ro',uri=True) as new:
                self.assertEqual(new.execute('SELECT value FROM marker').fetchone()[0],'after')
                self.assertEqual(new.execute('PRAGMA journal_mode').fetchone()[0],'delete')
            self.assertEqual(self.writer.execute('SELECT value FROM marker').fetchone()[0],'after')
            self.assertFalse(Path(str(self.target)+'-wal').exists())
            self.assertFalse(Path(str(self.target)+'-shm').exists())
        finally:old.close()
    def test_failure_preserves_previous_good_copy(self):
        publish_source_snapshot(self.live,self.target);before=self.target.read_bytes()
        with patch('shared.progressor_client.time.monotonic',side_effect=[0,11]):
            with self.assertRaises(TimeoutError):publish_source_snapshot(self.live,self.target)
        self.assertEqual(self.target.read_bytes(),before)
        self.assertEqual(list(self.target.parent.glob('.source-*')),[])
    def test_stale_snapshot_is_rejected_before_sql_or_deletions(self):
        publish_source_snapshot(self.live,self.target)
        os.utime(self.target,(time.time()-91,time.time()-91))
        with self.assertRaisesRegex(FileNotFoundError,'source_snapshot_stale'):snapshot('gym',self.target,max_age=90)
    def test_never_overwrite_live_database(self):
        with self.assertRaisesRegex(ValueError,'unsafe_source_snapshot_path'):publish_source_snapshot(self.live,self.live)

class SnapshotWorker(unittest.IsolatedAsyncioTestCase):
    async def test_owner_export_does_not_require_core_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            live=Path(folder)/'live.sqlite3';target=Path(folder)/'private/source.sqlite3'
            with sqlite3.connect(live) as db:db.execute('CREATE TABLE marker(value TEXT)');db.execute("INSERT INTO marker VALUES('native')")
            task=asyncio.create_task(source_snapshot_worker('gym',live,target))
            try:
                for _ in range(100):
                    if target.exists():break
                    await asyncio.sleep(.01)
                self.assertTrue(target.exists())
                with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:self.assertEqual(db.execute('SELECT value FROM marker').fetchone()[0],'native')
            finally:
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
