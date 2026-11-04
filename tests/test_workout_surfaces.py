import os,sqlite3,tempfile,unittest
from datetime import datetime
from pathlib import Path
from test_integration import fixture,USER,NOW
from progressor_core.adapters import snapshot
from progressor_core.store import Store
from progressor_core.context import build_context


class WorkoutSurfaces(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db')
        with sqlite3.connect(self.paths['gym']) as db:
            db.executescript('ALTER TABLE sets ADD COLUMN user_exercise_id INTEGER;ALTER TABLE sets ADD COLUMN reps INTEGER;ALTER TABLE sets ADD COLUMN seconds INTEGER;ALTER TABLE sets ADD COLUMN weight_kg REAL;CREATE TABLE session_exercises(session_id INTEGER,user_exercise_id INTEGER,is_done INTEGER,done_at TEXT);CREATE TABLE progressor_session_durations(session_id INTEGER,duration_seconds INTEGER,recorded_at TEXT);')
            db.execute('UPDATE sets SET user_exercise_id=700,reps=10,seconds=0,weight_kg=50')
            db.execute("INSERT INTO session_exercises VALUES(20,700,1,'2026-10-07T09:00:00Z')")
            db.execute("INSERT INTO sessions VALUES(21,7,'2026-10-07',0,1)")
            db.execute("INSERT INTO session_exercises VALUES(21,701,1,'2026-10-07T10:00:00Z')")
            db.execute("INSERT INTO sets VALUES(31,21,0,701,12,0,30)")
            db.execute("INSERT INTO sets VALUES(32,21,0,702,99,0,99)")
            # A genuine current touch proof is required for this positive free
            # fixture. Atomic native writer behavior is tested separately.
            db.executescript("CREATE TABLE progressor_free_sessions(session_id INTEGER PRIMARY KEY,last_activity REAL,status TEXT,completed_at TEXT,completion_basis TEXT,last_finished_at REAL);CREATE TABLE progressor_free_activity_proof(session_id INTEGER PRIMARY KEY,last_activity REAL,source_local_date TEXT,activity_timezone TEXT,proof_version INTEGER,clock_kind TEXT);")
            clock=datetime.fromisoformat('2026-10-07T10:00:00+00:00').timestamp()
            db.execute("INSERT INTO progressor_free_sessions VALUES(21,?,'active',NULL,NULL,NULL)",(clock,))
            db.execute("INSERT INTO progressor_free_activity_proof VALUES(21,?,'2026-10-07','Europe/Moscow',1,'native_touch')",(clock,))
    def tearDown(self):self.tmp.cleanup()
    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
        return build_context(self.store,str(USER),NOW,target='food')
    def test_full_day_and_free_marks_both_arrive_once(self):
        c=self.sync();self.assertEqual(c['activity']['recorded_session_count'],2)
        self.assertEqual(c['activity']['completed_workout_count'],1)
        self.assertEqual(sum(w['strength_metrics']['working_sets'] for w in c['activity']['workouts']),2)
        self.assertEqual(sum(w['strength_metrics']['repetitions'] for w in c['activity']['workouts']),22)
        self.assertIn('тренировочных записей',c['inline_hint']['message'])
        self.assertIn('Рабочих подходов — 2, повторений — 22',c['inline_hint']['message'])
        self.assertEqual(self.sync()['activity'],c['activity'])
    def test_drafts_undone_exercises_and_removed_sets_do_not_count(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM sets WHERE id=31')
        self.assertEqual(self.sync()['activity']['recorded_session_count'],1)
    def test_later_day_completion_replaces_partial_session_without_double_count(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute("INSERT INTO day_completion_history VALUES(11,7,1,0,'2026-10-07T10:05:00Z')")
        c=self.sync();self.assertEqual(c['activity']['recorded_session_count'],2)
        self.assertEqual(c['activity']['completed_workout_count'],2)
        self.assertEqual(sum(w['strength_metrics']['repetitions'] for w in c['activity']['workouts']),22)
    def test_backfilled_mark_preserves_training_day_and_is_labelled(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute("UPDATE sessions SET date='2026-10-06' WHERE id=21")
        self.sync();entities=self.store.data(str(USER))[0]
        free=next(e for e in entities if e['entity_id']=='workout:session:21')
        self.assertTrue(free['payload']['backfilled']);self.assertEqual(free['payload']['source_local_date'],'2026-10-06')
    def test_recorded_free_strength_duration_arrives_without_guessing(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute("INSERT INTO progressor_session_durations VALUES(21,3600,'2026-10-07T10:01:00Z')")
        c=self.sync();free=next(w for w in c['activity']['workouts'] if w.get('session_id')==21)
        self.assertEqual(free['recorded_strength_duration_seconds'],3600)
        self.assertIsNone(free['energy_estimate']) # No adult profile was provided in this fixture.
