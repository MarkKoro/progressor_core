"""Real temporary Git/SQLite plus mocked process control; never use live providers."""
import base64
import importlib.util
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('all_updater', Path(__file__).parents[1] / 'deploy/update_all.py')
up = importlib.util.module_from_spec(spec)
try: spec.loader.exec_module(up)
except ModuleNotFoundError: up = None


@unittest.skipIf(up is None, 'Linux production updater')
class CoordinatedUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.core = self.root / 'core'
        self.old = self.core / 'releases/old'; self.old.mkdir(parents=True)
        self.new = self.core / 'releases/new'; self.new.mkdir()
        (self.core / 'current').symlink_to(self.old, target_is_directory=True)
        (self.old / 'REVISION').write_text('a' * 40)
        (self.new / 'REVISION').write_text('b' * 40)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name, value in {'CORE': self.core, 'STATE': self.core / 'updater/state.json',
                            'UPDATERS': self.core / 'updater', 'TRANSACTIONS': self.root / 'transactions',
                            'SYSTEMD': self.root / 'systemd', 'BACKUPS': self.root / 'backups',
                            'RUNTIMES': self.root / 'runtimes'}.items():
            self.stack.enter_context(patch.object(up, name, value))
        self.repos = {n: {**s, 'path': self.root / 'repositories' / n} for n, s in up.REPOS.items()}
        self.stack.enter_context(patch.object(up, 'REPOS', self.repos))
        self.stack.enter_context(patch.object(up, 'emit'))
        self.u = up.Updater(); self.u.folder.mkdir(parents=True)

    def git(self, name, *args):
        p = subprocess.run(['git', '-C', str(self.repos[name]['path']), *args], capture_output=True, text=True)
        if p.returncode: raise AssertionError(p.stderr)
        return p.stdout.strip()

    def repository(self, name):
        root = self.repos[name]['path']; root.mkdir(parents=True)
        self.git(name, 'init', '-b', 'main'); self.git(name, 'config', 'user.name', 'Offline test')
        self.git(name, 'config', 'user.email', 'offline@example.invalid')
        (root / 'code.py').write_text('old = True\n'); (root / 'deleted.py').write_text('restorable\n')
        (root / 'live.sqlite3').write_bytes(b'original data')
        self.git(name, 'add', '.'); self.git(name, 'commit', '-m', 'before')
        before = self.git(name, 'rev-parse', 'HEAD')
        (root / 'code.py').write_text('new = True\n'); (root / 'added.py').write_text('added\n')
        (root / 'deleted.py').unlink()
        self.git(name, 'add', '.'); self.git(name, 'commit', '-m', 'after')
        after = self.git(name, 'rev-parse', 'HEAD')
        self.u.state['repositories'][name] = {'before': before, 'target': after, 'available_main': after,
                                             'paths': ['code.py', 'added.py', 'deleted.py']}
        (root / 'live.sqlite3').write_bytes(b'new paid/user writes')
        (root / '.env').write_text('TOKEN=private\n')
        return before, after

    def mock_processes(self):
        calls = []
        def command(args, **_kwargs): calls.append(args); return 0, b''
        return calls, patch.object(up, 'command', side_effect=command)

    def test_protected_paths_allow_example_but_never_live_database_or_key(self):
        for path in ['data/food_bot.sqlite3', '.env', '.env.save', 'venv/file.py', 'p.key', '../x', '/root/x', 'x.db-wal']:
            self.assertTrue(up.protected_path(path), path)
        self.assertFalse(up.protected_path('.env.example'))
        self.assertFalse(up.protected_path('webapp/config.js'))

    def test_real_git_rollback_restores_added_deleted_files_and_keeps_tracked_live_data(self):
        before, _ = self.repository('food')
        self.u.rollback_repository('food'); self.u.rollback_repository('food')
        root = self.repos['food']['path']
        self.assertEqual(self.git('food', 'rev-parse', 'HEAD'), before)
        self.assertEqual((root / 'code.py').read_text(), 'old = True\n')
        self.assertFalse((root / 'added.py').exists()); self.assertTrue((root / 'deleted.py').exists())
        self.assertEqual((root / 'live.sqlite3').read_bytes(), b'new paid/user writes')
        self.assertEqual((root / '.env').read_text(), 'TOKEN=private\n')

    def test_concurrent_commit_is_never_clobbered_by_recovery(self):
        self.repository('gym'); (self.repos['gym']['path'] / 'other.py').write_text('independent\n')
        self.git('gym', 'add', '.'); self.git('gym', 'commit', '-m', 'independent')
        head = self.git('gym', 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(up.UpdateError, 'concurrent_git'): self.u.rollback_repository('gym')
        self.assertEqual(self.git('gym', 'rev-parse', 'HEAD'), head)

    def test_recovery_rejects_protected_path_even_if_state_is_modified(self):
        self.repository('food'); self.u.state['repositories']['food']['paths'].append('live.sqlite3')
        with self.assertRaisesRegex(up.UpdateError, 'unsafe_recovery'): self.u.rollback_repository('food')
        self.assertEqual((self.repos['food']['path'] / 'live.sqlite3').read_bytes(), b'new paid/user writes')

    def test_full_recovery_restores_all_refs_runtimes_updaters_and_keeps_late_writes(self):
        revisions = {n: self.repository(n)[0] for n in ('gym', 'food', 'supply', 'core')}
        self.u.state['attempted_repositories'] = list(revisions)
        self.u.state['affected'] = ['food_bot.service', 'progressor_core.service']
        self.u.state['switch_started'] = True
        for unit, old in [('food_bot.service', b'old runtime')]:
            p = up.SYSTEMD / (unit + '.d') / up.DROPIN; up.atomic_file(p, b'new runtime')
            self.u.state['dropins'][unit] = base64.b64encode(old).decode()
        up.atomic_file(up.UPDATERS / 'update_all.py', b'new updater')
        self.u.state['old_updaters']['update_all.py'] = base64.b64encode(b'old updater').decode()
        up.atomic_link(self.core / 'current', self.new)
        calls, process_patch = self.mock_processes()
        # Git uses subprocess too; only mock systemctl and retain real Git.
        original = up.command
        def processes(args, **kwargs):
            if args[0] == 'systemctl': calls.append(args); return 0, b''
            return original(args, **kwargs)
        with patch.object(up, 'command', side_effect=processes), patch.object(self.u, 'wait_health', return_value={}):
            self.u.rollback()
        for n, before in revisions.items():
            self.assertEqual(self.git(n, 'rev-parse', 'HEAD'), before)
            self.assertEqual((self.repos[n]['path'] / 'live.sqlite3').read_bytes(), b'new paid/user writes')
        self.assertEqual((self.core / 'current').resolve(), self.old)
        self.assertEqual((up.UPDATERS / 'update_all.py').read_bytes(), b'old updater')
        self.assertEqual((up.SYSTEMD / 'food_bot.service.d' / up.DROPIN).read_bytes(), b'old runtime')
        self.assertEqual(self.u.state['phase'], 'rolled_back')

    def test_interrupted_transaction_is_recovered_before_a_new_plan(self):
        self.repository('food'); self.u.state.update(attempted_repositories=['food'], switch_started=True)
        self.u.save('starting')
        fresh = up.Updater()
        original = up.command
        def processes(args, **kwargs): return (0, b'') if args[0] == 'systemctl' else original(args, **kwargs)
        with patch.object(up, 'command', side_effect=processes), patch.object(up.Updater, 'wait_health', return_value={}):
            fresh.recover_pending()
        self.assertEqual(self.git('food', 'rev-parse', 'HEAD'), self.u.state['repositories']['food']['before'])
        self.assertEqual(json.loads(up.STATE.read_text())['phase'], 'rolled_back')

    def test_check_does_not_mutate_an_interrupted_transaction(self):
        self.u.save('switching')
        with self.assertRaisesRegex(up.UpdateError, 'run_update_all_to_recover'):
            up.Updater(check=True).recover_pending()
        self.assertEqual(json.loads(up.STATE.read_text())['phase'], 'switching')

    def test_failed_dependency_preparation_never_stops_services(self):
        self.u.changed = {'gym'}
        with patch.object(self.u, 'plan'), patch.object(self.u, 'health', return_value={}), \
             patch.object(self.u, 'prepare_runtimes', side_effect=up.UpdateError('packages')), \
             patch.object(self.u, 'stop_units') as stop, patch.object(self.u, 'backup') as backup:
            with self.assertRaisesRegex(up.UpdateError, 'packages'): self.u.execute()
        stop.assert_not_called(); backup.assert_not_called()

    def test_noop_checks_status_without_packages_tests_or_restarts(self):
        with patch.object(self.u, 'plan'), patch.object(self.u, 'health', return_value={}), \
             patch.object(self.u, 'prepare_runtimes') as packages, patch.object(self.u, 'stop_units') as stop, \
             patch.object(self.u, 'show_status') as status:
            self.u.execute()
        stop.assert_not_called(); packages.assert_not_called(); status.assert_called_once()
        self.assertEqual(self.u.state['phase'], 'already_current')

    def test_abort_before_switch_does_not_kill_running_paid_supply_job(self):
        self.u.state.update(affected=['supply_bot.service', 'supply_assistant_worker.service'], worker_frozen=True)
        calls, process_patch = self.mock_processes()
        with process_patch, patch.object(self.u, 'wait_health', return_value={}): self.u.rollback()
        self.assertIn(['systemctl', 'thaw', 'supply_assistant_worker.service'], calls)
        self.assertFalse(any(a[:2] == ['systemctl', 'stop'] for a in calls))

    def test_idle_worker_is_frozen_then_stopped_without_a_new_claim_race(self):
        database = self.root / 'supply.sqlite3'
        with sqlite3.connect(database) as db: db.execute('CREATE TABLE assistant_jobs(status TEXT)')
        self.u.state['affected'] = ['supply_bot.service', 'supply_assistant_worker.service']
        calls, process_patch = self.mock_processes()
        with patch.object(up, 'DBS', {'supply': database}), process_patch: self.u.stop_units()
        self.assertEqual(calls, [['systemctl', 'stop', 'supply_bot.service'],
            ['systemctl', 'freeze', 'supply_assistant_worker.service'], ['systemctl', 'stop', 'supply_assistant_worker.service']])
        self.assertFalse(self.u.state['worker_frozen'])

    def test_runtime_override_quotes_systemd_expansion_and_keeps_arguments(self):
        text = up.runtime_dropin(['/old/python', '-m', 'uvicorn', 'backend:app', '--port', '8005'], '/new/python').decode()
        self.assertIn('ExecStart=\n', text); self.assertIn('"/new/python" "-m" "uvicorn"', text)
        self.assertIn('"8005"', text)
        self.assertIn('$$', up.runtime_dropin(['/x/python', '$bad%'], '/new/python').decode())

    def test_sqlite_online_backup_and_independent_restore_are_consistent(self):
        source = self.root / 'source.sqlite3'
        with sqlite3.connect(source) as db:
            db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE records(value TEXT)')
            db.execute("INSERT INTO records VALUES('keep me')")
        report = up.verified_database_backup(source, self.root / 'copy.sqlite3')
        self.assertEqual(report['counts'], {'records': 1}); self.assertEqual(report['restored_copy'], 'ok')
        with sqlite3.connect(source) as db: db.execute("INSERT INTO records VALUES('later write')")
        with sqlite3.connect(source) as db: self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 2)

    def test_offline_environment_has_no_live_keys_or_live_database(self):
        with patch.dict('os.environ', {'PROGRESSOR_GYM_BOT_TOKEN': 'live', 'DB_PATH': '/live/db'}):
            env = up.offline_environment(self.root)
        self.assertNotIn('PROGRESSOR_GYM_BOT_TOKEN', env); self.assertNotEqual(env['DB_PATH'], '/live/db')

    def test_core_only_still_checks_all_shared_helpers(self):
        self.u.selected = {'core'}
        for n in up.REPOS:
            p = self.root / ('candidate-' + n); p.mkdir(); self.u.candidates[n] = p
        (self.u.candidates['core'] / 'shared').mkdir()
        for src, dst in up.HELPERS.items():
            (self.u.candidates['core'] / 'shared' / src).write_text('canonical')
            for n in ('gym', 'food', 'supply'): (self.u.candidates[n] / dst).write_text('canonical')
        (self.u.candidates['core'] / 'shared/workout_metrics.py').write_text('metrics')
        (self.u.candidates['gym'] / 'progressor_workout_metrics.py').write_text('metrics')
        self.u.check_helpers()
        (self.u.candidates['food'] / 'progressor_client.py').write_text('incompatible')
        with self.assertRaisesRegex(up.UpdateError, 'incompatible_shared_helper:food'): self.u.check_helpers()

    def test_stable_updater_promotion_is_part_of_the_recoverable_transaction(self):
        self.u.changed = {'core'}; self.u.state['core_after'] = str(self.new)
        (self.new / 'deploy').mkdir(); (self.new / 'deploy/update_all.py').write_text('tested new updater')
        up.atomic_file(up.UPDATERS / 'update_all.py', b'old updater')
        self.u.state['old_updaters']['update_all.py'] = base64.b64encode(b'old updater').decode()
        with self.assertRaisesRegex(up.UpdateError, 'missing_tested_updater'): self.u.promote_updaters()
        calls, process_patch = self.mock_processes()
        with process_patch, patch.object(self.u, 'wait_health', return_value={}): self.u.rollback()
        self.assertEqual((up.UPDATERS / 'update_all.py').read_bytes(), b'old updater')

    def test_core_and_all_lock_exclusion(self):
        import fcntl
        with (self.core / 'ecosystem-update.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(up.os, 'geteuid', return_value=0), patch.object(up.signal, 'signal'):
                with self.assertRaisesRegex(up.UpdateError, 'another_update_is_running'): up.main(['--only', 'core'])

    def test_startup_failure_uses_full_transaction_recovery(self):
        self.repository('food')
        self.u.changed = {'food'}
        self.u.state.update(attempted_repositories=['food'], affected=['food_bot.service'], switch_started=True)
        original = up.command
        def processes(args, **kwargs): return (0, b'') if args[0] == 'systemctl' else original(args, **kwargs)
        with patch.object(self.u, 'plan'), patch.object(self.u, 'health', return_value={}), \
             patch.object(self.u, 'prepare_runtimes'), patch.object(self.u, 'test_candidates'), \
             patch.object(self.u, 'backup'), patch.object(self.u, 'prepare_switch'), \
             patch.object(self.u, 'stop_units'), patch.object(self.u, 'switch'), \
             patch.object(self.u, 'wait_health', side_effect=[up.UpdateError('startup_failed'), {}]), \
             patch.object(self.u, 'show_status'), patch.object(up, 'command', side_effect=processes), patch.object(up.signal, 'signal'):
            with self.assertRaisesRegex(up.UpdateError, 'startup_failed'): self.u.execute()
        self.assertEqual(self.u.state['phase'], 'rolled_back')
        self.assertEqual(self.git('food', 'rev-parse', 'HEAD'), self.u.state['repositories']['food']['before'])
        self.assertEqual((self.repos['food']['path'] / 'live.sqlite3').read_bytes(), b'new paid/user writes')

    def test_new_local_edit_during_preparation_aborts_without_clobbering_it(self):
        before, _ = self.repository('gym')
        self.u.rollback_repository('gym')
        (self.repos['gym']['path'] / 'code.py').write_text('manual edit\n')
        for n in ('core', 'food', 'supply'):
            self.u.state['repositories'][n] = {'before': before, 'target': before, 'paths': []}
        self.u.changed = {'gym'}
        with self.assertRaisesRegex(up.UpdateError, 'local_edit_during_preparation'): self.u.switch()
        self.assertEqual(self.u.state['attempted_repositories'], [])
        self.assertEqual((self.repos['gym']['path'] / 'code.py').read_text(), 'manual edit\n')

    def test_disk_guard_keeps_reserve_and_aborts_before_mutation(self):
        disk = type('Disk', (), {'total': 40 * 1024**3, 'free': 4 * 1024**3})()
        with patch.object(up.shutil, 'disk_usage', return_value=disk):
            up.ensure_space()
            with self.assertRaisesRegex(up.UpdateError, 'not_enough_disk_space'): up.ensure_space(1)

    def test_retention_removes_only_older_verified_owned_archives(self):
        up.BACKUPS.mkdir()
        for i in range(5):
            folder = up.BACKUPS / ('20261008T00000' + str(i) + 'Z-123-all-update'); folder.mkdir()
            (folder / 'databases').mkdir(); (folder / 'code-config.tar.gz').write_bytes(b'code')
            (folder / 'manifest.json').write_text(json.dumps({'databases': {n: {'restored_copy': 'ok'} for n in up.DBS}}))
            archive = folder.with_suffix('.tar.gz'); archive.write_bytes(str(i).encode())
            (folder / 'archive.sha256').write_text(up.sha(archive))
        unrelated = up.BACKUPS / 'native-release.tar.gz'; unrelated.write_bytes(b'keep')
        incomplete = up.BACKUPS / '20261007T000000Z-123-all-update.tar.gz'; incomplete.write_bytes(b'keep')
        self.u.prune_backups()
        self.assertEqual(len(list(up.BACKUPS.glob('20261008*-all-update.tar.gz'))), 3)
        self.assertTrue(unrelated.exists()); self.assertTrue(incomplete.exists())
