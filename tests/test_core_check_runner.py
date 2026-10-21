"""Causal host-state isolation; real gates and application code are untouched."""
import gc
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from progressor_core import owner_policy
import test_selected_privacy as privacy_fixture

spec = importlib.util.spec_from_file_location('isolated_core_check_runner',
    Path(__file__).parents[1] / 'deploy/run_core_checks.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CoreCheckRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = self.root / 'simulated-host-owner-ready'
        self.host.write_bytes(b'1\n')
        self.empty = self.root / 'isolated-defaults'
        self.empty.mkdir()

    def existing_positive_fixture(self, *, own_gate=None):
        # Reuse the original assertion body. Only collect SQLite handle cycles
        # before its existing cleanup for Windows filesystem portability.
        case = privacy_fixture.SelectedPrivacy('test_weight_choice_applies_all_owners_preserves_history_fields_and_goal')
        case.setUp()
        try:
            if own_gate is not None:
                case.store.owner_policy_gate = own_gate
            case.test_weight_choice_applies_all_owners_preserves_history_fields_and_goal()
        finally:
            gc.collect()
            case.tearDown()

    def test_same_legacy_fixture_fails_with_simulated_host_gate_and_passes_in_runner(self):
        with patch.object(owner_policy, 'OWNER_POLICY_GATE', self.host):
            with self.assertRaisesRegex(AssertionError, '0 != 1'):
                self.existing_positive_fixture()
            with runner.isolated_readiness_defaults(self.empty):
                self.existing_positive_fixture()
            self.assertEqual(owner_policy.OWNER_POLICY_GATE, self.host)
        self.assertEqual(self.host.read_bytes(), b'1\n')

    def test_explicit_strict_fixture_is_not_disabled_by_default_isolation(self):
        with runner.isolated_readiness_defaults(self.empty):
            with self.assertRaisesRegex(AssertionError, '0 != 1'):
                self.existing_positive_fixture(own_gate=self.host)
        self.assertEqual(self.host.read_bytes(), b'1\n')

    def test_optional_next_meal_default_and_exception_restore_are_scoped(self):
        optional = types.ModuleType('progressor_core.next_meal')
        optional.NEXT_MEAL_GATE = self.host
        # A standalone optional-module double keeps this regression compatible
        # with the current release, before the next-meal module is installed.
        exec('def enabled(store):\n    return getattr(store,"next_meal_gate",NEXT_MEAL_GATE).exists()', optional.__dict__)
        with patch.dict(sys.modules, {'progressor_core.next_meal': optional}), \
                patch.object(owner_policy, 'OWNER_POLICY_GATE', self.host):
            self.assertTrue(optional.enabled(types.SimpleNamespace()))
            with self.assertRaisesRegex(RuntimeError, 'intentional'):
                with runner.isolated_readiness_defaults(self.empty):
                    self.assertFalse(owner_policy.enforced(types.SimpleNamespace()))
                    self.assertFalse(optional.enabled(types.SimpleNamespace()))
                    self.assertTrue(optional.enabled(types.SimpleNamespace(next_meal_gate=self.host)))
                    raise RuntimeError('intentional')
            self.assertEqual(owner_policy.OWNER_POLICY_GATE, self.host)
            self.assertEqual(optional.NEXT_MEAL_GATE, self.host)
        self.assertEqual(self.host.read_bytes(), b'1\n')

    def test_existing_default_marker_is_rejected_without_mutation(self):
        marker = self.empty / 'owner-consent-v1-ready'
        marker.write_text('keep\n')
        original = owner_policy.OWNER_POLICY_GATE
        with self.assertRaisesRegex(ValueError, 'test_default_gate_must_be_absent'):
            with runner.isolated_readiness_defaults(self.empty):
                self.fail('occupied directory must refuse isolation')
        self.assertEqual(owner_policy.OWNER_POLICY_GATE, original)
        self.assertEqual(marker.read_text(), 'keep\n')
