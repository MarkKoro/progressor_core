"""Provisioning rejects unverified input and never overwrites an immutable runtime."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

loader = importlib.util.spec_from_file_location('sqlite_runtime', Path(__file__).parents[1]/'deploy/sqlite_runtime.py')
runtime = importlib.util.module_from_spec(loader)
loader.loader.exec_module(runtime)


class RuntimeIntegrity(unittest.TestCase):
    def test_different_build_options_get_separate_immutable_runtime(self):
        spec = runtime.specification()
        changed = {**spec, 'compile_options':[*spec['compile_options'],'DEFAULT_RECURSIVE_TRIGGERS=0']}
        self.assertNotEqual(runtime.target('/runtime',spec),runtime.target('/runtime',changed))
        self.assertEqual(runtime.target('/runtime',spec),runtime.target('/runtime',dict(reversed(list(spec.items())))))
    def test_source_checksum_failure_cannot_compile_or_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'build').mkdir()
            (root/'build/sqlite-source.tar.gz').write_bytes(b'not the official source')
            with patch.object(runtime.shutil, 'which', return_value='gcc'), patch.object(runtime.subprocess, 'run') as compile:
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    runtime.provision(root/'runtimes', root/'build', [])
            compile.assert_not_called()
            self.assertFalse((root/'runtimes').exists())

    def test_changed_existing_library_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec = runtime.specification()
            library = runtime.target(root/'runtimes', spec)
            library.mkdir(parents=True)
            binary = library/'libsqlite3.so.0'
            binary.write_bytes(b'changed')
            (library.parent/'manifest.json').write_text(json.dumps(dict(specification=spec, library_sha256='0'*64)))
            with self.assertRaisesRegex(RuntimeError, 'do not overwrite'):
                runtime.provision(root/'runtimes', root/'build', [])
            self.assertEqual(binary.read_bytes(), b'changed')

    def test_archive_link_is_rejected_before_any_file_is_extracted(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as tar:
            member = tarfile.TarInfo('source/sqlite3.c')
            member.type = tarfile.SYMTYPE
            member.linkname = '/outside/target'
            tar.addfile(member)
        spec = {**runtime.specification(), 'source_sha3_256':hashlib.sha3_256(data.getvalue()).hexdigest()}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'build').mkdir()
            (root/'build/sqlite-source.tar.gz').write_bytes(data.getvalue())
            with patch.object(runtime, 'specification', return_value=spec), patch.object(runtime.shutil, 'which', return_value='gcc'), \
                 patch.object(runtime.subprocess, 'run') as compile:
                with self.assertRaisesRegex(RuntimeError, 'source member'):
                    runtime.provision(root/'runtimes', root/'build', [])
            compile.assert_not_called()
            self.assertFalse((root/'runtimes').exists())
