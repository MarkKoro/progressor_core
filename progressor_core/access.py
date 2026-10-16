"""Membership is identity, never a paid entitlement. Source data stays source-owned."""
from datetime import datetime,timezone
import json
from .contracts import SOURCES


def active_until(value,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(value,str) or not value: return False
    try:
        timestamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if timestamp.tzinfo is None: timestamp=timestamp.replace(tzinfo=timezone.utc)
        return timestamp>now
    except ValueError: return False


def entitlements(store,user_id,now=None,entities=None):
    now=now or datetime.now(timezone.utc)
    if entities is None:
        # Launch/subscription checks need membership profiles, never every
        # historical workout, meal or supplement mark of this account.
        with store.connection() as db:
            entities=[{**dict(row),'payload':json.loads(row['payload'])} for row in db.execute("SELECT source,entity_id,payload FROM entities WHERE user_id=? AND deleted=0 AND entity_id GLOB 'profile:*'",(user_id,))]
    native={source:None for source in SOURCES}
    for entity in entities:
        payload=entity['payload']
        if entity['entity_id'].startswith('profile:') and payload.get('profile_kind') is None:
            native[entity['source']]=payload.get('paid_until')
    bundle=None
    bundle_by_source={s:None for s in SOURCES}
    with store.connection() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='bundle_entitlements'").fetchone():
            row=db.execute('SELECT expires_at FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()
            bundle=row['expires_at'] if row else None
        has_intervals=db.execute("SELECT 1 FROM sqlite_master WHERE name='bundle_component_intervals'").fetchone()
        if has_intervals:
            for row in db.execute('SELECT source,starts_at,expires_at FROM bundle_component_intervals WHERE user_id=?',(user_id,)):
                if not active_until(row['starts_at'],now) and active_until(row['expires_at'],now):
                    current=bundle_by_source[row['source']]
                    if not current or row['expires_at']>current:bundle_by_source[row['source']]=row['expires_at']
        else:
            bundle_by_source={s:bundle for s in SOURCES}
    paid={source:active_until(native[source],now) or active_until(bundle_by_source[source],now) for source in SOURCES}
    return {'domains':paid,'accessible_domains':[s for s in SOURCES if paid[s]],'bundle_active':active_until(bundle,now),'bundle_until':bundle if active_until(bundle,now) else None,'bundle_domains_until':bundle_by_source,'native_until':{s:native[s] if active_until(native[s],now) else None for s in SOURCES}}
