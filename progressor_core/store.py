import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .contracts import canonical, digest, now_utc, validate

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS identities(user_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(source TEXT NOT NULL, local_id TEXT NOT NULL, user_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(source, local_id));
CREATE INDEX IF NOT EXISTS membership_user ON memberships(user_id);
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, hash TEXT NOT NULL, source TEXT NOT NULL, user_id TEXT NOT NULL, type TEXT NOT NULL, occurred_at TEXT NOT NULL, received_at TEXT NOT NULL, correlation_id TEXT NOT NULL, envelope TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities(source TEXT NOT NULL, entity_id TEXT NOT NULL, user_id TEXT NOT NULL, revision INTEGER NOT NULL, hash TEXT NOT NULL, event_id TEXT NOT NULL, type TEXT NOT NULL, deleted INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(source,entity_id));
CREATE INDEX IF NOT EXISTS entities_user ON entities(user_id,source,deleted);
CREATE TABLE IF NOT EXISTS source_state(source TEXT PRIMARY KEY, status TEXT NOT NULL, observed_at REAL NOT NULL, last_success REAL, failures INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0, reason TEXT);
CREATE TABLE IF NOT EXISTS adapter_state(source TEXT NOT NULL, entity_id TEXT NOT NULL, user_id TEXT NOT NULL, revision INTEGER NOT NULL, hash TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source,entity_id));
CREATE TABLE IF NOT EXISTS dead_letters(id INTEGER PRIMARY KEY, source TEXT NOT NULL, reason TEXT NOT NULL, payload_hash TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recommendations(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,rule TEXT NOT NULL,window TEXT NOT NULL,fingerprint TEXT NOT NULL,created_at TEXT NOT NULL,active INTEGER NOT NULL,payload TEXT NOT NULL, UNIQUE(user_id,rule,window,fingerprint));
CREATE TABLE IF NOT EXISTS notification_routes(recommendation_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,destination TEXT NOT NULL,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hint_preferences(user_id TEXT NOT NULL,target TEXT NOT NULL,dismissed_until REAL NOT NULL,PRIMARY KEY(user_id,target));
CREATE TABLE IF NOT EXISTS offer_preferences(user_id TEXT NOT NULL,target TEXT NOT NULL,dismissed_until REAL NOT NULL,PRIMARY KEY(user_id,target));
CREATE TABLE IF NOT EXISTS hint_seen(user_id TEXT NOT NULL,target TEXT NOT NULL,delivery_key TEXT NOT NULL,seen_at REAL NOT NULL,PRIMARY KEY(user_id,target,delivery_key));
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            from .connections import SCHEMA as CONNECTION_SCHEMA
            db.executescript(CONNECTION_SCHEMA)
            if db.execute('SELECT max(version) FROM schema_version').fetchone()[0] != 1:
                raise RuntimeError('unsupported_core_schema')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=5000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def accept(self, event, db=None):
        event = validate(event)
        if db is None:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                return self.accept(event, db)
        event_hash = digest(event)
        old = db.execute('SELECT hash FROM events WHERE event_id=?', (event['event_id'],)).fetchone()
        if old:
            if old['hash'] != event_hash:
                raise ValueError('event_id_conflict')
            return 'duplicate'
        payload = event['payload']
        old = db.execute('SELECT * FROM entities WHERE source=? AND entity_id=?', (event['source'], payload['entity_id'])).fetchone()
        if old and old['user_id'] != event['user_id']:
            raise ValueError('entity_subject_conflict')
        if old and old['revision'] == payload['revision'] and old['hash'] != event_hash:
            raise ValueError('entity_revision_conflict')
        db.execute('INSERT OR IGNORE INTO identities VALUES(?,?)', (event['user_id'], now_utc()))
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)', (event['event_id'], event_hash, event['source'], event['user_id'], event['event_type'], event['occurred_at'], now_utc(), event['correlation_id'], canonical(event)))
        if old and old['revision'] >= payload['revision']:
            return 'out_of_order'
        deleted = event['event_type'].endswith('.deleted') or payload.get('deleted') is True
        from .connection_changes import record
        record(db,event,old)
        db.execute('INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(source,entity_id) DO UPDATE SET revision=excluded.revision,hash=excluded.hash,event_id=excluded.event_id,type=excluded.type,deleted=excluded.deleted,payload=excluded.payload', (event['source'], payload['entity_id'], event['user_id'], payload['revision'], event_hash, event['event_id'], event['event_type'], int(deleted), canonical(payload)))
        if event['source']=='gym' and ((payload.get('profile_kind')=='coach_link' and (payload.get('status')!='accepted' or payload.get('coach_enabled') is not True))
                or (deleted and old and __import__('json').loads(old['payload']).get('profile_kind')=='coach_link')):
            prior=payload if not deleted else __import__('json').loads(old['payload'])
            db.execute('UPDATE coach_nutrition_permissions SET macros=0,top_dishes=0,expires_at=0 WHERE trainee_id=? AND coach_id=? AND link_id=?',
                (event['user_id'],prior['coach_id'],prior['link_id']))
        return 'accepted'

    def reconcile(self, source, snapshot):
        current = {item['entity_id']: item for item in snapshot['entities']}
        if len(current) != len(snapshot['entities']):
            raise ValueError('duplicate_snapshot_entity')
        with self.connection() as db:
            previous = {row['entity_id']: dict(row) for row in db.execute('SELECT * FROM adapter_state WHERE source=?', (source,))}
            db.execute('UPDATE memberships SET active=0 WHERE source=?', (source,))
            for member in snapshot['memberships']:
                existing = db.execute('SELECT user_id FROM memberships WHERE source=? AND local_id=?', (source, member['local_id'])).fetchone()
                if existing and existing['user_id'] != member['user_id']:
                    raise ValueError('membership_subject_changed')
                db.execute('INSERT OR IGNORE INTO identities VALUES(?,?)', (member['user_id'], now_utc()))
                db.execute('INSERT INTO memberships VALUES(?,?,?,1) ON CONFLICT(source,local_id) DO UPDATE SET active=1', (source, member['local_id'], member['user_id']))
            changed = 0
            for entity_id in sorted(set(current) | set(previous)):
                item, prior = current.get(entity_id), previous.get(entity_id)
                content_hash = digest(item) if item else 'deleted'
                if prior and prior['hash'] == content_hash:
                    continue
                revision = prior['revision'] + 1 if prior else 1
                if item:
                    user_id = item['user_id']
                    payload = {**item['payload'], 'entity_id': entity_id, 'revision': revision, 'historical': prior is None}
                    event_type = item['event_type']
                    if prior and event_type in ('workout.completed', 'meal.logged', 'lab.created'):
                        event_type = {'workout.completed': 'workout.updated', 'meal.logged': 'meal.updated', 'lab.created': 'lab.updated'}[event_type]
                    occurred_at = item['occurred_at']
                else:
                    user_id = prior['user_id']
                    payload = {'entity_id': entity_id, 'revision': revision, 'deleted': True}
                    event_type = 'workout.deleted' if entity_id.startswith('workout:') else 'meal.deleted' if entity_id.startswith('meal:') else 'entity.deleted'
                    occurred_at = now_utc()
                event_id = digest([source, entity_id, revision, content_hash])
                event = {'event_id': event_id, 'event_type': event_type, 'schema_version': 1, 'source': source, 'user_id': user_id, 'occurred_at': occurred_at, 'correlation_id': event_id, 'payload': payload}
                self.accept(event, db)
                db.execute('INSERT INTO adapter_state VALUES(?,?,?,?,?,?) ON CONFLICT(source,entity_id) DO UPDATE SET revision=excluded.revision,hash=excluded.hash,deleted=excluded.deleted', (source, entity_id, user_id, revision, content_hash, int(item is None)))
                changed += 1
            stamp = time.time()
            db.execute("INSERT INTO source_state VALUES(?,'ok',?,?,0,0,NULL) ON CONFLICT(source) DO UPDATE SET status='ok',observed_at=excluded.observed_at,last_success=excluded.last_success,failures=0,retry_at=0,reason=NULL", (source, stamp, stamp))
            if source=='gym':
                from .connection_changes import revoke_coach_permissions
                revoke_coach_permissions(db)
        return changed

    def failed(self, source, reason):
        with self.connection() as db:
            old = db.execute('SELECT * FROM source_state WHERE source=?', (source,)).fetchone()
            count = old['failures'] + 1 if old else 1
            stamp = time.time()
            db.execute("INSERT INTO source_state VALUES(?,'degraded',?,?,?, ?,?) ON CONFLICT(source) DO UPDATE SET status='degraded',observed_at=excluded.observed_at,failures=excluded.failures,retry_at=excluded.retry_at,reason=excluded.reason", (source, stamp, old['last_success'] if old else None, count, stamp + min(300, 15 * 2**min(count - 1, 5)), reason))

    def data(self, user_id):
        import json
        with self.connection() as db:
            entities = [{**dict(row), 'payload': json.loads(row['payload'])} for row in db.execute('SELECT e.*,ev.occurred_at FROM entities e JOIN events ev ON ev.event_id=e.event_id WHERE e.user_id=? AND e.deleted=0', (user_id,))]
            memberships = [dict(row) for row in db.execute('SELECT source,local_id,active FROM memberships WHERE user_id=?', (user_id,))]
            state = {row['source']: dict(row) for row in db.execute('SELECT * FROM source_state')}
        return entities, memberships, state

    def remember(self, user_id, rule, window, recommendation):
        fingerprint = digest(recommendation) if recommendation else None
        with self.connection() as db:
            db.execute('UPDATE recommendations SET active=0 WHERE user_id=? AND rule=? AND window=?', (user_id, rule, window))
            if recommendation is None:
                return None
            rec_id = digest([user_id, rule, window, fingerprint])
            db.execute('INSERT INTO recommendations VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET active=1', (rec_id, user_id, rule, window, fingerprint, now_utc(), canonical(recommendation)))
            db.execute("INSERT OR IGNORE INTO notification_routes VALUES(?,?,?,'webapp_only')", (rec_id, user_id, 'supply'))
        return rec_id

    def dismiss_hints(self, user_id, target):
        until=time.time()+7*86400
        with self.connection() as db:
            db.execute('INSERT INTO hint_preferences VALUES(?,?,?) ON CONFLICT(user_id,target) DO UPDATE SET dismissed_until=excluded.dismissed_until',(user_id,target,until))
        return until

    def mark_hint_seen(self,user_id,target,delivery_key):
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO hint_seen VALUES(?,?,?,?)',(user_id,target,delivery_key,time.time()))
            db.execute('DELETE FROM hint_seen WHERE seen_at<?',(time.time()-90*86400,))

    def hint_was_seen(self,user_id,target,delivery_key):
        with self.connection() as db:
            return bool(db.execute('SELECT 1 FROM hint_seen WHERE user_id=? AND target=? AND delivery_key=?',(user_id,target,delivery_key)).fetchone())

    def hints_dismissed(self, user_id, target):
        with self.connection() as db:
            row=db.execute('SELECT dismissed_until FROM hint_preferences WHERE user_id=? AND target=?',(user_id,target)).fetchone()
        return bool(row and row[0]>time.time())

    def dismiss_offers(self, user_id, target):
        until=time.time()+7*86400
        with self.connection() as db:
            db.execute('INSERT INTO offer_preferences VALUES(?,?,?) ON CONFLICT(user_id,target) DO UPDATE SET dismissed_until=excluded.dismissed_until',(user_id,target,until))
        return until

    def offers_dismissed(self, user_id, target):
        with self.connection() as db:
            row=db.execute('SELECT dismissed_until FROM offer_preferences WHERE user_id=? AND target=?',(user_id,target)).fetchone()
        return bool(row and row[0]>time.time())
