"""Separate plan/reset recovery epoch: local files/tars and mocked process control."""
import base64,json,os,stat,tarfile,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from test_owner_policy_updater import up


class MealChoiceUpdater(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.core=self.root/'core';self.current=self.core/'current';self.old=self.core/'old';self.new=self.core/'new';self.food=self.root/'food'
        for path in (self.current,self.old,self.new):self.release(path)
        self.food.mkdir();(self.food/'db.py').write_text('FOOD_RESET_PROTOCOL = 1\n')
        self.gate=self.root/'next-meal-v1-ready';self.owner=self.root/'owner-consent-v1-ready'
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in {'CORE':self.core,'STATE':self.root/'state.json','UPDATERS':self.core/'updater','TRANSACTIONS':self.root/'transactions','SYSTEMD':self.root/'systemd','OWNER_POLICY_GATE':self.owner,'MEAL_CHOICE_GATE':self.gate,'DBS':{'core':self.root/'core.db'}}.items():self.stack.enter_context(patch.object(up,name,value))
        self.stack.enter_context(patch.object(up,'REPOS',{'core':{'path':self.root/'core-repository'},'food':{'path':self.food}}))
        self.stack.enter_context(patch.object(up,'emit'))
        def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
        self.stack.enter_context(patch.object(up,'atomic_json',side_effect=write))
        up.UPDATERS.mkdir(parents=True);self.updater=b'MEAL_CHOICE_UPDATER_PROTOCOL=1\nOWNER_POLICY_UPDATER_PROTOCOL=1\n'
        (up.UPDATERS/'update_all.py').write_bytes(self.updater)
        self.u=up.Updater();self.u.folder.mkdir(parents=True)
        self.u.state.update(core_before=str(self.old),core_after=str(self.new),affected=['progressor_core.service','food_bot.service'],switch_started=True)
        self.u.candidates={'core':self.new,'food':self.food}
        self.live=self.root/'live.db';self.live.write_bytes(b'later user/paid records')
    def release(self,path,planner=1,updater=1,owner=1):
        (path/'progressor_core').mkdir(parents=True,exist_ok=True);(path/'deploy').mkdir(exist_ok=True)
        (path/'progressor_core/next_meal.py').write_text(f'NEXT_MEAL_PROTOCOL={planner}\n')
        (path/'progressor_core/owner_policy.py').write_text(f'OWNER_POLICY_PROTOCOL={owner}\n')
        (path/'deploy/update_all.py').write_text(f'MEAL_CHOICE_UPDATER_PROTOCOL={updater}\nOWNER_POLICY_UPDATER_PROTOCOL=1\n')
        (path/'deploy/update_progressor.py').write_text('# delegate\n')
    def enable(self):self.gate.write_bytes(b'compatible verified owner reset v1\n');self.gate.chmod(0o600)
    def test_gate_is_separate_and_literal_markers_fail_closed_without_execution(self):
        self.release(self.new,planner=0);up.check_meal_choice_epoch(self.u.candidates);self.enable()
        for marker,relative in (('NEXT_MEAL_PROTOCOL','progressor_core/next_meal.py'),('MEAL_CHOICE_UPDATER_PROTOCOL','deploy/update_all.py')):
            self.release(self.new)
            for value in ('0','True','"1"','int(1)'):
                (self.new/relative).write_text(f'{marker}={value}\n')
                with self.subTest(marker=marker,value=value),self.assertRaisesRegex(up.UpdateError,'incompatible_meal_choice_protocol'):up.check_meal_choice_epoch(self.u.candidates)
            for text in (f'if True:\n    {marker}=1\n',f'{marker}=1\n{marker}=0\n'):
                (self.new/relative).write_text(text)
                with self.assertRaises(up.UpdateError):up.check_meal_choice_epoch(self.u.candidates)
        self.release(self.new);(self.new/'progressor_core/next_meal.py').write_text('NEXT_MEAL_PROTOCOL=2\nraise RuntimeError("never execute")\n');up.check_meal_choice_epoch(self.u.candidates)
    def test_old_food_reset_code_and_missing_candidate_are_rejected(self):
        self.enable();(self.food/'db.py').write_text('# old purge code\n')
        with self.assertRaisesRegex(up.UpdateError,'FOOD_RESET_PROTOCOL'):up.check_meal_choice_epoch(self.u.candidates)
        with self.assertRaisesRegex(up.UpdateError,'missing_meal_choice_candidate:food'):up.check_meal_choice_epoch({'core':self.new})
    def test_gate_access_error_is_not_absence(self):
        with patch.object(Path,'lstat',side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(up.UpdateError,'meal_choice_gate_unavailable'):up.meal_choice_epoch_required()
    def test_prepare_helpers_and_switch_recheck_before_any_mutation(self):
        self.enable();self.release(self.new,planner=0)
        with patch.object(self.u,'save') as save,patch.object(up,'git') as git,patch.object(up,'atomic_link') as link,patch.object(up,'command') as command:
            for function in (self.u.check_helpers,self.u.prepare_switch,self.u.switch):
                with self.assertRaisesRegex(up.UpdateError,'incompatible_meal_choice_protocol'):function()
            save.assert_not_called();git.assert_not_called();link.assert_not_called();command.assert_not_called()
    def test_updater_promotion_rechecks_current_food_before_writing(self):
        self.enable();self.u.changed={'core'};(self.food/'db.py').write_text('FOOD_RESET_PROTOCOL=0\n')
        with patch.object(up,'atomic_file') as write:
            with self.assertRaisesRegex(up.UpdateError,'FOOD_RESET_PROTOCOL'):self.u.promote_updaters()
            write.assert_not_called()
    def test_repository_rollback_checks_core_and_food_commit_before_git_write(self):
        self.enable()
        for name in ('core','food'):
            self.u.state['repositories'][name]={'before':'a'*40,'target':'b'*40,'paths':[]}
            with patch.object(up,'command',return_value=(0,b'# old incompatible code\n')),patch.object(up,'git') as git:
                with self.assertRaisesRegex(up.UpdateError,'incompatible_meal_choice_rollback:'+name):self.u.rollback_repository(name)
                git.assert_not_called()
    def retained(self):
        self.assertEqual(self.live.read_bytes(),b'later user/paid records');self.assertEqual((up.UPDATERS/'update_all.py').read_bytes(),self.updater)
        self.assertTrue(self.gate.exists());self.assertFalse(self.u.state['database_restored']);self.assertEqual(self.u.state['phase'],'rolling_back')
    def test_old_planner_fallback_retains_compatible_current_and_all_runtime_state(self):
        self.enable();self.release(self.old,planner=0)
        with patch.object(self.u,'rollback_repository') as restore,patch.object(up,'atomic_file') as write,patch.object(up,'atomic_link') as link,patch.object(up,'command') as command,patch.object(self.u,'wait_health',return_value={'core':'ok'}):
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):self.u.rollback()
            restore.assert_not_called();write.assert_not_called();link.assert_not_called();self.assertEqual(command.call_count,2)
        self.retained()
    def test_old_food_purge_fallback_is_never_restored(self):
        self.enable();self.u.state['attempted_repositories']=['food'];self.u.state['repositories']['food']={'before':'a'*40}
        with patch.object(up,'command',return_value=(0,b'# old purge\n')),patch.object(self.u,'rollback_repository') as restore,patch.object(up,'atomic_link') as link,patch.object(self.u,'wait_health',return_value={}):
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):self.u.rollback()
            restore.assert_not_called();link.assert_not_called()
        self.retained()
    def test_missing_unguarded_old_updater_retains_current(self):
        self.enable()
        for old in (None,'not base64!',base64.b64encode(b'# legacy updater\n').decode()):
            self.u.state['old_updaters']['update_all.py']=old
            with patch.object(up,'atomic_file') as write,patch.object(up,'command'),patch.object(self.u,'wait_health',return_value={}):
                with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):self.u.rollback()
                write.assert_not_called()
            self.retained()
    def test_incompatible_current_does_not_restart_or_replace_anything(self):
        self.enable();self.release(self.old,planner=0);(self.food/'db.py').write_text('FOOD_RESET_PROTOCOL=0\n')
        with patch.object(up,'command') as command,patch.object(up,'atomic_file') as write,patch.object(up,'atomic_link') as link:
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):self.u.rollback()
            command.assert_not_called();write.assert_not_called();link.assert_not_called()
    def test_interrupted_recovery_uses_same_guard_and_keeps_gate(self):
        self.enable();self.release(self.old,planner=0);self.u.save('rolling_back');fresh=up.Updater()
        with patch.object(up,'command'),patch.object(up.Updater,'wait_health',return_value={}),patch.object(up,'atomic_link') as link:
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):fresh.recover_pending()
            link.assert_not_called()
        self.assertTrue(self.gate.exists());self.assertEqual(json.loads(up.STATE.read_text())['phase'],'rolling_back')
    def test_compatible_recovery_preserves_late_db_records_and_feature_gate(self):
        self.enable();self.u.state['old_updaters']['update_all.py']=base64.b64encode(self.updater).decode()
        with patch.object(up,'atomic_link') as link,patch.object(up,'atomic_file'),patch.object(up,'command'),patch.object(self.u,'wait_health',return_value={}):
            self.u.rollback();link.assert_called_once_with(self.core/'current',str(self.old))
        self.assertEqual(self.live.read_bytes(),b'later user/paid records');self.assertTrue(self.gate.exists());self.assertEqual(self.u.state['phase'],'rolled_back')
    def test_both_recovery_guards_check_current_against_other_active_epoch(self):
        self.enable();self.owner.write_text('owner ready');self.release(self.old,planner=0);self.release(self.current,owner=0)
        with patch.object(up,'command') as command:
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_meal_choice_protocol'):self.u.rollback()
            command.assert_not_called()
        self.release(self.current);self.release(self.old,owner=0)
        (up.UPDATERS/'update_all.py').write_bytes(b'OWNER_POLICY_UPDATER_PROTOCOL=1\n')
        with patch.object(up,'command') as command:
            with self.assertRaisesRegex(up.UpdateError,'recovery_requires_attention_owner_policy_protocol'):self.u.rollback()
            command.assert_not_called()
    def test_third_gate_real_tar_restore_bytes_mode_and_manifest(self):
        self.enable();archive=self.root/'code.tar';gates=up.capture_persistent_gates()
        with tarfile.open(archive,'w') as tar:up.add_persistent_gates(tar,gates)
        with tarfile.open(archive) as tar:
            up.verify_persistent_gates(tar,gates);entry=tar.getmember('var/lib/progressor/'+self.gate.name)
            self.assertEqual(entry.mode,stat.S_IMODE(self.gate.stat().st_mode));self.assertEqual(tar.extractfile(entry).read(),self.gate.read_bytes())
        manifest=up.persistent_gate_manifest(gates);self.assertTrue(manifest[self.gate.name]['present']);self.assertNotIn('content',manifest[self.gate.name])
    def test_third_gate_modified_archive_or_removed_during_backup_is_rejected(self):
        self.enable();archive=self.root/'code.tar';gates=up.capture_persistent_gates();changed={name:dict(record) for name,record in gates.items()};changed[self.gate.name]['content']=b'changed';changed[self.gate.name]['size']=7
        with tarfile.open(archive,'w') as tar:up.add_persistent_gates(tar,changed)
        with tarfile.open(archive) as tar:
            with self.assertRaisesRegex(up.UpdateError,'backup_persistent_gate_mismatch'):up.verify_persistent_gates(tar,gates)
        with tarfile.open(archive,'w') as tar:up.add_persistent_gates(tar,gates)
        self.gate.unlink()
        with tarfile.open(archive) as tar:
            with self.assertRaisesRegex(up.UpdateError,'backup_persistent_gate_changed_during_backup'):up.verify_persistent_gates(tar,gates)
