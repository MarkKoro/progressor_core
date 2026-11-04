"""Durable free-workout notification admission, owned only by Core.

Startup may adopt the schema once. Only successful Gym reconciliation writes
observations. Candidate reads never create policy, identities or admissions.
"""
import math
import re
import sqlite3
import time
from datetime import datetime, timezone

from .contracts import digest, subject
from .workout_time import free_activity_instant, recorded_activity_at

POLICY_OBJECTS = ('free_workout_notification_policy', 'free_workout_notification_admissions')
OWNER_TRIGGER = 'identities_delete_free_workout_admissions'
MARKER_INDEX = 'free_workout_notification_unknown_floor'
RECEIPT_BATCH = 128
POLICY_SQL = '''CREATE TABLE free_workout_notification_policy(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 protocol INTEGER NOT NULL CHECK(protocol=1),
 adopted_at REAL NOT NULL
)'''
ADMISSIONS_SQL = '''CREATE TABLE free_workout_notification_admissions(
 user_id TEXT NOT NULL,
 entity_id TEXT NOT NULL,
 clock_bucket TEXT NOT NULL,
 source_activity_at TEXT,
 first_observed_at REAL NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('admitted','denied','revoked')),
 reason TEXT NOT NULL,
 PRIMARY KEY(user_id,entity_id,clock_bucket)
)'''
OWNER_TRIGGER_SQL = '''CREATE TRIGGER identities_delete_free_workout_admissions
AFTER DELETE ON identities BEGIN
 DELETE FROM free_workout_notification_admissions WHERE user_id=old.user_id;
END'''
MARKER_INDEX_SQL = '''CREATE INDEX free_workout_notification_unknown_floor
ON free_workout_notification_admissions(user_id,entity_id,first_observed_at DESC,clock_bucket DESC)
WHERE source_activity_at IS NULL'''


def _epoch(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value < 253402300800


def _stamp(now):
    value = time.time() if now is None else now
    if not _epoch(value):
        raise ValueError('invalid_notification_clock')
    # The source's canonical buckets have Python/ISO microsecond precision.
    # Equal serialized policy/activity instants must not qualify by a smaller
    # sub-microsecond floating-point remainder in the policy clock.
    return datetime.fromtimestamp(value, timezone.utc).timestamp()


def _owner(value):
    try:
        return isinstance(value, str) and subject(value) == value
    except ValueError:
        return False


def _free(entity_id):
    return isinstance(entity_id, str) and len(entity_id) <= 128 and re.fullmatch(r'workout:session:[1-9][0-9]*', entity_id) is not None


def _sql(value):
    # Compare source-owned DDL conservatively. Whitespace outside quotes may
    # differ in sqlite_master; quoted CHECK values must retain every byte.
    output, quote, pending_space, index = [], None, False, 0
    while index < len(value):
        character = value[index]
        if quote is not None:
            output.append(character)
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    output.append(value[index + 1]); index += 1
                else:
                    quote = None
        elif character.isspace():
            pending_space = bool(output)
        else:
            if pending_space: output.append(' ')
            pending_space = False
            output.append(character)
            if character in "'\"`[": quote = ']' if character == '[' else character
        index += 1
    if quote is not None:
        raise ValueError('unterminated_notification_schema_quote')
    return ''.join(output).rstrip(';')


def _objects(db):
    rows = db.execute(
        'SELECT name,type,sql FROM sqlite_master WHERE name COLLATE NOCASE IN (?,?,?,?)',
        (*POLICY_OBJECTS, OWNER_TRIGGER, MARKER_INDEX)).fetchall()
    objects = {name.casefold(): (name, kind, sql) for name, kind, sql in rows}
    # SQLite permits a trigger to reuse a table's name. Never let dict ordering
    # hide an extra reserved object in a distinct namespace.
    if len(objects) != len(rows):
        raise ValueError('ambiguous_notification_policy_objects')
    return objects


def _tables_valid(objects):
    for name, expected in zip(POLICY_OBJECTS, (POLICY_SQL, ADMISSIONS_SQL)):
        found = objects.get(name)
        if not found or found[0] != name or found[1] != 'table' or not isinstance(found[2], str) or _sql(found[2]) != _sql(expected):
            return False
    return True


def _policy(db, now):
    objects = _objects(db)
    trigger = objects.get(OWNER_TRIGGER)
    if not _tables_valid(objects) or not trigger or trigger[0] != OWNER_TRIGGER or trigger[1] != 'trigger' or not isinstance(trigger[2], str) or _sql(trigger[2]) != _sql(OWNER_TRIGGER_SQL):
        return None
    index = objects.get(MARKER_INDEX)
    if not index or index[0] != MARKER_INDEX or index[1] != 'index' or not isinstance(index[2], str) or _sql(index[2]) != _sql(MARKER_INDEX_SQL):
        return None
    rows = db.execute('SELECT singleton,protocol,adopted_at FROM free_workout_notification_policy').fetchall()
    if len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] != 1:
        return None
    value = rows[0][2]
    return float(value) if _epoch(value) and value == _stamp(value) and value <= now else None


def initialize(db, *, now=None):
    """Declared startup migration; never reset or repair a partial adoption.

    Malformed existing policy disables free admission while other Core features
    remain usable. A savepoint prevents a failed first adoption leaving pieces.
    The enclosing startup transaction owns commit; reads must not call this.
    """
    if not db.in_transaction:
        raise ValueError('notification_adoption_requires_transaction')
    stamp = _stamp(now)
    db.execute('SAVEPOINT free_workout_adoption')
    try:
        objects = _objects(db)
        if not any(name in objects for name in POLICY_OBJECTS):
            # An unrelated/malformed old trigger must not be silently replaced.
            if OWNER_TRIGGER in objects or MARKER_INDEX in objects:
                raise ValueError('unexpected_notification_cleanup_trigger')
            db.execute(POLICY_SQL)
            db.execute(ADMISSIONS_SQL)
            db.execute('INSERT INTO free_workout_notification_policy VALUES(1,1,?)', (stamp,))
            db.execute(OWNER_TRIGGER_SQL)
            db.execute(MARKER_INDEX_SQL)
        elif _tables_valid(objects):
            # A valid retained policy may need its additive dedicated trigger;
            # validate the existing singleton before any migration write.
            rows = db.execute('SELECT singleton,protocol,adopted_at FROM free_workout_notification_policy').fetchall()
            if len(rows) != 1 or tuple(rows[0][:2]) != (1, 1) or not _epoch(rows[0][2]) or rows[0][2] > stamp:
                raise ValueError('invalid_retained_notification_epoch')
            if OWNER_TRIGGER not in objects:
                db.execute(OWNER_TRIGGER_SQL)
            if MARKER_INDEX not in objects:
                db.execute(MARKER_INDEX_SQL)
        valid = _policy(db, stamp) is not None
        if not valid:
            raise ValueError('invalid_retained_notification_policy')
    except (sqlite3.Error, ValueError, TypeError):
        db.execute('ROLLBACK TO free_workout_adoption')
        db.execute('RELEASE free_workout_adoption')
        return False
    db.execute('RELEASE free_workout_adoption')
    return True


def _identity(db, user_id, now):
    row = db.execute('SELECT created_at FROM identities WHERE user_id=?', (user_id,)).fetchone()
    if not row or not isinstance(row[0], str):
        return None
    try:
        value = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
        if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
            return None
        if value.isoformat().replace('+00:00', 'Z') != row[0].replace('+00:00', 'Z'):
            return None
        stamp = value.timestamp()
        return stamp if _epoch(stamp) and stamp <= now else None
    except (ValueError, OverflowError, OSError):
        return None


def _canonical(value):
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
            return None
        if instant.isoformat().replace('+00:00', 'Z') != value or not _epoch(instant.timestamp()):
            return None
        return instant
    except (ValueError, OverflowError, OSError):
        return None


def _marker_floor(db, user_id, entity_id, now):
    row = db.execute('''SELECT clock_bucket,first_observed_at,decision
        FROM free_workout_notification_admissions INDEXED BY free_workout_notification_unknown_floor
        WHERE user_id=? AND entity_id=? AND source_activity_at IS NULL
        ORDER BY first_observed_at DESC,clock_bucket DESC LIMIT 1''', (user_id, entity_id)).fetchone()
    if row is None:
        return 0.0
    bucket, observed, decision = row
    if bucket != 'unknown' and not (isinstance(bucket, str) and bucket.startswith('unknown:deleted:') and _canonical(bucket.removeprefix('unknown:deleted:'))):
        return None
    if decision not in ('denied', 'revoked') or not _epoch(observed) or observed != _stamp(observed) or observed > now:
        return None
    return observed


def receipt_probe_sql(size):
    """Bounded VALUES outer loop, exact composite-PK point seeks."""
    if type(size) is not int or not 1 <= size <= RECEIPT_BATCH:
        raise ValueError('invalid_notification_probe_size')
    return '''WITH wanted(user_id,entity_id,clock_bucket) AS (VALUES ''' + ','.join(['(?,?,?)'] * size) + ''')
        SELECT w.user_id,w.entity_id,w.clock_bucket FROM wanted w CROSS JOIN
        free_workout_notification_admissions a INDEXED BY sqlite_autoindex_free_workout_notification_admissions_1
        WHERE a.user_id=w.user_id AND a.entity_id=w.entity_id AND a.clock_bucket=w.clock_bucket'''


def _existing_buckets(db, keys):
    found = set()
    values = sorted(set(keys))
    for offset in range(0, len(values), RECEIPT_BATCH):
        chunk = values[offset:offset + RECEIPT_BATCH]
        found.update(tuple(row) for row in db.execute(receipt_probe_sql(len(chunk)),
            [value for key in chunk for value in key]))
    return found


def _existing_deletions(db, keys):
    """At most one indexed latest-marker read per supplied entity, in batches."""
    found = set()
    values = sorted(set(keys))
    for offset in range(0, len(values), RECEIPT_BATCH):
        chunk = values[offset:offset + RECEIPT_BATCH]
        sql = '''WITH wanted(user_id,entity_id) AS (VALUES ''' + ','.join(['(?,?)'] * len(chunk)) + ''')
            SELECT w.user_id,w.entity_id,(SELECT clock_bucket FROM free_workout_notification_admissions a
                INDEXED BY free_workout_notification_unknown_floor
                WHERE a.user_id=w.user_id AND a.entity_id=w.entity_id AND a.source_activity_at IS NULL
                ORDER BY first_observed_at DESC,clock_bucket DESC LIMIT 1) FROM wanted w'''
        for owner, entity, marker in db.execute(sql, [value for key in chunk for value in key]):
            if isinstance(marker, str) and marker.startswith('unknown:deleted:'):
                found.add((owner, entity))
    return found


def allowed(db, user_id, entity_id, payload, *, now=None):
    """Fail closed without writes; all ordinary notification guards are extra."""
    if not _owner(user_id) or not _free(entity_id) or not isinstance(payload, dict):
        return False
    try:
        stamp = _stamp(now)
        epoch = _policy(db, stamp)
        identity = _identity(db, user_id, stamp)
        activity = free_activity_instant(payload, entity_id)
        bucket = recorded_activity_at(payload)
        recorded = _canonical(bucket)
        floor = _marker_floor(db, user_id, entity_id, stamp) if epoch is not None else None
        if epoch is None or identity is None or floor is None or activity is None or recorded is None or activity != recorded:
            return False
        value = activity.timestamp()
        if not max(epoch, identity, floor) < value <= stamp:
            return False
        row = db.execute('''SELECT source_activity_at,first_observed_at,decision
            FROM free_workout_notification_admissions WHERE user_id=? AND entity_id=? AND clock_bucket=?''',
            (user_id, entity_id, bucket)).fetchone()
        return bool(row and row[0] == bucket and _epoch(row[1]) and value <= row[1] <= stamp and row[2] == 'admitted')
    except (sqlite3.Error, ValueError, TypeError, OverflowError, OSError):
        return False


def _insert(db, user_id, entity_id, bucket, activity, now, decision, reason):
    db.execute('''INSERT OR IGNORE INTO free_workout_notification_admissions
        VALUES(?,?,?,?,?,?,?)''', (user_id, entity_id, bucket, activity, now, decision, reason))


def _observe(db, item, epoch, now):
    user_id, entity_id = item.get('user_id'), item.get('entity_id')
    if not _owner(user_id) or not _free(entity_id):
        return
    payload = item.get('payload')
    if not isinstance(payload, dict):
        return
    if item.get('event_type') not in ('workout.completed', 'workout.updated') or payload.get('deleted') is True:
        return
    identity = _identity(db, user_id, now)
    if identity is None:
        return
    recorded = recorded_activity_at(payload)
    instant = _canonical(recorded)
    if instant is None:
        _insert(db, user_id, entity_id, 'unknown', None, now, 'denied', 'unknown_clock')
        return
    value = instant.timestamp()
    floor = _marker_floor(db, user_id, entity_id, now)
    proven = free_activity_instant(payload, entity_id)
    decision, reason = 'denied', 'not_native_touch'
    if value > now:
        reason = 'future_clock'
    elif identity is None or value <= max(epoch, identity):
        reason = 'pre_policy_or_identity'
    elif floor is None or value <= floor:
        reason = 'prior_unknown_observation'
    elif proven is not None and proven == instant:
        decision, reason = 'admitted', 'native_touch'
    if decision == 'denied':
        # A successful source observation can invalidate a previously trusted
        # same-clock witness (including an old Gym touch during fallback).
        # Later metadata repair must not reopen that admission.
        db.execute('''UPDATE free_workout_notification_admissions SET decision='revoked',reason=?
            WHERE user_id=? AND entity_id=? AND clock_bucket=? AND decision='admitted' ''',
            (reason, user_id, entity_id, recorded))
    _insert(db, user_id, entity_id, recorded, recorded, now, decision, reason)


def _revoke(db, user_id, entity_id, now):
    if not _owner(user_id) or not _free(entity_id) or _identity(db, user_id, now) is None:
        return
    db.execute('''UPDATE free_workout_notification_admissions SET decision='revoked',reason='source_deleted'
        WHERE user_id=? AND entity_id=? AND decision='admitted' ''', (user_id, entity_id))
    bucket = 'unknown:deleted:' + datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')
    _insert(db, user_id, entity_id, bucket, None, now, 'revoked', 'source_deleted')


def observe_snapshot(db, snapshot, previous, *, now=None):
    """Successful complete Gym snapshot only, inside its reconcile transaction.

    Observe every current free clock, including byte-identical adapter rows.
    Only absence from this successful complete snapshot proves source deletion.
    Failure, access/source-off, expiry, rest and read paths do not call this.
    """
    if not db.in_transaction:
        raise ValueError('notification_observation_requires_transaction')
    stamp = _stamp(now)
    try:
        epoch = _policy(db, stamp)
    except (sqlite3.Error, ValueError, TypeError):
        return
    if epoch is None:
        return
    current = {item['entity_id']: item for item in snapshot['entities']}
    unchanged = {entity_id for entity_id, item in current.items()
        if _free(entity_id) and entity_id in previous and previous[entity_id]['hash'] == digest(item)}
    buckets, deletions = {}, {}
    for entity_id in unchanged:
        item = current[entity_id]
        owner = item.get('user_id')
        if not _owner(owner) or not isinstance(item.get('payload'), dict):
            continue
        if item.get('event_type') in ('workout.deleted', 'entity.deleted') or item['payload'].get('deleted') is True:
            deletions[entity_id] = (owner, entity_id)
        else:
            buckets[entity_id] = (owner, entity_id, recorded_activity_at(item['payload']) or 'unknown')
    existing = _existing_buckets(db, buckets.values())
    deleted = _existing_deletions(db, deletions.values())
    for entity_id, item in current.items():
        if buckets.get(entity_id) in existing or deletions.get(entity_id) in deleted:
            continue
        if item.get('event_type') in ('workout.deleted', 'entity.deleted') or item.get('payload', {}).get('deleted') is True:
            _revoke(db, item.get('user_id'), entity_id, stamp)
        else:
            _observe(db, item, epoch, stamp)
    for entity_id, prior in previous.items():
        if entity_id not in current and not prior['deleted']:
            _revoke(db, prior['user_id'], entity_id, stamp)
