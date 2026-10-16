"""Pinned, private SQLite library; never changes the OS or an existing runtime.

The stable updater loads this tested module from its exact Core candidate. Only
selected services receive its library through their transactional systemd override.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


def specification(folder=None):
    spec = json.loads(((Path(folder) if folder else Path(__file__).parent) / 'sqlite-runtime.json').read_text())
    assert re.fullmatch(r'3\.\d+\.\d+', spec['version'])
    assert re.fullmatch(r'https://sqlite\.org/20\d{2}/sqlite-autoconf-\d+\.tar\.gz', spec['source_url'])
    assert re.fullmatch(r'[0-9a-f]{64}', spec['source_sha3_256'])
    assert all(re.fullmatch(r'[A-Z][A-Z0-9_]*(?:=-?(?:0x[0-9a-f]+|[0-9]+))?', x) for x in spec['compile_options'])
    return spec


def target(root, spec):
    identity = hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    return Path(root) / (spec['version'] + '-' + identity) / 'lib'


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(python, library, spec):
    # New interpreter: importing sqlite3 in the updater cannot change a library
    # already loaded in its own process. No production database is opened.
    code = """import json,sqlite3
c=sqlite3.connect(':memory:')
c.execute('CREATE VIRTUAL TABLE docs USING fts5(body)')
c.execute('CREATE VIRTUAL TABLE points USING rtree(id,x1,x2)')
assert c.execute(\"SELECT json_extract('{\\\"ok\\\":1}', '$.ok')\").fetchone()[0]==1
print(json.dumps(dict(version=sqlite3.sqlite_version,source_id=c.execute('SELECT sqlite_source_id()').fetchone()[0],
                     defaults={name:c.execute('PRAGMA '+name).fetchone()[0] for name in ('foreign_keys','recursive_triggers','secure_delete')},
                     threadsafety=sqlite3.threadsafety,compile_options=[r[0] for r in c.execute('PRAGMA compile_options')])))
c.close()
"""
    env = dict(os.environ, LD_LIBRARY_PATH=str(library))
    run = subprocess.run([str(python), '-c', code], capture_output=True, text=True, env=env, timeout=30, check=True)
    result = json.loads(run.stdout)
    if result['version'] != spec['version'] or result['source_id'] != spec['source_id'] or result['threadsafety'] != 3:
        raise RuntimeError('SQLite runtime identity mismatch')
    return result


def provision(root, build_folder, interpreters):
    spec = specification()
    library = target(root, spec)
    runtime = library.parent
    manifest = runtime / 'manifest.json'
    if runtime.exists():
        saved = json.loads(manifest.read_text())
        if saved['specification'] != spec or saved['library_sha256'] != file_hash(library / 'libsqlite3.so.0'):
            raise RuntimeError('Existing SQLite runtime changed; do not overwrite it')
        return library, {str(p): probe(p, library, spec) for p in sorted(set(interpreters))}
    if not shutil.which('gcc'): raise RuntimeError('SQLite build requires gcc; working services remain unchanged')
    build_folder = Path(build_folder)
    build_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(build_folder).free < 512 * 1024**2: raise RuntimeError('Insufficient SQLite build space')
    archive = build_folder / 'sqlite-source.tar.gz'
    if not archive.exists():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(spec['source_url'], timeout=60) as response:
            data = response.read(20 * 1024**2 + 1)
        if len(data) > 20 * 1024**2 or hashlib.sha3_256(data).hexdigest() != spec['source_sha3_256']:
            raise RuntimeError('SQLite official source checksum mismatch')
        archive.write_bytes(data)
    if hashlib.sha3_256(archive.read_bytes()).hexdigest() != spec['source_sha3_256']:
        raise RuntimeError('SQLite source checksum mismatch')
    source = build_folder / 'source'
    source.mkdir(exist_ok=True, mode=0o700)
    with tarfile.open(archive) as tar:
        # Read only the three regular amalgamation files, never extract arbitrary
        # paths, links, configure scripts or files from an unverified archive.
        for name in ('sqlite3.c', 'sqlite3.h', 'sqlite3ext.h'):
            entries = [m for m in tar.getmembers() if Path(m.name).name == name]
            if len(entries) != 1 or not entries[0].isfile() or entries[0].size > 20*1024**2:
                raise RuntimeError('Unexpected SQLite source member')
            with tar.extractfile(entries[0]) as stream: (source/name).write_bytes(stream.read())
    Path(root).mkdir(parents=True, exist_ok=True, mode=0o755)
    Path(root).chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='.build-', dir=root) as temporary:
        prepared = Path(temporary)
        lib = prepared / 'lib'
        lib.mkdir(mode=0o755)
        command = ['gcc', '-O2', '-fPIC', '-shared', '-Wl,-soname,libsqlite3.so.0',
                   *['-DSQLITE_'+x for x in spec['compile_options']],
                   str(source/'sqlite3.c'), '-o', str(lib/'libsqlite3.so.0'), '-pthread', '-ldl', '-lm']
        with (build_folder/'compile.log').open('w') as out:
            subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, timeout=240, check=True)
        (lib/'libsqlite3.so.0').chmod(0o644)
        probes = {str(p): probe(p, lib, spec) for p in sorted(set(interpreters))}
        saved = dict(specification=spec, library_sha256=file_hash(lib/'libsqlite3.so.0'),
                     compiler=subprocess.run(['gcc','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0],
                     build_command=command, probe_results=probes)
        (prepared/'manifest.json').write_text(json.dumps(saved, indent=2)+'\n')
        (prepared/'manifest.json').chmod(0o644)
        prepared.chmod(0o755)
        # Same filesystem publication. Existing runtimes are immutable.
        prepared.rename(runtime)
    return library, {str(p): probe(p, library, spec) for p in sorted(set(interpreters))}
