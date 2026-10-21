"""Owner-published read policy. No native policy constants or domain writes."""
import re
import sqlite3
import time
from datetime import datetime,timezone
from pathlib import Path

OWNER_POLICY_PROTOCOL=1
OWNER_POLICY_GATE=Path('/var/lib/progressor/owner-consent-v1-ready')
SCHEMA='''CREATE TABLE IF NOT EXISTS owner_policy_visibility(
    user_id TEXT PRIMARY KEY,semantic_key TEXT NOT NULL,opened_at REAL,changed_at REAL NOT NULL);'''


def enforced(store):
    path=getattr(store,'owner_policy_gate',OWNER_POLICY_GATE)
    if path is None:return False
    try:Path(path).lstat()
    except FileNotFoundError:return False
    except OSError:return True
    return True


def parse_supply_metadata(db,users):
    unknown={uid:{'protocol':0,'status':'unknown','reason':'metadata_unavailable'} for uid in users}
    try:
        header=db.execute('SELECT * FROM progressor_owner_policy').fetchall()
        if len(header)!=1:raise ValueError('owner_policy_header')
        header=dict(header[0]);stamp=datetime.fromisoformat(header['generated_at_utc'].replace('Z','+00:00'))
        if stamp.tzinfo is None or not -5<=time.time()-stamp.timestamp()<120:raise ValueError('owner_policy_time')
        if type(header['schema_version']) is not int or header['schema_version']!=1 or header['source']!='supply':raise ValueError('owner_policy_schema')
        if not re.fullmatch('[0-9a-f]{32}',header['generation']) or not re.fullmatch('[0-9a-f]{64}',header['policy_fingerprint']):raise ValueError('owner_policy_fingerprint')
        if any(not isinstance(header[k],str) or not header[k] or len(header[k])>128 for k in ('required_offer_version','required_privacy_version')):raise ValueError('owner_policy_version')
        rows=db.execute('SELECT * FROM progressor_owner_consent').fetchall()
        found={r['native_user_id']:dict(r) for r in rows}
        if len(found)!=len(rows):raise ValueError('owner_policy_duplicate')
        result=dict(unknown)
        for uid,user in users.items():
            row=found.get(uid)
            if not row:continue
            value=row['legal_current'];reason=row['reason']
            if type(value) is not int or value not in (0,1) or row['user_subject']!=str(user['tg_user_id']):continue
            if row['policy_fingerprint']!=header['policy_fingerprint']:continue
            if reason not in ('current','not_accepted','offer_changed','privacy_changed','both_changed') or (reason=='current')!=bool(value):continue
            result[uid]={'protocol':1,'status':'current' if value else 'closed','reason':reason,'policy_fingerprint':header['policy_fingerprint']}
        return result
    except (sqlite3.Error,KeyError,IndexError,TypeError,ValueError,OverflowError):return unknown


def supply_state(store,entities):
    if not enforced(store):return 'shadow'
    profiles=[e['payload'] for e in entities if e['source']=='supply'
        and e['entity_id'].startswith('profile:') and e['payload'].get('profile_kind') is None]
    if len(profiles)!=1:return 'unknown'
    base=profiles[0]
    proof=base.get('owner_consent') or {}
    if (type(proof.get('protocol')) is not int or proof['protocol']!=1
            or proof.get('status') not in ('current','closed')
            or not re.fullmatch('[0-9a-f]{64}',str(proof.get('policy_fingerprint','')))):return 'unknown'
    return proof['status']


def eligible_sources(store,user_id,snapshot,now=None,*,target=None,policy=None,access=None,enabled_sources=None,fresh=True,respect_rest=False):
    from .access import entitlements
    from .connections import preferences
    from .contracts import SOURCES
    now=now or datetime.now(timezone.utc);entities,members,state=snapshot
    policy=policy if policy is not None else preferences(store,user_id)
    access=access if access is not None else entitlements(store,user_id,now,entities)
    enabled=set(enabled_sources if enabled_sources is not None else getattr(store,'enabled_sources',SOURCES))
    joined={m['source'] for m in members if m['active']}
    visible=set(access['accessible_domains']) & enabled & joined
    visible={s for s in visible if policy['sources'][s]}
    # Explicit own-profile choices remain available during rest. Proactive
    # context, summaries and reminders opt into the rest overlay separately.
    if respect_rest and policy['rest_active']:visible=set()
    if supply_state(store,entities) not in ('current','shadow'):visible.discard('supply')
    def current(source):
        value=state.get(source,{});stamp=value.get('last_success')
        return value.get('status')=='ok' and type(stamp) in (int,float) and -5<=time.time()-stamp<120
    ready={s for s in visible if current(s)}
    if target is not None and target not in visible:return set()
    return ready if fresh else visible


def observe_snapshot(db,snapshot):
    """Track semantic owner-policy boundaries, not every snapshot generation."""
    opened=set();stamp=time.time()
    subjects=set()
    for entity in snapshot['entities']:
        p=entity['payload']
        if not entity['entity_id'].startswith('profile:') or p.get('profile_kind') is not None:continue
        proof=p.get('owner_consent') or {};current=proof.get('protocol')==1 and proof.get('status')=='current'
        key=str(proof.get('status','unknown'))+':'+str(proof.get('policy_fingerprint',''))
        uid=entity['user_id'];subjects.add(uid);old=db.execute('SELECT * FROM owner_policy_visibility WHERE user_id=?',(uid,)).fetchone()
        if old and old['semantic_key']==key:continue
        opened_at=stamp if current else None
        db.execute('INSERT INTO owner_policy_visibility VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET semantic_key=excluded.semantic_key,opened_at=excluded.opened_at,changed_at=excluded.changed_at',(uid,key,opened_at,stamp))
        if current:opened.add(uid)
    # A removed native account closes its visibility epoch too. Recreating the
    # same Telegram subject later must not revive its old change suggestions.
    for row in db.execute('SELECT user_id FROM owner_policy_visibility').fetchall():
        if row['user_id'] not in subjects:
            db.execute("UPDATE owner_policy_visibility SET semantic_key='missing',opened_at=NULL,changed_at=? WHERE user_id=? AND semantic_key!='missing'",(stamp,row['user_id']))
    return opened


def changes_since(store,user_id):
    if not enforced(store):return None
    with store.connection() as db:
        row=db.execute('SELECT opened_at FROM owner_policy_visibility WHERE user_id=?',(user_id,)).fetchone()
    return row['opened_at'] if row and row['opened_at'] is not None else float('inf')
