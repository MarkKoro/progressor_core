#!/usr/bin/env python3
"""Coordinated main deployment. Never restore databases during code recovery."""
import argparse
import base64
import fcntl
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

CORE = Path('/srv/progressor_core')
STATE = CORE / 'updater/update-all-state.json'
TRANSACTIONS = Path('/root/progressor-deployments/update-all')
RUNTIMES = Path('/srv/progressor-runtimes')
BACKUPS = Path('/root/progressor-backups')
SYSTEMD = Path('/etc/systemd/system')
DROPIN = 'zz-progressor-update-all.conf'
UPDATERS = CORE / 'updater'
REPOS = {
    'gym': {'path': Path('/srv/gym_diary_prod'), 'repo': 'gym_diary_bot', 'title': 'Gym'},
    'food': {'path': Path('/srv/food_bot'), 'repo': 'food_bot', 'title': 'Food'},
    'supply': {'path': Path('/srv/supply_bot'), 'repo': 'supply_bot', 'title': 'Supply'},
    'core': {'path': CORE / 'repository', 'repo': 'progressor_core', 'title': 'Core'},
}
UNIT_SPECS = {
    'gymdiary.service': ('gym', 'bot', None),
    'gymdiary_webapp_prod.service': ('gym', 'api', 'http://127.0.0.1:8020/health'),
    'food_bot.service': ('food', 'bot', None),
    'food_webapp.service': ('food', 'api', 'http://127.0.0.1:8005/api/health'),
    'foodweb.service': ('food', 'legacy', 'http://127.0.0.1:8002/api/health'),
    'supply_bot.service': ('supply', 'bot', None),
    'supply_webapp.service': ('supply', 'api', 'http://127.0.0.1:8030/health'),
    'supply_assistant_worker.service': ('supply', 'worker', None),
    'progressor_core.service': ('core', 'api', 'http://127.0.0.1:8040/ready'),
}
DBS = {'gym': Path('/srv/gym_diary_prod/gymdiary.db'),
       'food': Path('/srv/food_bot/data/food_bot.sqlite3'),
       'supply': Path('/srv/supply_bot/data/supply_bot.sqlite3'),
       'core': Path('/var/lib/progressor/core.sqlite3')}
INCOMPLETE = {'stopping', 'switching', 'starting', 'verifying', 'promoting', 'rolling_back'}
HELPERS = {'domain_bridge.py': 'progressor_bridge.py', 'progressor_client.py': 'progressor_client.py',
           'progressor_bot.py': 'progressor_bot.py', 'ai_guard.py': 'progressor_ai_guard.py'}


class UpdateError(RuntimeError):
    pass


def emit(message):
    print(message, flush=True)


def sha(path):
    d = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            d.update(block)
    return d.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.chmod(0o600); tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def atomic_file(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.parent.chmod(0o755)
    tmp = path.with_name(path.name + '.new')
    with tmp.open('wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    tmp.chmod(mode); tmp.replace(path)


def atomic_link(path, target):
    tmp = path.with_name(path.name + '.update-all')
    if tmp.exists() or tmp.is_symlink(): tmp.unlink()
    tmp.symlink_to(target, target_is_directory=True); tmp.replace(path)


def command(args, *, cwd=None, env=None, timeout=180, logfile=None, allow_failure=False):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True,
                       timeout=timeout, umask=0o022)
    if logfile:
        Path(logfile).write_bytes(p.stdout + p.stderr); Path(logfile).chmod(0o600)
    if p.returncode and not allow_failure:
        raise UpdateError('command_failed:' + Path(str(args[0])).name)
    return p.returncode, p.stdout


def text_command(args, **kwargs):
    return command(args, **kwargs)[1].decode('utf-8').strip()


def git(name, *args, **kwargs):
    return text_command(['git', '-c', 'core.hooksPath=/dev/null', '-C', REPOS[name]['path'], *args], **kwargs)


def protected_path(name):
    p = PurePosixPath(name)
    return (p.is_absolute() or '..' in p.parts or not p.parts or
            any(x in {'.git', '.venv', 'venv', '__pycache__', 'uploads', 'backups'} for x in p.parts) or
            any(x == '.env' or x.startswith('.env.') and x != '.env.example' for x in p.parts) or
            p.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pem', '.key'} or
            p.name.endswith(('-wal', '-shm')))


def extract_revision(name, commit, target):
    target.mkdir(parents=True, exist_ok=False, mode=0o755)
    archive = command(['git', '-C', REPOS[name]['path'], 'archive', '--format=tar', commit])[1]
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for item in tar:
            if protected_path(item.name): continue
            dest = (target / item.name).resolve()
            if not dest.is_relative_to(target.resolve()) or item.issym() or item.islnk():
                raise UpdateError('unsafe_repository_member:' + name)
            if item.isdir(): dest.mkdir(parents=True, exist_ok=True, mode=0o755)
            elif item.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with tar.extractfile(item) as f: dest.write_bytes(f.read())
                dest.chmod(0o755 if item.mode & 0o111 else 0o644)
            else: raise UpdateError('unsupported_repository_member:' + name)
    if not (target / 'requirements.txt').is_file():
        raise UpdateError('missing_requirements:' + name)


def offline_environment(folder):
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(folder), 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(folder),
            'PROGRESSOR_TEST_TMP_DIR': str(folder), 'DB_PATH': str(folder / 'unused.sqlite3'),
            'BOT_TOKEN': '123:OFFLINE', 'TG_TOKEN': '123:OFFLINE', 'CHANNEL_ID': '-1001',
            'OPENAI_API_KEY': 'offline', 'YOOKASSA_SHOP_ID': '', 'YOOKASSA_SECRET_KEY': '',
            'PROGRESSOR_ENABLED_DOMAINS': '', 'PROGRESSOR_CLIENT_ENABLED': '0',
            'PROGRESSOR_AUTH_ENABLED': '0', 'PROGRESSOR_SOURCE_SNAPSHOT_ENABLED': '0',
            'AUTO_SEED_ON_START': '0'}


def unit_info(unit):
    raw = text_command(['systemctl', 'show', unit,
        '--property=ExecStart,WorkingDirectory,ActiveState,MainPID,NRestarts,FragmentPath'])
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    match = re.search(r'argv\[\]=(.*?) ; ignore_errors=', fields.get('ExecStart', ''))
    if not match: raise UpdateError('unknown_service_command:' + unit)
    args = shlex.split(match[1])
    if not args or not Path(args[0]).is_absolute() or Path(args[0]).name not in {'python', 'python3', 'python3.12'}:
        raise UpdateError('unsupported_service_runtime:' + unit)
    if any('\n' in x or '\r' in x for x in args): raise UpdateError('unsafe_service_argument:' + unit)
    return {'args': args, 'active': fields['ActiveState'] == 'active', 'cwd': fields['WorkingDirectory'],
            'pid': int(fields.get('MainPID', '0')), 'restarts': int(fields.get('NRestarts', '0')),
            'fragment': fields['FragmentPath']}


def signature(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise UpdateError('database_backup_integrity_failed')
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {'schema': db.execute('PRAGMA schema_version').fetchone()[0],
            'counts': {t: db.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}}


def verified_database_backup(source, target):
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst, pages=256, sleep=0.05)
        result = signature(dst); dst.execute('PRAGMA journal_mode=DELETE')
    finally: dst.close(); src.close()
    restore = target.with_name(target.stem + '-restore.sqlite3')
    shutil.copyfile(target, restore)
    db = sqlite3.connect(restore.as_uri() + '?mode=ro', uri=True)
    try:
        if signature(db) != result: raise UpdateError('database_restore_mismatch')
    finally: db.close()
    return {'sha256': sha(target), 'size_bytes': target.stat().st_size,
            'integrity': 'ok', 'restored_copy': 'ok', **result}


def runtime_dropin(args, python):
    def quote(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'
    return ('[Service]\nExecStart=\nExecStart=' + ' '.join(quote(x) for x in [str(python), *args[1:]]) + '\n').encode()


def tree_size(folder, exclude=()):
    total = 0
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if d not in exclude]
        for name in files:
            path = Path(root) / name
            if not path.is_symlink(): total += path.stat().st_size
    return total


def ensure_space(needed=0):
    disk = shutil.disk_usage(CORE)
    reserve = max(2 * 1024**3, disk.total // 10)
    if disk.free < reserve + needed:
        raise UpdateError('not_enough_disk_space_no_production_switch')


class Updater:
    def __init__(self, only=None, check=False):
        self.selected = {only} if only else set(REPOS)
        self.check_only = check
        self.stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + str(os.getpid())
        self.folder = TRANSACTIONS / self.stamp
        self.state = {'phase': 'preparing', 'id': self.stamp, 'repositories': {}, 'units': {},
                      'affected': [], 'attempted_repositories': [], 'dropins': {}, 'old_updaters': {},
                      'core_before': str((CORE / 'current').resolve(strict=True)), 'core_after': None,
                      'worker_frozen': False, 'history': []}
        self.candidates = {}; self.runtime_plans = {}; self.python_for_unit = {}; self.changed = set()

    def save(self, phase=None, **fields):
        if phase: self.state['phase'] = phase
        self.state.update(fields)
        self.state['history'].append({'at': datetime.now(timezone.utc).isoformat(), 'phase': self.state['phase']})
        atomic_json(STATE, self.state)
        atomic_json(self.folder / 'state.json', self.state)

    def recover_pending(self):
        if not STATE.exists(): return
        old = json.loads(STATE.read_text())
        if old.get('phase') not in INCOMPLETE: return
        if self.check_only: raise UpdateError('interrupted_update_run_update_all_to_recover')
        emit('Восстанавливаю предыдущую версию после прерванного обновления…')
        self.state = old
        self.folder = TRANSACTIONS / old['id']
        if self.folder.parent != TRANSACTIONS or not self.folder.exists(): raise UpdateError('unsafe_transaction_state')
        self.rollback()
        self.__init__(next(iter(self.selected)) if len(self.selected) == 1 else None)

    def plan(self):
        self.folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        candidates = self.folder / 'candidates'; candidates.mkdir()
        for name, spec in REPOS.items():
            if git(name, 'config', '--get', 'remote.origin.url') != 'git@github.com:MarkKoro/' + spec['repo'] + '.git':
                raise UpdateError('wrong_git_remote:' + name)
            if git(name, 'branch', '--show-current') != 'main': raise UpdateError('main_required:' + name)
            before = git(name, 'rev-parse', 'HEAD')
            emit('Получаю main: ' + spec['title'] + '…')
            ensure_space(512 * 1024**2)
            git(name, 'fetch', '--quiet', 'origin', 'main')
            after = git(name, 'rev-parse', 'origin/main') if name in self.selected else before
            if not re.fullmatch('[0-9a-f]{40}', after): raise UpdateError('invalid_git_revision:' + name)
            git(name, 'merge-base', '--is-ancestor', before, after)
            _, raw = command(['git', '-C', spec['path'], 'diff', '--name-only', '--no-renames', '-z', before, after])
            paths = [s.decode('utf-8') for s in raw.split(b'\0') if s]
            if any(protected_path(p) for p in paths): raise UpdateError('git_changed_live_data_or_private_file:' + name)
            if paths and git(name, 'status', '--porcelain', '--', *paths):
                raise UpdateError('local_changes_in_updated_files:' + name)
            dirty = command(['git', '-C', spec['path'], 'diff', '--name-only', '-z', 'HEAD'])[1].split(b'\0')
            if any(p and not protected_path(p.decode()) for p in dirty):
                raise UpdateError('local_uncommitted_code:' + name)
            self.state['repositories'][name] = {'before': before, 'target': after,
                'available_main': git(name, 'rev-parse', 'origin/main'), 'paths': paths}
            extract_revision(name, after, candidates / name)
            self.candidates[name] = candidates / name
            if before != after: self.changed.add(name)
        old_core = Path(self.state['core_before'])
        if not old_core.is_relative_to(CORE / 'releases'): raise UpdateError('core_release_outside_managed_path')
        self.state['core_revision_before'] = (old_core / 'REVISION').read_text().strip()
        if 'core' in self.selected and self.state['core_revision_before'] != self.state['repositories']['core']['target']:
            self.changed.add('core')
        for unit, (name, kind, _) in UNIT_SPECS.items():
            if kind == 'legacy' and text_command(['systemctl', 'is-active', unit], allow_failure=True) != 'active': continue
            info = unit_info(unit)
            expected = CORE / 'current' if name == 'core' else REPOS[name]['path']
            if Path(info['cwd']).resolve() != expected.resolve(): raise UpdateError('unexpected_service_directory:' + unit)
            self.state['units'][unit] = info
            self.python_for_unit[unit] = info['args'][0]
            if name not in self.selected: continue
            runtime_key = name + '-' + hashlib.sha256(info['args'][0].encode()).hexdigest()[:10]
            if runtime_key in self.runtime_plans: continue
            report = self.folder / (runtime_key + '-requirements.json')
            command([info['args'][0], '-m', 'pip', 'install', '--dry-run', '--disable-pip-version-check',
                     '--report', report, '-r', self.candidates[name] / 'requirements.txt'],
                    cwd=self.candidates[name], timeout=360, logfile=self.folder / (runtime_key + '-requirements.log'))
            install = json.loads(report.read_text()).get('install', [])
            check = command([info['args'][0], '-m', 'pip', 'check'], allow_failure=True,
                            logfile=self.folder / (runtime_key + '-pip-check.log'))[0]
            needs = bool(install) or bool(check) or name == 'core' and name in self.changed
            self.runtime_plans[runtime_key] = {'name': name, 'python': info['args'][0], 'needs': needs}
            if needs: self.changed.add(name)
        self.check_helpers()
        self.state['changed_components'] = sorted(self.changed)
        self.save()

    def check_helpers(self):
        for name in ('gym', 'food', 'supply'):
            mapping = {**HELPERS, **({'workout_metrics.py': 'progressor_workout_metrics.py'} if name == 'gym' else {})}
            for src, dst in mapping.items():
                a, b = self.candidates['core'] / 'shared' / src, self.candidates[name] / dst
                if not a.is_file() or not b.is_file() or a.read_bytes() != b.read_bytes():
                    raise UpdateError('incompatible_shared_helper:' + name + '/' + dst)

    def prepare_runtimes(self):
        prepared = {}
        core_release = None
        for key, item in self.runtime_plans.items():
            if not item['needs']: continue
            name = item['name']; source = self.candidates[name]
            freeze = text_command([item['python'], '-m', 'pip', 'freeze'])
            fingerprint = hashlib.sha256((freeze + sha(source / 'requirements.txt')).encode()).hexdigest()
            if name == 'core':
                core_release = CORE / 'releases' / (self.stamp + '-' + self.state['repositories']['core']['target'][:12])
                extract_revision(name, self.state['repositories']['core']['target'], core_release)
                source = core_release; self.candidates['core'] = core_release
                venv = core_release / '.venv'
            elif (name, fingerprint) in prepared:
                venv = prepared[(name, fingerprint)]
            else:
                venv = RUNTIMES / name / (self.stamp + '-' + fingerprint[:12])
            if not venv.exists():
                emit('Готовлю отдельное окружение: ' + REPOS[name]['title'] + '…')
                ensure_space(3 * tree_size(Path(item['python']).parent.parent) + 512 * 1024**2)
                venv.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                venv.parent.chmod(0o755)
                RUNTIMES.mkdir(exist_ok=True, mode=0o755); RUNTIMES.chmod(0o755)
                if name != 'core': (RUNTIMES / name).chmod(0o755)
                command(['/usr/bin/python3', '-m', 'venv', venv])
                baseline = self.folder / (key + '-baseline.txt'); baseline.write_text(freeze + '\n')
                python = venv / 'bin/python'
                command([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', baseline],
                        timeout=600, logfile=self.folder / (key + '-baseline-install.log'))
                command([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', source / 'requirements.txt'],
                        cwd=source, timeout=600, logfile=self.folder / (key + '-target-install.log'))
                command([python, '-m', 'pip', 'check'], logfile=self.folder / (key + '-final-pip-check.log'))
            prepared[(name, fingerprint)] = venv
            for unit, info in self.state['units'].items():
                if UNIT_SPECS[unit][0] == name and info['args'][0] == item['python']:
                    self.python_for_unit[unit] = str(venv / 'bin/python')
        if core_release:
            (core_release / 'REVISION').write_text(self.state['repositories']['core']['target'] + '\n')
            self.state['core_after'] = str(core_release)
        self.check_helpers()

    def test_candidates(self):
        results = {}
        for name in sorted(self.changed):
            source = self.candidates[name]
            if not (source / 'tests').is_dir(): raise UpdateError('missing_contract_tests:' + name)
            for file in source.rglob('*.py'):
                if any(p in {'.venv', 'venv', '__pycache__'} for p in file.relative_to(source).parts): continue
                try: compile(file.read_bytes(), str(file), 'exec')
                except Exception: raise UpdateError('candidate_syntax_error:' + name + '/' + str(file.relative_to(source)))
            selections = [('gymdiary.service', 'test_subscriptions.py'), ('gymdiary_webapp_prod.service', 'test_progressor_context.py'),
                          ('gymdiary_webapp_prod.service', 'test_native_controls.py')] if name == 'gym' else [
                          ('progressor_core.service' if name == 'core' else name + '_bot.service', None)]
            emit('Проверяю новую версию: ' + REPOS[name]['title'] + '…')
            for i, (unit, pattern) in enumerate(selections):
                tmp = self.folder / ('tests-' + name + '-' + str(i)); tmp.mkdir()
                args = [self.python_for_unit[unit], '-m', 'unittest', 'discover', '-s', 'tests']
                if pattern:
                    if not (source / 'tests' / pattern).is_file(): raise UpdateError('missing_contract_tests:' + name)
                    args += ['-p', pattern]
                args += ['-q']
                logfile = self.folder / (name + '-tests-' + str(i) + '.log')
                command(args, cwd=source, env=offline_environment(tmp), timeout=360, logfile=logfile)
                match = re.search(r'Ran (\d+) tests?', logfile.read_text())
                if not match or int(match[1]) == 0: raise UpdateError('no_contract_tests_ran:' + name)
                results[name] = results.get(name, 0) + int(match[1])
        self.save(tests_passed=True, tests=results, python_for_unit=self.python_for_unit)

    def health(self, *, stable_seconds=0):
        def probe():
            result = {}
            for unit in self.state['units']:
                info = unit_info(unit)
                if not info['active'] or not info['pid']: raise UpdateError('service_not_running:' + unit)
                url = UNIT_SPECS[unit][2]
                if url:
                    with urllib.request.urlopen(url, timeout=3) as response: data = json.load(response)
                    name = UNIT_SPECS[unit][0]
                    if name == 'core':
                        if data.get('ready') is not True or any(data.get('sources', {}).get(n) != 'ok' for n in ('gym', 'food', 'supply')):
                            raise UpdateError('source_sync_not_ready')
                    elif data.get('ok') is not True and data.get('status') != 'ok':
                        raise UpdateError('api_not_ready:' + unit)
                result[unit] = {'pid': info['pid'], 'restarts': info['restarts']}
            self.check_consumers(result)
            return result
        first = probe()
        deadline = time.monotonic() + stable_seconds
        while time.monotonic() < deadline:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            if probe() != first: raise UpdateError('service_restarted_during_verification')
        return first

    def check_consumers(self, services):
        for name in ('gym', 'food', 'supply'):
            expected_unit = next(u for u, spec in UNIT_SPECS.items() if spec[:2] == (name, 'bot'))
            found = []
            for process in Path('/proc').glob('[0-9]*'):
                try:
                    args = process.joinpath('cmdline').read_bytes().decode().split('\0')
                    if any(a == str(REPOS[name]['path'] / 'bot.py') or
                           a == 'bot.py' and process.joinpath('cwd').resolve() == REPOS[name]['path'] for a in args):
                        found.append(int(process.name))
                except (OSError, UnicodeError): pass
            if sorted(found) != [services[expected_unit]['pid']]:
                raise UpdateError('telegram_consumer_count_not_one:' + name)

    def wait_health(self, seconds=150):
        deadline = time.monotonic() + seconds
        while True:
            try: return self.health(stable_seconds=8)
            except Exception:
                if time.monotonic() >= deadline: raise UpdateError('startup_or_sync_verification_failed')
                time.sleep(2)

    def backup(self):
        emit('Сохраняю код, настройки и проверенные копии четырёх баз…')
        required = 3 * sum(p.stat().st_size for p in DBS.values()) + sum(
            tree_size(s['path'], exclude={'venv', '.venv', '__pycache__', 'node_modules', 'backups'}) for s in REPOS.values())
        ensure_space(required + 256 * 1024**2)
        folder = BACKUPS / (self.stamp + '-all-update')
        folder.mkdir(parents=True, mode=0o700)
        databases = folder / 'databases'; databases.mkdir()
        checks = {name: verified_database_backup(path, databases / (name + '.sqlite3')) for name, path in DBS.items()}
        def code_filter(item):
            parts = PurePosixPath(item.name).parts
            if any(p in {'.venv', 'venv', '__pycache__', 'node_modules', 'backups', 'releases'} for p in parts): return None
            if item.name.endswith(('.db', '.sqlite', '.sqlite3', '-wal', '-shm')): return None
            return item
        archive = folder / 'code-config.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for spec in REPOS.values(): tar.add(spec['path'], arcname=str(spec['path']).lstrip('/'), filter=code_filter)
            tar.add(self.state['core_before'], arcname='previous-core-release', filter=lambda item: None if any(
                p in {'.venv', '__pycache__'} for p in PurePosixPath(item.name).parts) else item)
            for path in [Path('/etc/progressor'), Path('/etc/nginx'), Path('/etc/gymdiary_webapp_prod.env'),
                         UPDATERS, *self.command_paths(),
                         *[SYSTEMD / u for u in self.state['units']],
                         *[SYSTEMD / (u + '.d') for u in self.state['units']]]:
                if path.exists(): tar.add(path, arcname=str(path).lstrip('/'))
        with tarfile.open(archive) as tar:
            names = set(tar.getnames())
            required = {'previous-core-release/progressor_core/app.py', 'etc/progressor/core.env', 'etc/progressor/signing.key'}
            required.update(str(REPOS[n]['path'] / f).lstrip('/') for n in ('gym', 'food', 'supply') for f in ('bot.py', '.env', '.git/config'))
            if not required.issubset(names): raise UpdateError('backup_missing_code_or_configuration')
        manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'repositories': self.state['repositories'],
                    'units': self.state['units'], 'databases': checks, 'code_config_sha256': sha(archive),
                    'runtime_packages': {p: text_command([p, '-m', 'pip', 'freeze'])
                        for p in sorted({u['args'][0] for u in self.state['units'].values()})},
                    'core_previous': self.state['core_before'],
                    'scope': 'Four applications; online per-database copies, not a globally atomic snapshot or VPS image. Recovery never restores live databases.'}
        atomic_json(folder / 'manifest.json', manifest)
        bundle = folder.with_suffix('.tar.gz')
        with tarfile.open(bundle, 'w:gz') as tar: tar.add(folder, arcname=folder.name)
        bundle.chmod(0o600)
        atomic_file(folder / 'archive.sha256', (sha(bundle) + '\n').encode(), mode=0o600)
        self.save(backup={'path': str(bundle), 'sha256': sha(bundle), 'databases_restored_check': 'ok'})
        emit('Копия проверена: ' + str(bundle))
        emit('SHA256: ' + self.state['backup']['sha256'])

    def prune_backups(self):
        # Only our verified, fully packaged all-update backups. Other project checkpoints are never candidates.
        valid = []
        for archive in BACKUPS.glob('*-all-update.tar.gz'):
            if not re.fullmatch(r'\d{8}T\d{6}Z-\d+-all-update\.tar\.gz', archive.name): continue
            folder = archive.with_name(archive.name.removesuffix('.tar.gz'))
            if archive.is_symlink() or folder.is_symlink() or folder.resolve().parent != BACKUPS.resolve(): continue
            try:
                manifest = json.loads((folder / 'manifest.json').read_text())
                if set(manifest['databases']) != set(DBS) or any(v.get('restored_copy') != 'ok' for v in manifest['databases'].values()): continue
                if sha(archive) != (folder / 'archive.sha256').read_text().strip(): continue
                if set(p.name for p in folder.iterdir()) != {'manifest.json', 'archive.sha256', 'code-config.tar.gz', 'databases'}: continue
                valid.append((archive, folder))
            except (OSError, ValueError, KeyError): continue
        valid.sort(key=lambda pair: pair[0].name, reverse=True)
        protected = self.state.get('backup', {}).get('path')
        reclaimed = 0
        for archive, folder in valid[3:]:
            if str(archive) == protected: continue
            reclaimed += archive.stat().st_size + tree_size(folder)
            archive.unlink(); shutil.rmtree(folder)
        if reclaimed: emit('Освобождено старых копий: ' + str(round(reclaimed / 1024**2)) + ' МБ; последние три проверенные копии сохранены.')

    @staticmethod
    def command_paths():
        return [Path('/usr/local/bin') / n for n in ('update-all', 'updateall', 'update_food', 'update_supply',
                'update_gymdiary', 'update-progressor', 'updatecore')]

    def prepare_switch(self):
        affected = [u for u in self.state['units'] if UNIT_SPECS[u][0] in self.changed or
                    u == 'progressor_core.service' and self.changed]
        self.state['affected'] = affected
        for unit in affected:
            path = SYSTEMD / (unit + '.d') / DROPIN
            self.state['dropins'][unit] = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
        for file in ('update_all.py', 'update_progressor.py'):
            path = UPDATERS / file
            self.state['old_updaters'][file] = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
        self.save()

    def thaw_worker(self):
        if self.state.get('worker_frozen'):
            command(['systemctl', 'thaw', 'supply_assistant_worker.service'])
            self.save(worker_frozen=False)

    def stop_units(self):
        worker = 'supply_assistant_worker.service'
        # Producers stop first. Freeze+read excludes the race between an idle check and the next paid job claim.
        others = [u for u in self.state['affected'] if u != worker]
        if others: command(['systemctl', 'stop', *others], timeout=150)
        if worker not in self.state['affected']: return
        deadline = time.monotonic() + 600
        while True:
            self.save(worker_frozen=True)
            command(['systemctl', 'freeze', worker])
            db = sqlite3.connect(DBS['supply'].as_uri() + '?mode=ro', uri=True, timeout=3)
            try: busy = db.execute("SELECT count(*) FROM assistant_jobs WHERE status='processing'").fetchone()[0]
            finally: db.close()
            if not busy:
                command(['systemctl', 'stop', worker], timeout=100)
                self.save(worker_frozen=False)
                return
            self.thaw_worker()
            if time.monotonic() >= deadline: raise UpdateError('supply_paid_jobs_did_not_finish')
            emit('Ожидаю завершения текущего задания Supply…')
            time.sleep(10)

    def switch(self):
        self.save('switching', switch_started=True)
        for name in ('core', 'gym', 'food', 'supply'):
            info = self.state['repositories'][name]
            if name not in self.changed or info['before'] == info['target']: continue
            if git(name, 'rev-parse', 'HEAD') != info['before']: raise UpdateError('repository_changed_during_update:' + name)
            if info['paths'] and git(name, 'status', '--porcelain', '--', *info['paths']):
                raise UpdateError('local_edit_during_preparation:' + name)
            self.state['attempted_repositories'].append(name); self.save()
            git(name, 'merge', '--ff-only', '--no-edit', info['target'])
        if self.state['core_after']: atomic_link(CORE / 'current', self.state['core_after'])
        for unit in self.state['affected']:
            old = self.state['units'][unit]['args'][0]
            python = self.python_for_unit[unit]
            if UNIT_SPECS[unit][0] == 'core': python = str(CORE / 'current/.venv/bin/python')
            if old != python:
                atomic_file(SYSTEMD / (unit + '.d') / DROPIN, runtime_dropin(self.state['units'][unit]['args'], python))
        command(['systemctl', 'daemon-reload'])

    def start_units(self):
        units = self.state['affected']
        sources = [u for u in units if u != 'progressor_core.service']
        if sources: command(['systemctl', 'start', *sources], timeout=150)
        if 'progressor_core.service' in units: command(['systemctl', 'start', 'progressor_core.service'], timeout=100)

    def promote_updaters(self):
        if 'core' not in self.changed: return
        for file in ('update_all.py', 'update_progressor.py'):
            source = Path(self.state['core_after']) / 'deploy' / file
            if not source.is_file(): raise UpdateError('missing_tested_updater:' + file)
            atomic_file(UPDATERS / file, source.read_bytes())

    def rollback_repository(self, name):
        info = self.state['repositories'][name]
        head = git(name, 'rev-parse', 'HEAD')
        if head not in {info['before'], info['target']}: raise UpdateError('concurrent_git_change_prevents_recovery:' + name)
        paths = []
        for path in info['paths']:
            if protected_path(path): raise UpdateError('unsafe_recovery_path')
            old_exists = command(['git', '-C', REPOS[name]['path'], 'cat-file', '-e', info['before'] + ':' + path], allow_failure=True)[0] == 0
            tracked = bool(git(name, 'ls-files', '--', path))
            if old_exists or tracked: paths.append(path)
            elif (REPOS[name]['path'] / path).exists():
                # Idempotent recovery after index restoration was interrupted. Never delete somebody else's edit.
                expected = command(['git', '-C', REPOS[name]['path'], 'show', info['target'] + ':' + path])[1]
                dest = REPOS[name]['path'] / path
                if dest.is_symlink() or not dest.is_file() or dest.read_bytes() != expected:
                    raise UpdateError('new_local_file_prevents_recovery:' + name)
                dest.unlink()
        if paths: git(name, 'restore', '--source', info['before'], '--staged', '--worktree', '--', *paths)
        if head != info['before']: git(name, 'update-ref', 'refs/heads/main', info['before'], head)

    def rollback(self):
        self.save('rolling_back')
        self.thaw_worker()
        # Stop new code before restoring any path. Failure to stop must not replace executing source files.
        # An aborted drain has not switched code. Leave the still-running paid job alone.
        if self.state.get('switch_started') and self.state['affected']:
            command(['systemctl', 'stop', *self.state['affected']], timeout=150)
        errors = []
        for name in reversed(self.state['attempted_repositories']):
            try: self.rollback_repository(name)
            except Exception as error: errors.append(type(error).__name__ + ':' + name)
        try:
            atomic_link(CORE / 'current', self.state['core_before'])
            for unit, old in self.state['dropins'].items():
                path = SYSTEMD / (unit + '.d') / DROPIN
                if old is None: path.unlink(missing_ok=True)
                else: atomic_file(path, base64.b64decode(old))
            for file, old in self.state['old_updaters'].items():
                if old is None: (UPDATERS / file).unlink(missing_ok=True)
                else: atomic_file(UPDATERS / file, base64.b64decode(old))
            command(['systemctl', 'daemon-reload'])
        except Exception as error: errors.append(type(error).__name__ + ':runtime')
        if errors:
            self.save(recovery_errors=errors)
            raise UpdateError('recovery_requires_attention_see_private_transaction_log')
        self.start_units()
        report = self.wait_health()
        self.save('rolled_back', health=report, database_restored=False)
        emit('Возвращены прежние версии кода и окружений. Новые записи пользователей сохранены.')

    def show_status(self, report):
        for name, spec in REPOS.items():
            info = self.state['repositories'][name]
            installed = git(name, 'rev-parse', 'HEAD')
            if name == 'core': installed = (CORE / 'current/REVISION').read_text().strip()
            available = info['available_main']
            tail = 'актуальная main' if installed == available else 'на GitHub есть новая версия'
            emit(spec['title'] + ': OK · ' + installed[:12] + ' · ' + tail)
        emit('Синхронизация трёх ботов: OK')
        emit('Журнал: ' + str(self.folder))

    def execute(self):
        self.recover_pending()
        ensure_space()
        self.plan()
        baseline = self.health(stable_seconds=2)
        self.save(baseline_health=baseline)
        if self.check_only or not self.changed:
            self.save('checked' if self.check_only else 'already_current', health=baseline)
            if self.check_only: emit('Изменения для установки: ' + (', '.join(sorted(self.changed)) or 'нет'))
            else: emit('Обновление не требуется; перезапусков нет.')
            self.show_status(baseline)
            return
        self.prepare_runtimes()
        self.test_candidates()
        self.backup()
        self.prepare_switch()
        try:
            emit('Переключаю проверенные версии…')
            self.save('stopping')
            self.stop_units()
            self.switch()
            self.save('starting'); self.start_units()
            self.save('verifying'); report = self.wait_health()
            self.save('promoting'); self.promote_updaters()
            self.save('complete', health=report, database_restored=False)
            emit('Обновление завершено.')
            self.show_status(report)
        except BaseException:
            emit('Проверка не прошла. Выполняю общий откат…')
            # Further signals must not interrupt recovery; SIGKILL/power loss is handled by the next invocation.
            for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(signum, signal.SIG_IGN)
            self.rollback()
            self.show_status(self.state['health'])
            raise
        try: self.prune_backups()
        except Exception: emit('Старые копии сохранены: автоматическая очистка не завершилась.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Обновить Gym, Food, Supply и Core из GitHub main с проверкой и откатом')
    parser.add_argument('--check', action='store_true', help='Проверить версии, зависимости и запуск без переключения')
    parser.add_argument('--only', choices=list(REPOS), help='Обновить один продукт, проверить совместимость со всеми')
    args = parser.parse_args(argv)
    if os.geteuid() != 0: raise UpdateError('run_as_root')
    os.umask(0o077)
    CORE.mkdir(exist_ok=True, mode=0o755)
    def interrupted(signum, _frame): raise UpdateError('interrupted_signal_' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(signum, interrupted)
    with ExitStack() as stack:
        for file in ('ecosystem-update.lock', 'update.lock'):
            lock = stack.enter_context((CORE / file).open('a'))
            try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise UpdateError('another_update_is_running')
        Updater(only=args.only, check=args.check).execute()


if __name__ == '__main__':
    try: main()
    except Exception as error:
        reason = str(error)[:180] if isinstance(error, UpdateError) else type(error).__name__
        emit('Обновление не выполнено: ' + reason)
        emit('Подробности: ' + str(STATE) + '. До переключения рабочие версии не меняются; после него действует общий откат.')
        raise SystemExit(1)
