"""Fresh own Food save events; a journal date is not a consumption instant."""
from datetime import date, datetime, timedelta, timezone
from .adapters import zone
from .connections import permitted_entities, preferences
from .contracts import subject


def _recorded_for_anchor(entity):
    """Keep legacy Food save-time semantics, excluding clearly historical days.

    Old adapter payloads have a known legacy_server_timezone basis. New payloads
    explicitly distinguish an absent save timestamp from the day-midnight
    fallback used by the event envelope. Neither case invents consumption time.
    """
    payload = entity['payload']
    if 'recorded_at' in payload:
        if payload.get('recorded_at_basis') != 'legacy_server_timezone':
            return None
        recorded = payload.get('recorded_at')
    else:
        recorded = entity['occurred_at'] if payload.get('timestamp_basis') == 'legacy_server_timezone' else None
    try:
        if not isinstance(recorded, str) or not isinstance(payload.get('timezone'), str) or not payload['timezone']:
            return None
        instant = datetime.fromisoformat(recorded.replace('Z', '+00:00'))
        if instant.tzinfo is None:
            return None
        journal_day = date.fromisoformat(payload['source_local_date'])
        if journal_day != instant.astimezone(zone(payload['timezone'])).date():
            return None
        return instant.astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def events(store,people,now=None):
    if not isinstance(people,list) or len(people)>100:raise ValueError('invalid_people')
    now=now or datetime.now(timezone.utc);result=[]
    for person in people:
        uid=subject(person);policy=preferences(store,uid)
        if policy['rest_active'] or not policy['notifications']:continue
        entities,_,access=permitted_entities(store,uid,now,respect_rest=True)
        if not {'food','supply'}.issubset({e['source'] for e in entities}):continue
        meals=[]
        for e in entities:
            if e['source']!='food' or not e['entity_id'].startswith('meal:'):continue
            at=_recorded_for_anchor(e)
            if at is not None and now-timedelta(minutes=10)<=at<=now:
                meals.append({'entity_id':e['entity_id'],'occurred_at':at.isoformat().replace('+00:00','Z')})
        meals.sort(key=lambda m:m['occurred_at'],reverse=True)
        if meals:result.append({'user_id':uid,'meals':meals[:3]})
    return {'items':result}
