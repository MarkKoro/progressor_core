#!/usr/bin/env python3
"""Explicit offline Core test entry point; never imported by the application.

Host readiness files are deployment state, not facts about temporary test DBs.
Only this test subprocess redirects reader defaults before test discovery.
Individual strict-mode fixtures retain their explicit store-owned gate paths.
No production reader, Store, Engine or environment policy is modified.
"""
from contextlib import ExitStack, contextmanager
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_readiness_defaults(directory):
    directory = Path(directory)
    assert directory.is_dir() and not directory.is_symlink()
    modules = [(importlib.import_module('progressor_core.owner_policy'), 'OWNER_POLICY_GATE',
                directory / 'owner-consent-v1-ready')]
    try:
        meals = importlib.import_module('progressor_core.next_meal')
    except ModuleNotFoundError as error:
        if error.name != 'progressor_core.next_meal':
            raise
    else:
        modules.append((meals, 'NEXT_MEAL_GATE', directory / 'next-meal-v1-ready'))
    with ExitStack() as stack:
        for module, name, path in modules:
            try:
                path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError('test_default_gate_must_be_absent')
            stack.enter_context(patch.object(module, name, path))
        yield


def main(argv=None):
    sys.path.insert(0, str(ROOT))
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ['discover', '-s', 'tests', '-q']
    with tempfile.TemporaryDirectory(prefix='core-readiness-', dir=os.getenv('PROGRESSOR_TEST_TMP_DIR')) as folder:
        with isolated_readiness_defaults(folder):
            result = unittest.main(module=None, argv=[str(Path(__file__)), *arguments], exit=False)
    return 0 if result.result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
