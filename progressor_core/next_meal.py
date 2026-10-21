"""Explicit next-meal intent. Never a consumed meal or a source-owner write."""
from datetime import datetime, timezone
import json
import re
from zoneinfo import ZoneInfo
from pathlib import Path

from .access import active_until, entitlements
from .connections import preferences_from_connection
from .contracts import digest, subject
from .meal_ideas import VERSION, NOTE, ideas

NEXT_MEAL_PROTOCOL = 1
NEXT_MEAL_GATE = Path('/var/lib/progressor/next-meal-v1-ready')

def enabled(store):
    path=getattr(store,'next_meal_gate',NEXT_MEAL_GATE)
    if path is None:return False
    try:Path(path).lstat()
    except OSError:return False
    return True

SCHEMA = '''
CREATE TABLE IF NOT EXISTS next_meal_choices(
 user_id TEXT PRIMARY KEY,day TEXT NOT NULL,revision INTEGER NOT NULL,
 idea_id TEXT,preferences_revision INTEGER NOT NULL,catalog_version INTEGER NOT NULL,
 updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS next_meal_receipts(
 user_id TEXT NOT NULL,operation_id TEXT NOT NULL,request_hash TEXT NOT NULL,
 applied_revision INTEGER NOT NULL,day TEXT NOT NULL,expires_at REAL NOT NULL,
 PRIMARY KEY(user_id,operation_id));
CREATE INDEX IF NOT EXISTS next_meal_receipts_expiry ON next_meal_receipts(expires_at);
CREATE INDEX IF NOT EXISTS next_meal_receipts_owner_expiry ON next_meal_receipts(user_id,expires_at);
CREATE TABLE IF NOT EXISTS next_meal_owner_resets(user_id TEXT PRIMARY KEY,revision INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS identities_delete_choices AFTER DELETE ON identities BEGIN
 DELETE FROM next_meal_choices WHERE user_id=OLD.user_id;
 DELETE FROM next_meal_receipts WHERE user_id=OLD.user_id;
 DELETE FROM next_meal_owner_resets WHERE user_id=OLD.user_id;
 DELETE FROM connection_preferences WHERE user_id=OLD.user_id;
 DELETE FROM connection_preference_versions WHERE user_id=OLD.user_id;
END;
'''
MOSCOW = ZoneInfo('Europe/Moscow')
RECEIPT_TTL = 86400
MAX_OWNER_RECEIPTS = 64


class ChoiceConflict(ValueError):
    pass


def _food_ready(db, store, uid, preferences, now):
    if 'food' not in getattr(store, 'enabled_sources', ('gym','food','supply')):
        return 'connection_unavailable'
    if not preferences['sources'].get('food'):
        return 'food_connection_disabled'
    if not db.execute("SELECT 1 FROM memberships WHERE source='food' AND user_id=? AND active=1", (uid,)).fetchone():
        return 'food_access_required'
    state = db.execute("SELECT status,last_success FROM source_state WHERE source='food'").fetchone()
    if (not state or state['status'] != 'ok' or type(state['last_success']) not in (int,float)
            or not -5 <= now.timestamp() - state['last_success'] < 120):
        return 'connection_unavailable'
    profiles = [{'source':'food', 'entity_id': row['entity_id'], 'payload':json.loads(row['payload'])}
                for row in db.execute("SELECT entity_id,payload FROM entities WHERE source='food' AND user_id=? AND deleted=0 AND entity_id GLOB 'profile:*'", (uid,))]
    base = [item for item in profiles if item['payload'].get('profile_kind') is None]
    if len(base) != 1:
        return 'connection_unavailable'
    epoch=base[0]['payload'].get('data_reset_revision',0)
    saved=db.execute('SELECT revision FROM next_meal_owner_resets WHERE user_id=?',(uid,)).fetchone()
    if type(epoch) is not int or epoch<0 or (saved and saved['revision']!=epoch):
        return 'reset_sync_pending'
    # This is an explicitly opened own Food tool. Its native current trial is
    # sufficient too; it does not grant any other cross-product capability.
    access = entitlements(store, uid, now, profiles)['domains']['food']
    if not access and not active_until(base[0]['payload'].get('native_trial_until'), now):
        return 'food_access_required'
    return None


def _view(db, store, uid, now, preferences, expected_reset=None):
    day = now.astimezone(MOSCOW).date().isoformat()
    row = db.execute('SELECT * FROM next_meal_choices WHERE user_id=?', (uid,)).fetchone()
    try:
        reason = _food_ready(db, store, uid, preferences, now)
    except (ValueError, TypeError, KeyError,AttributeError):
        reason = 'connection_unavailable'
    if preferences.get('_unknown'):reason='preferences_unavailable'
    if not enabled(store):reason='feature_not_ready'
    reset=db.execute('SELECT revision FROM next_meal_owner_resets WHERE user_id=?',(uid,)).fetchone()
    reset_revision=reset['revision'] if reset else 0
    if expected_reset is not None and expected_reset!=reset_revision:reason='reset_sync_pending'
    candidates = []
    if reason is None:
        if not preferences['revision'] or preferences.get('updated_at') is None:
            reason = 'preferences_required'
        else:
            try:
                raw=db.execute('SELECT body FROM connection_preferences WHERE user_id=?',(uid,)).fetchone()
                saved=json.loads(raw['body']) if raw else None
                if (not isinstance(saved,dict) or not {'diet','excluded_food_groups','sources'}<=saved.keys()
                        or not isinstance(saved['sources'],dict)
                        or set(saved['sources'])!={'gym','food','supply'}
                        or any(type(v) is not bool for v in saved['sources'].values())):
                    raise ValueError('unknown_preferences')
                candidates = ideas(preferences)
            except (ValueError,TypeError,KeyError):
                reason = 'preferences_unavailable'
    choice, state = None, 'none'
    if row and row['idea_id']:
        if row['day'] != day:
            state = 'different_day'
        elif row['preferences_revision'] != preferences['revision']:
            state = 'settings_changed'
        elif row['catalog_version'] != VERSION:
            state = 'catalog_changed'
        elif reason is None:
            choice = next((idea for idea in candidates if idea['id'] == row['idea_id']), None)
            state = 'selected' if choice else 'catalog_changed'
    return {'owner_subject':uid, 'day':day, 'timezone':'Europe/Moscow',
            'available':reason is None, 'unavailable_reason':reason,
            'preferences_revision':preferences['revision'], 'catalog_version':VERSION,
            'choice_revision':row['revision'] if row else 0,
            'data_reset_revision':reset_revision,
            'choice':choice, 'choice_state':state,
            'has_current_intent':bool(row and row['idea_id'] and row['day']==day),
            'ideas':candidates, 'note':NOTE,
            'recorded_as_eaten':False}


def view(store, user_id, now=None, expected_reset=None):
    uid = subject(user_id)
    now = now or datetime.now(timezone.utc)
    with store.connection() as db:
        db.execute('BEGIN')
        preferences = _preferences(db,uid,now.timestamp())
        return _view(db, store, uid, now, preferences,expected_reset)


def change(store, user_id, operation, now=None, expected_reset=None):
    uid = subject(user_id)
    now = now or datetime.now(timezone.utc)
    if not isinstance(operation, dict):
        raise ChoiceConflict('invalid_operation')
    required = {'operation_id','action','day','choice_revision','preferences_revision','catalog_version','data_reset_revision'}
    if (set(operation) not in (required, required|{'idea_id'})
            or operation.get('action') not in ('choose','cancel')
            or not isinstance(operation.get('operation_id'),str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',operation['operation_id'])
            or any(type(operation.get(key)) is not int or not 0<=operation[key]<2**63
                   for key in ('choice_revision','preferences_revision','catalog_version','data_reset_revision'))
            or not isinstance(operation.get('day'),str)):
        raise ChoiceConflict('invalid_operation')
    choosing = operation['action'] == 'choose'
    if (choosing and (set(operation)!=required|{'idea_id'} or not isinstance(operation['idea_id'],str))
            or not choosing and set(operation)!=required):
        raise ChoiceConflict('invalid_operation')
    stamp, request_hash = now.timestamp(), digest(operation)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        preferences = _preferences(db, uid, stamp)
        state = _view(db, store, uid, now, preferences,expected_reset)
        if not state['available']:
            raise ChoiceConflict(state['unavailable_reason'])
        receipt = db.execute('SELECT * FROM next_meal_receipts WHERE user_id=? AND operation_id=?',
                             (uid,operation['operation_id'])).fetchone()
        if receipt and receipt['expires_at'] > stamp:
            if receipt['request_hash'] != request_hash:
                raise ChoiceConflict('operation_conflict')
            return {**state,'applied':True,'duplicate':True,'operation_id':operation['operation_id'],
                    'receipt_revision':receipt['applied_revision'],
                    'current_matches':state['day']==receipt['day'] and state['choice_revision']==receipt['applied_revision']}
        if (operation['data_reset_revision']!=state['data_reset_revision']
                or operation['day'] != state['day'] or operation['choice_revision'] != state['choice_revision']
                or operation['preferences_revision'] != state['preferences_revision']
                or operation['catalog_version'] != VERSION):
            raise ChoiceConflict('choice_changed')
        if choosing and not any(idea['id']==operation['idea_id'] for idea in state['ideas']):
            raise ChoiceConflict('idea_unavailable')
        db.execute('DELETE FROM next_meal_receipts WHERE rowid IN (SELECT rowid FROM next_meal_receipts WHERE expires_at<=? ORDER BY expires_at LIMIT 128)', (stamp,))
        if db.execute('SELECT count(*) FROM next_meal_receipts WHERE user_id=? AND expires_at>?', (uid,stamp)).fetchone()[0]>=MAX_OWNER_RECEIPTS:
            raise ChoiceConflict('too_many_choices')
        revision = state['choice_revision']+1
        db.execute('INSERT INTO next_meal_choices VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET day=excluded.day,revision=excluded.revision,idea_id=excluded.idea_id,preferences_revision=excluded.preferences_revision,catalog_version=excluded.catalog_version,updated_at=excluded.updated_at',
                   (uid,state['day'],revision,operation.get('idea_id') if choosing else None,preferences['revision'],VERSION,stamp))
        db.execute('INSERT INTO next_meal_receipts VALUES(?,?,?,?,?,?)',
                   (uid,operation['operation_id'],request_hash,revision,state['day'],stamp+RECEIPT_TTL))
        return {**_view(db,store,uid,now,preferences,expected_reset),'applied':True,'duplicate':False,
                'operation_id':operation['operation_id'],'receipt_revision':revision,'current_matches':True}


def _preferences(db,uid,stamp):
    try:
        raw=db.execute('SELECT body FROM connection_preferences WHERE user_id=?',(uid,)).fetchone()
        if raw:
            from .connections import FOOD_GROUPS
            body=json.loads(raw['body'])
            if (not isinstance(body,dict) or body.get('diet') not in ('any','vegetarian','vegan')
                    or not isinstance(body.get('excluded_food_groups'),list)
                    or any(group not in FOOD_GROUPS for group in body['excluded_food_groups'])
                    or not isinstance(body.get('sources'),dict)
                    or set(body['sources'])!={'gym','food','supply'}
                    or any(type(v) is not bool for v in body['sources'].values())):
                raise ValueError('unknown_preferences')
        return preferences_from_connection(db,uid,stamp)
    except (ValueError,TypeError,KeyError):
        # Unknown saved restrictions must never become permissive defaults.
        version=db.execute('SELECT revision FROM connection_preference_versions WHERE user_id=?',(uid,)).fetchone()
        return {'_unknown':True,'sources':{'food':True},'revision':version['revision'] if version else 0,
                'updated_at':stamp,'diet':None,'excluded_food_groups':None}


def reconcile_resets(db,snapshot):
    """Owner metadata only; no source write and no global preference erasure."""
    for item in snapshot['entities']:
        payload=item['payload']
        if not item['entity_id'].startswith('profile:') or payload.get('profile_kind') is not None:continue
        uid=subject(item['user_id']);revision=payload.get('data_reset_revision',0)
        if type(revision) is not int or not 0<=revision<2**63:raise ValueError('invalid_food_reset_revision')
        old=db.execute('SELECT revision FROM next_meal_owner_resets WHERE user_id=?',(uid,)).fetchone()
        if old and revision<old['revision']:continue  # stale export cannot undo a reset
        if (old and revision>old['revision']) or (not old and revision>0):
            db.execute('DELETE FROM next_meal_choices WHERE user_id=?',(uid,))
            db.execute('DELETE FROM next_meal_receipts WHERE user_id=?',(uid,))
        db.execute('INSERT INTO next_meal_owner_resets VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET revision=max(revision,excluded.revision)',(uid,revision))
