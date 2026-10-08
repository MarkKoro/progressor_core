#!/usr/bin/env python3
"""Root-only main updater. Stage and test before switching; keep data on rollback."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/srv/progressor_core')
REPOSITORY = ROOT / 'repository'
UPSTREAM = 'git@github.com:MarkKoro/progressor_core.git'
SERVICE = 'progressor_core.service'
DATABASE = Path('/var/lib/progressor/core.sqlite3')
PRIVATE_CONFIG = Path('/etc/progressor')
BACKUPS = Path('/root/progressor-backups')
UPDATER = ROOT / 'updater/update_progressor.py'
HEALTH = 'http://127.0.0.1:8040'


def log(action, **fields):
    print(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'action': action, **fields}), flush=True)


def run(args, *, cwd=None, env=None, timeout=180, output=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=timeout, umask=0o022)
    if output:
        output.write_text(result.stdout + result.stderr)
        output.chmod(0o600)
    if result.returncode:
        raise RuntimeError('command_failed:' + Path(args[0]).name)
    return result.stdout.strip()


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as data:
        for block in iter(lambda: data.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def database_signature(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise RuntimeError('backup_integrity_failed')
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts = {t: db.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
    return {'schema_version': db.execute('PRAGMA schema_version').fetchone()[0], 'counts': counts}


def code_filter(info):
    parts = Path(info.name).parts
    if any(part in {'.venv', 'venv', '__pycache__', '.git'} for part in parts):
        return None
    return info


def backup_core(previous, stamp):
    """Online SQLite backup + independent restore check + exact code/private config."""
    folder = BACKUPS / (stamp + '-core-update')
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True, timeout=30)
    target = sqlite3.connect(folder / 'core.sqlite3')
    try:
        source.backup(target, pages=256, sleep=0.05)
        signature = database_signature(target)
        target.execute('PRAGMA journal_mode=DELETE')
    finally:
        target.close()
        source.close()
    restored = folder / 'restore-check.sqlite3'
    shutil.copy2(folder / 'core.sqlite3', restored)
    check = sqlite3.connect(restored.as_uri() + '?mode=ro', uri=True)
    try:
        if database_signature(check) != signature:
            raise RuntimeError('backup_restore_mismatch')
    finally:
        check.close()
    code = folder / 'code-config.tar.gz'
    with tarfile.open(code, 'w:gz') as tar:
        tar.add(previous, arcname='previous-release', filter=code_filter)
        for item in [PRIVATE_CONFIG, Path('/etc/systemd/system') / SERVICE,
                     Path('/etc/systemd/system') / (SERVICE + '.d'), UPDATER,
                     Path('/usr/local/bin/update-progressor'), Path('/usr/local/bin/updatecore')]:
            if item.exists():
                tar.add(item, arcname=str(item).lstrip('/'))
    with tarfile.open(code) as tar:
        names = set(tar.getnames())
        if not {'previous-release/progressor_core/app.py', 'etc/progressor/core.env',
                'etc/progressor/signing.key'}.issubset(names):
            raise RuntimeError('backup_missing_code_or_configuration')
    manifest = {'scope': 'Core application checkpoint; native databases are untouched',
                'previous_release': str(previous), 'restore_integrity': 'ok',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'files': {p.name: sha(p) for p in [folder / 'core.sqlite3', code]},
                'database_schema_version': signature['schema_version']}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    bundle = folder.with_suffix('.tar.gz')
    with tarfile.open(bundle, 'w:gz') as tar:
        tar.add(folder, arcname=folder.name)
    with tarfile.open(bundle) as tar:
        if not tar.getmembers():
            raise RuntimeError('empty_backup')
    log('backup_verified', archive=str(bundle), sha256=sha(bundle), restored_copy='ok')
    return folder


def readiness():
    with urllib.request.urlopen(HEALTH + '/health', timeout=3) as response:
        if json.load(response).get('ok') is not True:
            raise RuntimeError('unhealthy')
    with urllib.request.urlopen(HEALTH + '/ready', timeout=3) as response:
        state = json.load(response)
    if state.get('ready') is not True:
        raise RuntimeError('not_ready')
    return state


def compatible_readiness(new, previous):
    if new.get('ready') is not True:
        return False
    return all(new.get('sources', {}).get(source) == 'ok'
               for source, status in previous.get('sources', {}).items() if status == 'ok')


def wait_ready(previous):
    for _ in range(90):
        try:
            state = readiness()
            if compatible_readiness(state, previous) and run(['systemctl', 'is-active', SERVICE]) == 'active':
                return state
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('release_readiness_failed')


def atomic_link(path, destination):
    temporary = path.with_name(path.name + '.updating')
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(destination, target_is_directory=True)
    temporary.replace(path)


def offline_environment(tmp):
    # Do not inherit live provider tokens or source paths into tests.
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(tmp),
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
            'TMPDIR': str(tmp), 'PROGRESSOR_TEST_TMP_DIR': str(tmp),
            'BOT_TOKEN': '123:OFFLINE', 'OPENAI_API_KEY': 'offline',
            'PROGRESSOR_ENABLED_DOMAINS': '', 'PROGRESSOR_CLIENT_ENABLED': '0'}


def stage_revision(commit, stamp):
    release = ROOT / 'releases' / (stamp + '-' + commit[:12])
    release.mkdir(parents=True, mode=0o755)
    # git archive emits only tracked objects at the exact fetched revision.
    raw = subprocess.check_output(['git', '-C', str(REPOSITORY), 'archive', commit])
    import io
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar:
            target = release / member.name
            if not target.resolve().is_relative_to(release.resolve()) or not (member.isfile() or member.isdir()):
                raise RuntimeError('unsafe_repository_member')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
            else:
                if target.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pem', '.key'} or '.env' in target.parts:
                    raise RuntimeError('private_file_in_repository')
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with tar.extractfile(member) as data:
                    target.write_bytes(data.read())
                target.chmod(0o644)
    for required in ['progressor_core/app.py', 'requirements.txt', 'tests/test_integration.py',
                     'deploy/update_progressor.py']:
        if not (release / required).is_file():
            raise RuntimeError('incomplete_core_revision')
    venv = release / '.venv'
    log('prepare_runtime', revision=commit)
    run(['/usr/bin/python3', '-m', 'venv', str(venv)])
    runtime = str(venv / 'bin/python')
    run([runtime, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(release / 'requirements.txt')],
        timeout=360, output=release / 'dependency-install.log')
    run([runtime, '-m', 'pip', 'check'], output=release / 'dependency-check.log')
    with tempfile.TemporaryDirectory(prefix='progressor-tests-') as directory:
        run([runtime, '-m', 'unittest', 'discover', '-s', 'tests', '-q'], cwd=release,
            env=offline_environment(Path(directory)), timeout=240, output=release / 'test-results.log')
    (release / 'REVISION').write_text(commit + '\n')
    log('tests_passed', revision=commit, production_providers=False)
    return release


def apply_release(release, previous, before, checkpoint):
    switched = False
    try:
        atomic_link(ROOT / 'current', release)
        switched = True
        run(['systemctl', 'restart', SERVICE])
        state = wait_ready(before)
    except Exception:
        if switched:
            atomic_link(ROOT / 'current', previous)
            run(['systemctl', 'restart', SERVICE])
            wait_ready(before)
            log('rolled_back_code', release=str(previous), database_restored=False, checkpoint=str(checkpoint))
        raise
    # Promote the same tested updater only after the release is healthy.
    UPDATER.parent.mkdir(exist_ok=True, mode=0o755)
    temporary = UPDATER.with_suffix('.new')
    shutil.copyfile(release / 'deploy/update_progressor.py', temporary)
    temporary.chmod(0o644)
    temporary.replace(UPDATER)
    log('updated', release=str(release), sources=state['sources'], database_restored=False)


def main():
    parser = argparse.ArgumentParser(description='Проверенное обновление Progressor Core из GitHub main')
    parser.add_argument('--check', action='store_true', help='Проверить main и состояние без переключения версии')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('run_as_root')
    os.umask(0o077)
    ROOT.mkdir(exist_ok=True, mode=0o755)
    with (ROOT / 'update.lock').open('w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not REPOSITORY.is_dir() or run(['git', '-C', str(REPOSITORY), 'config', '--get', 'remote.origin.url']) != UPSTREAM:
            raise RuntimeError('repository_not_installed_or_wrong_remote')
        if run(['git', '-C', str(REPOSITORY), 'branch', '--show-current']) != 'main':
            raise RuntimeError('repository_must_use_main')
        if run(['git', '-C', str(REPOSITORY), 'status', '--porcelain']):
            raise RuntimeError('repository_has_local_changes')
        run(['git', '-C', str(REPOSITORY), 'fetch', 'origin', 'main'])
        commit = run(['git', '-C', str(REPOSITORY), 'rev-parse', 'origin/main'])
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise RuntimeError('invalid_main_revision')
        run(['git', '-C', str(REPOSITORY), 'merge-base', '--is-ancestor', 'HEAD', commit])
        previous = (ROOT / 'current').resolve(strict=True)
        if not previous.is_relative_to(ROOT / 'releases') or not previous.is_dir():
            raise RuntimeError('current_release_outside_releases')
        before = readiness()
        installed = (previous / 'REVISION').read_text().strip() if (previous / 'REVISION').exists() else None
        if args.check or installed == commit:
            log('checked' if args.check else 'already_current', main=commit, installed=installed,
                sources=before['sources'])
            return
        # Runtime must follow the release symlink for code and dependency rollback together.
        execution = run(['systemctl', 'show', SERVICE, '-p', 'ExecStart', '--value'])
        if '/srv/progressor_core/current/.venv/bin/python' not in execution:
            raise RuntimeError('install_release_runtime_service_override_first')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        release = stage_revision(commit, stamp)
        checkpoint = backup_core(previous, stamp)
        apply_release(release, previous, before, checkpoint)
        run(['git', '-C', str(REPOSITORY), 'merge', '--ff-only', commit])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never echo private provider/configuration or raw command output.
        log('update_failed', reason=str(error)[:180] if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1)
