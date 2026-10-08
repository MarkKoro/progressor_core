"""Membership is identity, never a paid entitlement. Source data stays source-owned."""
from datetime import datetime,timezone
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
    entities=entities if entities is not None else store.data(user_id)[0]
    native={source:None for source in SOURCES}
    for entity in entities:
        payload=entity['payload']
        if entity['entity_id'].startswith('profile:') and payload.get('profile_kind') not in ('reported_health','reported_nutrition'):
            native[entity['source']]=payload.get('paid_until')
    bundle=None
    with store.connection() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='bundle_entitlements'").fetchone():
            row=db.execute('SELECT expires_at FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()
            bundle=row['expires_at'] if row else None
    paid={source:active_until(native[source],now) or active_until(bundle,now) for source in SOURCES}
    return {'domains':paid,'accessible_domains':[s for s in SOURCES if paid[s]],'bundle_active':active_until(bundle,now),'bundle_until':bundle if active_until(bundle,now) else None,'native_until':{s:native[s] if active_until(native[s],now) else None for s in SOURCES}}
