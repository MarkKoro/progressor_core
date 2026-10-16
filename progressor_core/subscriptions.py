"""Account-owned access display; independent of checkout and cross-health consent.

Only source membership/expiry metadata is returned, never meals, profiles or labs.
Stale native state is unknown, never silently presented as an absent purchase.
"""
from datetime import datetime, timezone
from .access import active_until, entitlements
from .contracts import SOURCES, subject

NAMES = {'gym': 'Gym Diary', 'food': 'Food', 'supply': 'Supply'}


def subscription_view(store, user_id, enabled_sources=SOURCES, now=None):
    user_id = subject(user_id)
    now = now or datetime.now(timezone.utc)
    entities, memberships, states = store.membership_snapshot(user_id)
    access = entitlements(store, user_id, now, entities)
    profiles = {e['source']: e['payload'] for e in entities
                if e['entity_id'].startswith('profile:')
                and e['payload'].get('profile_kind') is None}
    products = []
    for source in SOURCES:
        observed = states.get(source, {})
        fresh = (source in enabled_sources and observed.get('status') == 'ok'
                 and -10 <= now.timestamp() - (observed.get('last_success') or 0) < 120)
        profile = profiles.get(source, {})
        native = profile.get('paid_until') if fresh else None
        trial = profile.get('native_trial_until') if fresh else None
        shared = access['bundle_domains_until'].get(source)
        active_ends = [v for v in (native, shared) if active_until(v, now)]
        def expiry_timestamp(value):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
        expires = max(active_ends, key=expiry_timestamp) if active_ends else None
        kind = 'bundle' if active_until(shared, now) else 'native' if active_until(native, now) else 'trial' if active_until(trial, now) else 'free' if fresh and source == 'gym' else 'none' if fresh else 'unknown'
        products.append({'source': source, 'name': NAMES[source],
                         'state': 'active' if expires else 'trial' if kind == 'trial' else 'free' if kind == 'free' else 'inactive' if fresh else 'unknown',
                         'kind': kind, 'expires_at': expires or (trial if kind == 'trial' else None),
                         'native_until': native, 'bundle_until': shared, 'native_fresh': fresh,
                         'premium_active': bool(expires), 'cross_context_active': bool(expires and fresh),
                         'native_access_label': 'Активна' if kind == 'native' else None})
    return {'schema_version': 1, 'generated_at': now.isoformat(), 'products': products,
            'bundle': {'active': access['bundle_active'], 'expires_at': access['bundle_until']},
            'premium_count': sum(p['premium_active'] for p in products),
            'missing_products': [p['source'] for p in products if p['state'] in ('inactive', 'free', 'trial')],
            'unknown_products': [p['source'] for p in products if p['state'] == 'unknown'],
            'note': 'Отдельный, подарочный и пробный доступ сохраняет свои условия. Доплата за общую подписку учитывает только подтверждённые оплаченные дни.'}
