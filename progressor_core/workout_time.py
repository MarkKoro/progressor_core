"""Free activity provenance and pure known-time selectors; no writes or adoption."""
import math
import re
import sqlite3
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TIME_COVERAGE = 'Подсчёт использует сохранённое время программных тренировок и подтверждённое время свободных занятий. Старые свободные записи без привязки времени остаются в исходном дневнике.'


def canonical_clock(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError, OSError):
        return None


def parsed(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def recorded_activity_at(payload):
    """Saved source scalar, including invalid/legacy witnesses; never calendar UTC."""
    clock = payload.get('activity_clock')
    return canonical_clock(clock.get('source_last_activity')) if isinstance(clock, dict) else None


def free_activity_instant(payload, entity_id=None):
    """Validate all source proof fields, never a self-reported boolean alone."""
    try:
        entity_id = entity_id or payload.get('entity_id')
        match = re.fullmatch(r'workout:session:([1-9][0-9]*)', entity_id or '')
        if not match or type(payload.get('session_id')) is not int or payload['session_id'] != int(match[1]):
            return None
        if payload.get('day_index') != 0 or type(payload.get('day_index')) is not int:
            return None
        clock = payload['activity_clock']
        if not isinstance(clock, dict) or type(clock.get('version')) is not int or clock['version'] != 1 or clock.get('clock_kind') != 'native_touch':
            return None
        value = recorded_activity_at(payload)
        if value is None or any(payload.get(k) != value for k in ('recorded_at', 'completed_at')) or clock.get('activity_at') != value:
            return None
        if payload.get('activity_time_basis') != 'source_last_activity' or payload.get('activity_day_basis') != 'owner_validated_session_day' or payload.get('backfilled') is not False:
            return None
        day = payload['source_local_date']
        if date.fromisoformat(day).isoformat() != day or clock.get('source_local_date') != day:
            return None
        name = clock.get('activity_timezone')
        if not isinstance(name, str) or not name or payload.get('timezone') != name:
            return None
        stamp = parsed(value)
        if stamp.astimezone(_calendar_zone(name)).date().isoformat() != day:
            return None
        if type(payload.get('session_complete')) is not bool:
            return None
        return stamp
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def known_payload(payload, *, entity_id=None, completed=False, now=None):
    identity = entity_id or payload.get('entity_id')
    if isinstance(identity, str) and re.fullmatch(r'workout:[1-9][0-9]*', identity):
        stamp = parsed(payload.get('completed_at'))
    else:
        stamp = free_activity_instant(payload, identity)
    return bool(stamp is not None and (now is None or stamp <= now)
                and (not completed or payload.get('session_complete', True)))


def validate_activity_metadata(payload):
    """Optional new wire metadata is atomic; old envelopes keep old validation."""
    def require(condition):
        if not condition:
            raise ValueError('invalid_free_activity_metadata')
    identity = payload.get('entity_id')
    match = re.fullmatch(r'workout:session:([1-9][0-9]*)', identity or '') if isinstance(identity,str) else None
    require(match is not None and type(payload.get('session_id')) is int and payload['session_id'] == int(match[1]))
    require(type(payload.get('day_index')) is int and payload['day_index'] >= 0)
    clock = payload.get('activity_clock')
    require(isinstance(clock,dict) and type(clock.get('version')) is int and clock['version'] == 1)
    require(clock.get('clock_kind') in ('native_touch','recorded_only'))
    require(payload.get('activity_time_basis') in ('source_last_activity','recorded_only','not_recorded'))
    require(payload.get('activity_day_basis') in ('owner_validated_session_day','owner_transition_ledger','not_recorded','historical_edit'))
    require(type(payload.get('backfilled')) is bool and type(payload.get('session_complete')) is bool)
    day = payload.get('source_local_date')
    try:
        require(isinstance(day,str) and date.fromisoformat(day).isoformat() == day)
    except (ValueError,TypeError):
        require(False)
    require(clock.get('source_local_date') == day)
    raw = clock.get('source_last_activity'); saved = canonical_clock(raw)
    require(raw is None or saved is not None)
    require(clock.get('activity_at') == saved)
    if clock['clock_kind'] == 'native_touch':
        require(free_activity_instant(payload) is not None and payload.get('timestamp_basis') == 'source_utc')
    else:
        require(clock.get('activity_timezone') is None and payload['backfilled'] is True)
        recorded = payload.get('recorded_at')
        require(recorded is None or parsed(recorded) is not None)
        require(saved is None or recorded == saved)
        require(payload['activity_time_basis'] == ('recorded_only' if recorded else 'not_recorded'))
        require(payload.get('timestamp_basis') == ('source_utc' if recorded else 'session_local_day'))
        if payload['activity_day_basis'] in ('owner_transition_ledger','historical_edit'):
            try:
                _calendar_zone(payload.get('timezone'))
            except (ValueError,KeyError,TypeError):
                require(False)
        else:
            require(payload['activity_day_basis'] == 'not_recorded' and 'timezone' not in payload)
    if payload.get('completion_recorded_at') is not None:
        require(parsed(payload['completion_recorded_at']) is not None)


def known_workout(entity, *, completed=False, now=None):
    return entity.get('source') == 'gym' and known_payload(entity.get('payload') or {},
        entity_id=entity.get('entity_id'), completed=completed, now=now)


def completed_window(entities, now, *, days=14, limit=20):
    """One shared completed, known, nonfuture and bounded list for both AI uses."""
    start = now - timedelta(days=days)
    records = [e for e in entities if known_workout(e, completed=True, now=now)
               and parsed(e['payload']['completed_at']) >= start]
    records.sort(key=lambda e: (parsed(e['payload']['completed_at']), e['entity_id']))
    return records[-limit:]


def _calendar_zone(name):
    if not isinstance(name, str) or not name:
        raise ValueError('missing_zone')
    match = re.fullmatch(r'UTC([+-])(\d{2}):(\d{2})', name)
    if match:
        hours, remainder = int(match[2]), int(match[3])
        if hours > 14 or remainder > 59 or (hours == 14 and remainder):
            raise ValueError('invalid_timezone')
        minutes = hours * 60 + remainder
        return timezone(timedelta(minutes=minutes * (1 if match[1] == '+' else -1)))
    if len(name) > 80:
        raise ValueError('invalid_timezone')
    return ZoneInfo(name)


class GymFreeTime:
    """Load optional sidecars/owner intervals once in the native snapshot."""
    def __init__(self, db, users):
        self.proofs, self.histories = {}, {}
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='progressor_free_activity_proof'").fetchone():
                columns = {r['name']: r for r in db.execute('PRAGMA table_info(progressor_free_activity_proof)')}
                required = {'session_id','last_activity','source_local_date','activity_timezone','proof_version','clock_kind'}
                if set(columns) == required and columns['session_id']['pk'] == 1 and columns['session_id']['type'].upper() == 'INTEGER':
                    rows = list(db.execute('SELECT session_id,last_activity,source_local_date,activity_timezone,proof_version,clock_kind FROM progressor_free_activity_proof'))
                    proofs = {r['session_id']: dict(r) for r in rows}
                    if len(proofs) == len(rows):
                        self.proofs = proofs
        except sqlite3.Error:
            self.proofs = {}
        owners = {str(u['tg_id']): uid for uid, u in users.items()}
        chains, invalid = {uid: [] for uid in users}, set()
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='progressor_timezone_history'").fetchone():
                return
            for r in db.execute('SELECT user_id,changed_at,before_zone,after_zone FROM progressor_timezone_history ORDER BY user_id,changed_at'):
                uid = owners.get(r['user_id'])
                if uid is None:
                    continue
                chain = chains[uid]
                try:
                    stamp, before, after = r['changed_at'], r['before_zone'], r['after_zone']
                    if canonical_clock(stamp) is None or before == after:
                        raise ValueError('invalid_transition')
                    _calendar_zone(before); _calendar_zone(after)
                    if chain and (stamp <= chain[-1][0] or before != chain[-1][2]):
                        raise ValueError('broken_transition')
                    chain.append((stamp, before, after))
                except (ValueError, KeyError, TypeError, OverflowError):
                    invalid.add(uid)
        except sqlite3.Error:
            return
        self.histories = {uid: (tuple(r[0] for r in chain), tuple(r[2] for r in chain)) for uid, chain in chains.items() if chain and uid not in invalid
                          and chain[-1][2] == (users[uid]['tz'] or 'UTC')}

    def calendar(self, owner_id, clock, day):
        history = self.histories.get(owner_id)
        if not history or canonical_clock(clock) is None:
            return {}
        times, zones = history
        index = bisect_right(times, clock) - 1
        # The first before-zone is an unbounded prefix; equal serialized clocks
        # cannot establish whether a touch preceded a transition.
        if index < 0 or any(canonical_clock(t) == canonical_clock(clock) for t in times[max(0,index):index+2]):
            return {}
        name = zones[index]
        same = datetime.fromtimestamp(clock, _calendar_zone(name)).date().isoformat() == day
        return {'timezone': name, 'activity_day_basis': 'owner_transition_ledger' if same else 'historical_edit'}

    def resolve(self, session, free, mark_clock, fallback):
        day = session['date']
        raw = free['last_activity'] if free else None
        value = canonical_clock(raw)
        finish = bool(free and free['status'] == 'finished')
        saved_finish = parsed(free['completed_at']) if finish and free['completed_at'] else None
        completed = saved_finish.isoformat().replace('+00:00', 'Z') if saved_finish else value or mark_clock or fallback
        recorded = value or mark_clock
        proof = self.proofs.get(session['id'], {})
        valid = False
        if value is not None:
            try:
                valid = (session['day_index'] == 0 and free['status'] in ('active', 'finished') and type(proof.get('proof_version')) is int
                         and proof['proof_version'] == 1 and proof.get('clock_kind') == 'native_touch'
                         and type(proof.get('last_activity')) in (int, float) and proof['last_activity'] == raw
                         and proof.get('source_local_date') == day and isinstance(proof.get('activity_timezone'), str)
                         and bool(proof['activity_timezone'])
                         and datetime.fromtimestamp(raw, _calendar_zone(proof['activity_timezone'])).date().isoformat() == day
                         and (not finish or free['completed_at'] == datetime.fromtimestamp(raw, timezone.utc).isoformat()))
            except (KeyError, ValueError, TypeError, OverflowError):
                valid = False
        metadata = {'timezone': proof['activity_timezone'], 'activity_day_basis': 'owner_validated_session_day'} if valid else self.calendar(session['user_id'], raw, day)
        metadata.setdefault('activity_day_basis', 'not_recorded')
        clock = {'version': 1, 'clock_kind': 'native_touch' if valid else 'recorded_only',
                 'source_last_activity': raw if value is not None else None, 'activity_at': value,
                 'source_local_date': day, 'activity_timezone': proof['activity_timezone'] if valid else None}
        return {'completed_at': completed, 'recorded_at': recorded, 'activity_clock': clock,
                'activity_time_basis': 'source_last_activity' if valid else 'recorded_only' if recorded else 'not_recorded',
                'backfilled': not valid, 'timestamp_basis': 'source_utc' if recorded else 'session_local_day', **metadata}
