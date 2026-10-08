"""Recovery must retain user writes and the previous runtime without provider calls."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('updater', Path(__file__).parents[1] / 'deploy/update_progressor.py')
updater = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(updater)
except ModuleNotFoundError:
    updater = None  # fcntl is Linux-only; production tests run on Linux.


@unittest.skipIf(updater is None, 'Production updater is Linux-only')
class UpdateRecovery(unittest.TestCase):
    def test_failed_release_restores_pointer_and_never_restores_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / 'releases/old'; old.mkdir(parents=True)
            new = root / 'releases/new'; new.mkdir()
            (root / 'current').symlink_to(old, target_is_directory=True)
            data = root / 'ledger.sqlite3'; data.write_bytes(b'new user writes')
            with patch.object(updater, 'ROOT', root), patch.object(updater, 'run') as run, \
                    patch.object(updater, 'wait_ready', side_effect=[RuntimeError('not_ready'), {'sources': {}}]):
                with self.assertRaises(RuntimeError):
                    updater.apply_release(new, old, {'sources': {}}, root / 'backup')
                self.assertEqual((root / 'current').resolve(), old)
                self.assertEqual(data.read_bytes(), b'new user writes')
                self.assertEqual(run.call_count, 2)

    def test_source_readiness_cannot_regress_healthy_baseline(self):
        old = {'ready': True, 'sources': {'gym': 'ok', 'food': 'ok', 'supply': 'degraded'}}
        self.assertFalse(updater.compatible_readiness({'ready': True, 'sources': {'gym': 'ok', 'food': 'degraded'}}, old))
        self.assertTrue(updater.compatible_readiness({'ready': True, 'sources': {'gym': 'ok', 'food': 'ok'}}, old))

    def test_offline_environment_does_not_inherit_production_tokens(self):
        with patch.dict('os.environ', {'PROGRESSOR_GYM_BOT_TOKEN': 'LIVE', 'YOOKASSA_SECRET_KEY': 'LIVE'}):
            env = updater.offline_environment(Path('/tmp/own-tests'))
        self.assertNotIn('PROGRESSOR_GYM_BOT_TOKEN', env)
        self.assertNotIn('YOOKASSA_SECRET_KEY', env)
        self.assertEqual(env['BOT_TOKEN'], '123:OFFLINE')
