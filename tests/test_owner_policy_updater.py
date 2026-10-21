"""Owner-policy deployment epoch: temporary files and mocked process/Git control only."""
import base64
import importlib.util
import json
import os
import stat
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('owner_policy_updater', Path(__file__).parents[1] / 'deploy/update_all.py')
up = importlib.util.module_from_spec(spec)
try:
    import fcntl
except ModuleNotFoundError:
    # These tests never acquire a lock. Keep the production-only import local.
    with patch.dict(sys.modules, {'fcntl': types.ModuleType('fcntl')}):
        spec.loader.exec_module(up)
else:
    spec.loader.exec_module(up)


class OwnerPolicyUpdater(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = self.root / 'core'
        self.current = self.core / 'current'
        self.old = self.core / 'releases/old'
        self.new = self.core / 'releases/new'
        for release in (self.current, self.old, self.new):
            self.release(release)
        self.gate = self.root / 'owner-consent-v1-ready'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {'CORE': self.core, 'STATE': self.core / 'updater/state.json',
                            'UPDATERS': self.core / 'updater', 'TRANSACTIONS': self.root / 'transactions',
                            'SYSTEMD': self.root / 'systemd', 'OWNER_POLICY_GATE': self.gate,
                            'MEAL_CHOICE_GATE':self.root/'next-meal-v1-ready'}.items():
            self.stack.enter_context(patch.object(up, name, value))
        self.stack.enter_context(patch.object(up, 'emit'))
        self.stack.enter_context(patch.object(up, 'atomic_json', side_effect=self.write_state))
        self.updater_source = b'OWNER_POLICY_UPDATER_PROTOCOL = 1\n# current guarded updater\n'
        up.UPDATERS.mkdir(parents=True)
        (up.UPDATERS / 'update_all.py').write_bytes(self.updater_source)
        self.u = up.Updater()
        self.u.folder.mkdir(parents=True)
        self.u.state['core_before'] = str(self.old)
        self.u.state['core_after'] = str(self.new)
        self.u.candidates = {'core': self.new}
        self.u.state['affected'] = ['progressor_core.service']
        self.u.state['switch_started'] = True
        self.live_data = self.root / 'live.sqlite3'
        self.live_data.write_bytes(b'late user/payment records')
        self.dropin = up.SYSTEMD / 'progressor_core.service.d' / up.DROPIN
        self.dropin.parent.mkdir(parents=True)
        self.dropin.write_bytes(b'current release runtime and SQLite library')
        self.u.state['dropins']['progressor_core.service'] = base64.b64encode(b'old runtime').decode()

    def write_state(self, path, value):
        # Windows cannot fsync a directory. Exercise transaction persistence here,
        # while the Linux atomic-write implementation has its own existing tests.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def release(self, path, protocol=1, updater=1):
        (path / 'progressor_core').mkdir(parents=True, exist_ok=True)
        (path / 'deploy').mkdir(exist_ok=True)
        (path / 'progressor_core/owner_policy.py').write_text('OWNER_POLICY_PROTOCOL = ' + str(protocol) + '\n')
        (path / 'deploy/update_all.py').write_text('OWNER_POLICY_UPDATER_PROTOCOL = ' + str(updater) + '\n')
        (path / 'deploy/update_progressor.py').write_text('# delegate to installed updater\n')

    def enable_gate(self):
        self.gate.write_text('ready\n')

    def assert_retained(self):
        self.assertEqual(self.dropin.read_bytes(), b'current release runtime and SQLite library')
        self.assertEqual((up.UPDATERS / 'update_all.py').read_bytes(), self.updater_source)
        self.assertEqual(self.live_data.read_bytes(), b'late user/payment records')
        self.assertEqual(self.u.state['phase'], 'rolling_back')
        self.assertFalse(self.u.state['database_restored'])

    def test_gate_is_independent_of_financial_epoch_and_has_fixed_production_path(self):
        self.assertEqual(str(up.OWNER_POLICY_GATE), str(self.gate))
        self.release(self.new, protocol=0, updater=0)
        with patch.object(up, 'financial_epoch_required', side_effect=AssertionError('financial epoch used')):
            up.check_owner_policy_epoch(self.u.candidates)
            self.enable_gate()
            with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
                up.check_owner_policy_epoch(self.u.candidates)

    def test_enabled_gate_requires_literal_top_level_protocol(self):
        self.enable_gate()
        source = self.new / 'progressor_core/owner_policy.py'
        invalid = ['', 'OWNER_POLICY_PROTOCOL = 0\n', 'OWNER_POLICY_PROTOCOL = True\n',
                   'OWNER_POLICY_PROTOCOL = "1"\n', 'OWNER_POLICY_PROTOCOL = int(1)\n',
                   'OWNER_POLICY_PROTOCOL: int = 1\n', 'if True:\n    OWNER_POLICY_PROTOCOL = 1\n',
                   'def version():\n    OWNER_POLICY_PROTOCOL = 1\n',
                   'OWNER_POLICY_PROTOCOL = 1\nOWNER_POLICY_PROTOCOL = 0\n',
                   'OWNER_POLICY_PROTOCOL = 1\nOWNER_POLICY_PROTOCOL += 1\n',
                   'OWNER_POLICY_PROTOCOL = (\n']
        for text in invalid:
            with self.subTest(source=text):
                source.write_text(text)
                with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
                    up.check_owner_policy_epoch(self.u.candidates)
        source.unlink()
        with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
            up.check_owner_policy_epoch(self.u.candidates)
        source.write_bytes(b'\xff\xfeinvalid python')
        with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
            up.check_owner_policy_epoch(self.u.candidates)

    def test_compatible_and_future_protocol_are_read_without_executing_candidate(self):
        self.enable_gate()
        for version in (1, 2):
            (self.new / 'progressor_core/owner_policy.py').write_text(
                'OWNER_POLICY_PROTOCOL = ' + str(version) + '\nraise RuntimeError("must never execute")\n')
            up.check_owner_policy_epoch(self.u.candidates)

    def test_missing_or_unguarded_candidate_updater_is_rejected(self):
        self.enable_gate()
        updater = self.new / 'deploy/update_all.py'
        for value in (None, 'OWNER_POLICY_UPDATER_PROTOCOL = 0\n', 'OWNER_POLICY_UPDATER_PROTOCOL = True\n'):
            if value is None:
                updater.unlink()
            else:
                updater.write_text(value)
            with self.subTest(value=value), self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_updater'):
                up.check_owner_policy_epoch(self.u.candidates)

    def test_gate_access_error_fails_closed_and_dangling_gate_is_enabled(self):
        with patch.object(Path, 'lstat', side_effect=PermissionError('test denial')):
            with self.assertRaisesRegex(up.UpdateError, 'owner_policy_gate_unavailable'):
                up.owner_policy_epoch_required()
        # lstat succeeds for a dangling symlink; no target contents are consulted.
        with patch.object(Path, 'lstat', return_value=object()):
            self.assertTrue(up.owner_policy_epoch_required())

    def test_prepare_and_switch_recheck_gate_before_any_promotion(self):
        self.release(self.new, protocol=0)
        up.check_owner_policy_epoch(self.u.candidates)
        self.enable_gate()
        with patch.object(self.u, 'save') as save, patch.object(up, 'git') as git, \
                patch.object(up, 'atomic_link') as link, patch.object(up, 'command') as command:
            for operation in (self.u.prepare_switch, self.u.switch):
                with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
                    operation()
            save.assert_not_called()
            git.assert_not_called()
            link.assert_not_called()
            command.assert_not_called()

    def test_helper_check_runs_owner_guard_before_financial_or_shared_helpers(self):
        self.release(self.new, protocol=0)
        self.enable_gate()
        with patch.object(up, 'check_financial_epoch') as financial:
            with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_protocol'):
                self.u.check_helpers()
            financial.assert_not_called()

    def test_updater_promotion_rechecks_both_markers_before_writing_any_file(self):
        self.enable_gate()
        self.u.changed = {'core'}
        for protocol, updater in ((0, 1), (1, 0)):
            self.release(self.new, protocol=protocol, updater=updater)
            with self.subTest(protocol=protocol, updater=updater), patch.object(up, 'atomic_file') as write:
                with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_'):
                    self.u.promote_updaters()
                write.assert_not_called()

    def test_incompatible_old_core_retains_current_code_runtime_and_updater(self):
        self.enable_gate()
        self.release(self.old, protocol=0)
        self.u.state['attempted_repositories'] = ['core', 'food']
        with patch.object(self.u, 'rollback_repository') as restore, patch.object(up, 'atomic_link') as link, \
                patch.object(up, 'atomic_file') as write, patch.object(up, 'command') as command, \
                patch.object(self.u, 'wait_health', return_value={'core': 'ok'}):
            with self.assertRaisesRegex(up.UpdateError, 'recovery_requires_attention_owner_policy_protocol'):
                self.u.rollback()
            restore.assert_not_called()
            link.assert_not_called()
            write.assert_not_called()
            self.assertEqual(command.call_args_list[0].args[0], ['systemctl', 'start', 'progressor_core.service'])
            self.assertEqual(command.call_count, 1)
        self.assert_retained()
        self.assertEqual(self.u.state['owner_policy_retained_core'], str(self.current.resolve()))

    def test_old_unguarded_or_missing_updater_is_never_restored(self):
        self.enable_gate()
        for old in (None, base64.b64encode(b'# old unguarded updater\n').decode(), 'invalid base64!'):
            self.u.state['old_updaters']['update_all.py'] = old
            with self.subTest(old=old), patch.object(up, 'atomic_file') as write, \
                    patch.object(up, 'atomic_link') as link, patch.object(up, 'command'), \
                    patch.object(self.u, 'wait_health', return_value={}):
                with self.assertRaisesRegex(up.UpdateError, 'recovery_requires_attention_owner_policy_protocol'):
                    self.u.rollback()
                write.assert_not_called()
                link.assert_not_called()
            self.assert_retained()

    def test_compatible_rollback_preserves_existing_recovery_behavior_and_live_data(self):
        self.enable_gate()
        previous_updater = b'OWNER_POLICY_UPDATER_PROTOCOL = 1\n# previous guarded updater\n'
        self.u.state['old_updaters']['update_all.py'] = base64.b64encode(previous_updater).decode()
        with patch.object(up, 'atomic_link') as link, patch.object(up, 'command') as command, \
                patch.object(self.u, 'wait_health', return_value={'core': 'ok'}):
            self.u.rollback()
            link.assert_called_once_with(self.core / 'current', str(self.old))
            self.assertIn(['systemctl', 'stop', 'progressor_core.service'], [c.args[0] for c in command.call_args_list])
        self.assertEqual(self.dropin.read_bytes(), b'old runtime')
        self.assertEqual((up.UPDATERS / 'update_all.py').read_bytes(), previous_updater)
        self.assertEqual(self.live_data.read_bytes(), b'late user/payment records')
        self.assertEqual(self.u.state['phase'], 'rolled_back')
        self.assertFalse(self.u.state['database_restored'])

    def test_core_repository_rollback_rejects_legacy_commit_before_any_git_write(self):
        self.enable_gate()
        self.u.state['repositories']['core'] = {'before': 'a' * 40, 'target': 'b' * 40, 'paths': []}
        for source in (b'OWNER_POLICY_PROTOCOL = 0\n', b'OWNER_POLICY_PROTOCOL = True\n', b'bad python ('):
            with self.subTest(source=source), patch.object(up, 'command', return_value=(0, source)) as command, \
                    patch.object(up, 'git') as git:
                with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_rollback:core'):
                    self.u.rollback_repository('core')
                git.assert_not_called()
                self.assertEqual(command.call_args.args[0][3], 'show')

    def test_core_repository_rollback_requires_guarded_updater_in_old_commit(self):
        self.enable_gate()
        self.u.state['repositories']['core'] = {'before': 'a' * 40, 'target': 'b' * 40, 'paths': []}
        replies = [(0, b'OWNER_POLICY_PROTOCOL = 1\n'), (0, b'# old unguarded updater\n')]
        with patch.object(up, 'command', side_effect=replies), patch.object(up, 'git') as git:
            with self.assertRaisesRegex(up.UpdateError, 'incompatible_owner_policy_rollback:core'):
                self.u.rollback_repository('core')
            git.assert_not_called()

    def test_compatible_repository_rollback_can_restore_the_old_ref(self):
        self.enable_gate()
        before, target = 'a' * 40, 'b' * 40
        self.u.state['repositories']['core'] = {'before': before, 'target': target, 'paths': []}
        replies = [(0, b'OWNER_POLICY_PROTOCOL = 1\n'), (0, b'OWNER_POLICY_UPDATER_PROTOCOL = 1\n')]
        with patch.object(up, 'command', side_effect=replies), patch.object(up, 'git', return_value=target) as git:
            self.u.rollback_repository('core')
            self.assertEqual(git.call_args.args, ('core', 'update-ref', 'refs/heads/main', before, target))

    def test_pending_incomplete_rollback_retains_compatible_current_and_requires_attention(self):
        self.enable_gate()
        self.release(self.old, protocol=0)
        self.u.save('rolling_back')
        fresh = up.Updater()
        with patch.object(up, 'atomic_link') as link, patch.object(up, 'atomic_file') as write, \
                patch.object(up, 'command') as command, patch.object(up.Updater, 'wait_health', return_value={}):
            with self.assertRaisesRegex(up.UpdateError, 'recovery_requires_attention_owner_policy_protocol'):
                fresh.recover_pending()
            link.assert_not_called()
            write.assert_not_called()
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0], ['systemctl', 'start', 'progressor_core.service'])
        self.u = fresh
        self.assert_retained()
        self.assertEqual(json.loads(up.STATE.read_text())['phase'], 'rolling_back')

    def test_incomplete_recovery_never_starts_incompatible_current_or_unguarded_updater(self):
        self.enable_gate()
        self.release(self.old, protocol=0)
        for protocol, installed in ((0, self.updater_source), (1, b'# unguarded updater\n')):
            self.release(self.current, protocol=protocol)
            (up.UPDATERS / 'update_all.py').write_bytes(installed)
            with self.subTest(protocol=protocol), patch.object(up, 'command') as command, \
                    patch.object(up, 'atomic_link') as link, patch.object(up, 'atomic_file') as write:
                with self.assertRaisesRegex(up.UpdateError, 'recovery_requires_attention_owner_policy_protocol'):
                    self.u.rollback()
                command.assert_not_called()
                link.assert_not_called()
                write.assert_not_called()
            self.assertEqual(self.live_data.read_bytes(), b'late user/payment records')
            self.assertFalse(self.u.state['database_restored'])


class PersistentGateBackups(unittest.TestCase):
    """Real small tar archives; only inaccessible filesystem cases are injected."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.financial = self.root / 'bundle-v2-ready'
        self.owner = self.root / 'owner-consent-v1-ready'
        self.meal = self.root / 'next-meal-v1-ready'
        self.archive = self.root / 'code-config.tar'
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(up, 'OWNER_POLICY_GATE', self.owner))
        stack.enter_context(patch.object(up, 'MEAL_CHOICE_GATE', self.meal))
        stack.enter_context(patch.object(up, 'DBS', {'core': self.root / 'core.sqlite3'}))

    def write_gates(self):
        self.financial.write_bytes(b'financial-ready\n')
        self.owner.write_bytes(b'owner-ready\n\x00private-recovery-marker')
        for path in (self.financial, self.owner):
            path.chmod(0o600)

    def archive_gates(self, gates):
        with tarfile.open(self.archive, 'w') as archive:
            up.add_persistent_gates(archive, gates)

    def test_archive_preserves_both_present_gate_bytes_mode_and_manifest(self):
        self.write_gates()
        gates = up.capture_persistent_gates()
        self.archive_gates(gates)
        with tarfile.open(self.archive) as archive:
            up.verify_persistent_gates(archive, gates)
            self.assertEqual(len(archive.getmembers()), 2)
            for path in (self.financial, self.owner):
                member = archive.getmember('var/lib/progressor/' + path.name)
                self.assertEqual(member.mode, stat.S_IMODE(path.stat().st_mode))
                with archive.extractfile(member) as stream:
                    self.assertEqual(stream.read(), path.read_bytes())
        manifest = up.persistent_gate_manifest(gates)
        json.dumps(manifest)
        self.assertTrue(manifest[self.financial.name]['present']);self.assertTrue(manifest[self.owner.name]['present'])
        self.assertFalse(manifest[self.meal.name]['present'])
        self.assertTrue(all('content' not in value for value in manifest.values()))

    def test_absent_gates_are_explicit_and_valid_before_activation(self):
        gates = up.capture_persistent_gates()
        self.assertEqual({name: record['present'] for name, record in gates.items()},
                         {'bundle-v2-ready': False, 'owner-consent-v1-ready': False,'next-meal-v1-ready':False})
        self.archive_gates(gates)
        with tarfile.open(self.archive) as archive:
            up.verify_persistent_gates(archive, gates)
            self.assertEqual(archive.getmembers(), [])

    def test_one_missing_gate_is_recorded_without_losing_the_other(self):
        self.write_gates()
        self.owner.unlink()
        gates = up.capture_persistent_gates()
        self.archive_gates(gates)
        with tarfile.open(self.archive) as archive:
            up.verify_persistent_gates(archive, gates)
            self.assertEqual([item.name for item in archive.getmembers()],
                             ['var/lib/progressor/bundle-v2-ready'])

    def test_invalid_directory_oversized_and_symlink_gate_refuse_backup(self):
        self.owner.mkdir()
        with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_invalid'):
            up.capture_persistent_gates()
        self.owner.rmdir()
        self.owner.write_bytes(b'x' * 4097)
        with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_invalid'):
            up.capture_persistent_gates()
        self.owner.write_bytes(b'ready')
        original = Path.lstat
        def symlink_info(path, *args, **kwargs):
            return types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_size=5) if path == self.owner else original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', symlink_info):
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_invalid'):
                up.capture_persistent_gates()
        if os.name != 'nt':
            self.owner.chmod(0o666)
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_invalid'):
                up.capture_persistent_gates()

    def test_unreadable_gate_is_never_silently_treated_as_absent(self):
        self.write_gates()
        original = Path.open
        def denied(path, *args, **kwargs):
            if path == self.owner:
                raise PermissionError('synthetic read denial')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', denied):
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_unavailable'):
                up.capture_persistent_gates()

    def test_modified_archive_bytes_and_mode_fail_verification(self):
        self.write_gates()
        gates = up.capture_persistent_gates()
        for field, value in (('content', b'changed'), ('mode', 0o444)):
            changed = {name: dict(record) for name, record in gates.items()}
            changed[self.owner.name][field] = value
            if field == 'content':
                changed[self.owner.name]['size'] = len(value)
            self.archive_gates(changed)
            with self.subTest(field=field), tarfile.open(self.archive) as archive:
                with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_mismatch'):
                    up.verify_persistent_gates(archive, gates)

    def test_duplicate_archive_gate_fails_verification(self):
        self.write_gates()
        gates = up.capture_persistent_gates()
        self.archive_gates(gates)
        with tarfile.open(self.archive, 'a') as archive:
            up.add_persistent_gates(archive, gates)
        with tarfile.open(self.archive) as archive:
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_mismatch'):
                up.verify_persistent_gates(archive, gates)

    def test_gate_activation_or_removal_during_backup_refuses_old_manifest(self):
        absent = up.capture_persistent_gates()
        self.archive_gates(absent)
        self.write_gates()
        with tarfile.open(self.archive) as archive:
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_changed_during_backup'):
                up.verify_persistent_gates(archive, absent)
        present = up.capture_persistent_gates()
        self.archive_gates(present)
        self.owner.unlink()
        with tarfile.open(self.archive) as archive:
            with self.assertRaisesRegex(up.UpdateError, 'backup_persistent_gate_changed_during_backup'):
                up.verify_persistent_gates(archive, present)


if __name__ == '__main__':
    unittest.main()
