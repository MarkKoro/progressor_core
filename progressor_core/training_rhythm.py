"""Two-week preliminary rhythm, explicit confirmation, bounded expiry."""
import json,time
from datetime import datetime,timedelta,timezone
from .adapters import zone
from .connections import permitted_entities,preferences
from .contracts import canonical,digest,subject
from shared.day_goal import redistribute,goal_key

def proposal(store,user_id,now=None):
    now=now or datetime.now(timezone.utc);entities,_,_=permitted_entities(store,user_id,now)
    records=sorted([e for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:')
        and e['payload'].get('session_complete',True) and e['payload'].get('program_id') is not None
        and not e['payload'].get('backfilled')],key=lambda e:e['payload']['completed_at'])
    result={'status':'insufficient_history','minimum_days':14,'message':'Сначала наблюдаем две недели занятий по одной системе. Незаписанный день не считаем днём отдыха.'}
    if not records:return result
    program=records[-1]['payload']['program_id'];same=[e for e in records if e['payload']['program_id']==program]
    changed=max((e['payload']['completed_at'] for e in records if e['payload']['program_id']!=program),default='')
    same=[e for e in same if e['payload']['completed_at']>changed]
    parsed=lambda e:datetime.fromisoformat(e['payload']['completed_at'].replace('Z','+00:00'))
    if not same or now-parsed(same[0])<timedelta(days=14):return result
    recent=[e for e in same if now-timedelta(days=14)<=parsed(e)<=now]
    weeks=[set(),set()];seen=set()
    for e in recent:
        p=e['payload'];stamp=parsed(e);local=stamp.astimezone(zone(p.get('timezone','UTC')))
        unique=(p.get('session_id') or e['entity_id'],local.date().isoformat())
        if unique in seen:continue
        seen.add(unique);index=0 if stamp>now-timedelta(days=7) else 1;weeks[index].add(local.weekday())
    if weeks[0]!=weeks[1] or not 2<=len(weeks[0])<=5:return {**result,'status':'variable_schedule','message':'Дни занятий пока меняются. Можно пользоваться обычной целью и подтвердить ритм позже.'}
    weekdays=sorted(weeks[0]);identity={'program_id':program,'weekdays':weekdays}
    goal=next((e for e in entities if e['source']=='food' and e['entity_id'].startswith('target:')),None)
    previews=[]
    if goal:
        for extra in (0,100,150):
            try:previews.append(redistribute(goal['payload']['targets'],weekdays,extra))
            except ValueError:continue
    return {'status':'proposal','program_id':program,'weekdays':weekdays,'fingerprint':digest(identity),'goal_event_id':goal['event_id'] if goal else None,
        'provenance':[{'source':'gym','event_id':e['event_id']} for e in recent],
        'base_goal_key':goal_key(goal['payload']['targets']) if goal else None,'previews':previews,
        'message':'В обеих неделях повторяются одни и те же дни тренировок. Подтвердите, если этот ритм вам подходит. Недельная сумма калорий сохраняется; белок и жиры остаются прежними, разница приходится на углеводы.'}

def confirm(store,user_id,fingerprint,base_key,extra,now=None):
    now=now or datetime.now(timezone.utc);uid=subject(user_id)
    current=proposal(store,uid,now)
    if current['status']!='proposal' or current['fingerprint']!=fingerprint or current['base_goal_key']!=base_key:raise ValueError('rhythm_changed')
    selected=next((p for p in current['previews'] if p['training_extra_kcal']==extra),None)
    if not selected:raise ValueError('manual_goal_required')
    body={**current,'plan':selected};body.pop('previews',None)
    with store.connection() as db:
        db.execute('INSERT INTO confirmed_training_rhythm VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET body=excluded.body,confirmed_at=excluded.confirmed_at,expires_at=excluded.expires_at',
            (uid,canonical(body),now.timestamp(),(now+timedelta(days=28)).timestamp()))
    return active(store,uid,now)

def active(store,user_id,now=None):
    now=now or datetime.now(timezone.utc);policy=preferences(store,user_id,now.timestamp())
    if policy['rest_active'] or not all(policy['sources'][s] for s in ('food','gym')):return None
    entities,_,_=permitted_entities(store,user_id,now)
    if not all(any(e['source']==s for e in entities) for s in ('food','gym')):return None
    with store.connection() as db:row=db.execute('SELECT * FROM confirmed_training_rhythm WHERE user_id=? AND expires_at>?',(subject(user_id),now.timestamp())).fetchone()
    if not row:return None
    body=json.loads(row['body']);goal=next((e for e in entities if e['source']=='food' and e['entity_id'].startswith('target:')),None)
    if not goal or goal_key(goal['payload']['targets'])!=body['base_goal_key'] or goal['event_id']!=body.get('goal_event_id'):return None
    recent=[e for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:') and e['payload'].get('session_complete',True) and not e['payload'].get('backfilled')]
    if recent:
        last=max(recent,key=lambda e:e['payload']['completed_at'])
        if last['payload'].get('program_id')!=body['program_id']:return None
        for e in recent:
            stamp=datetime.fromisoformat(e['payload']['completed_at'].replace('Z','+00:00'))
            if stamp.timestamp()>row['confirmed_at'] and (e['payload'].get('program_id')!=body['program_id'] or stamp.astimezone(zone(e['payload'].get('timezone','UTC'))).weekday() not in body['weekdays']):return None
    return {**body['plan'],'weekdays':body['weekdays'],'expires_at':row['expires_at'],'confirmed_at':row['confirmed_at']}

def disable(store,user_id):
    with store.connection() as db:db.execute('DELETE FROM confirmed_training_rhythm WHERE user_id=?',(subject(user_id),))
    return {'active':False}
