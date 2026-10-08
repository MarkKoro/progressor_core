import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('core_updater', Path(__file__).parents[1] / 'deploy/update_progressor.py')
updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)


class CoreEntryPoint(unittest.TestCase):
    def test_core_entry_uses_the_same_transaction_and_lock_engine(self):
        engine = types.ModuleType('update_all'); engine.main = Mock()
        with patch.dict(sys.modules, {'update_all': engine}), patch.object(sys, 'argv', ['updatecore']): updater.main()
        engine.main.assert_called_once_with(['--only', 'core'])

    def test_check_is_forwarded_without_switching_scope(self):
        engine = types.ModuleType('update_all'); engine.main = Mock()
        with patch.dict(sys.modules, {'update_all': engine}), patch.object(sys, 'argv', ['update-progressor', '--check']): updater.main()
        engine.main.assert_called_once_with(['--only', 'core', '--check'])

    def test_engine_failure_is_not_silently_ignored(self):
        engine = types.ModuleType('update_all'); engine.main = Mock(side_effect=RuntimeError('verification_failed'))
        with patch.dict(sys.modules, {'update_all': engine}), patch.object(sys, 'argv', ['updatecore']):
            with self.assertRaisesRegex(RuntimeError, 'verification_failed'): updater.main()
