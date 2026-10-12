"""Minimal, fresh owned meal timestamps for explicitly chosen Supply reminders."""
from datetime import datetime,timedelta,timezone
from .connections import permitted_entities,preferences
from .contracts import subject

def events(store,people,now=None):
    if not isinstance(people,list) or len(people)>100:raise ValueError('invalid_people')
    now=now or datetime.now(timezone.utc);result=[]
    for person in people:
        uid=subject(person);policy=preferences(store,uid)
        if policy['rest_active'] or not policy['notifications']:continue
        entities,_,access=permitted_entities(store,uid,now)
        if not {'food','supply'}.issubset({e['source'] for e in entities}):continue
        meals=[]
        for e in entities:
            if e['source']!='food' or not e['entity_id'].startswith('meal:'):continue
            at=datetime.fromisoformat(e['occurred_at'].replace('Z','+00:00'))
            if now-timedelta(minutes=10)<=at<=now:
                meals.append({'entity_id':e['entity_id'],'occurred_at':e['occurred_at']})
        meals.sort(key=lambda m:m['occurred_at'],reverse=True)
        if meals:result.append({'user_id':uid,'meals':meals[:3]})
    return {'items':result}
