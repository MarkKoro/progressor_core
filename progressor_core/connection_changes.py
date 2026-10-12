"""Confirmed source changes only. No clinical cause or missing-data inference."""
import json,time
from datetime import datetime,timedelta,timezone
from .contracts import canonical,digest,subject

def record(db,event,previous):
    if event['payload'].get('deleted') or previous and previous['deleted']:return
    old=json.loads(previous['payload']) if previous else {};p=event['payload'];kind=None;body={}
    if not previous:
        # A bootstrap is not a user change. New facts only after a successful
        # source poll and an actual recent source timestamp; backfills excluded.
        known=db.execute('SELECT last_success FROM source_state WHERE source=?',(event['source'],)).fetchone()
        stamp=datetime.fromisoformat(event['occurred_at'].replace('Z','+00:00'))
        if not known or not known[0] or not datetime.now(timezone.utc)-timedelta(hours=2)<=stamp<=datetime.now(timezone.utc) or p.get('backfilled'):return
        if event['event_type']=='supplement.started':kind='supplement';body={'name':p.get('name','Добавка')[:160],'before_active':None,'after_active':p.get('active')}
        elif event['event_type']=='workout.completed' and p.get('session_complete',True):kind='workout';body={'before_sets':None,'after_sets':p.get('strength_sets'),'date':p.get('source_local_date')}
        else:return
    elif p.get('profile_kind')=='reported_health' and event['source']=='supply':
        before=(old.get('reported_profile') or {}).get('weight_kg');after=(p.get('reported_profile') or {}).get('weight_kg')
        if type(after) in (int,float) and 30<=after<=350 and before!=after:kind='weight';body={'before':before,'after':after,'unit':'kg'}
    elif event['event_type']=='nutrition_target.changed' and old.get('targets')!=p.get('targets'):
        kind='goal';body={'before':old.get('targets'),'after':p['targets']}
    elif event['event_type'].startswith('supplement.') and old.get('active')!=p.get('active'):
        kind='supplement';body={'name':p.get('name','Добавка')[:160],'before_active':old.get('active'),'after_active':p.get('active')}
    elif event['event_type'].startswith('workout.') and old.get('strength_sets')!=p.get('strength_sets'):
        kind='workout';body={'before_sets':old.get('strength_sets'),'after_sets':p.get('strength_sets'),'date':p.get('source_local_date')}
    elif event['event_type']=='daily_nutrition.updated' and old.get('totals')!=p.get('totals'):
        kind='food';body={'date':p.get('source_local_date'),'before':old.get('totals'),'after':p.get('totals')}
    elif p.get('profile_kind') is None and old.get('timezone')!=p.get('timezone') and p.get('timezone'):
        kind='timezone';body={'before':old.get('timezone'),'after':p['timezone']}
    if kind:
        stamp=time.time();body.update(event_id=event['event_id'],occurred_at=event['occurred_at'])
        db.execute('INSERT OR IGNORE INTO connection_changes VALUES(?,?,?,?,?,?)',(digest([event['event_id'],kind]),event['user_id'],event['source'],kind,stamp,canonical(body)))
        db.execute('DELETE FROM connection_changes WHERE observed_at<?',(stamp-30*86400,))

def recent(store,user_id,now=None):
    from .connections import permitted_entities,preferences
    now=now or datetime.now(timezone.utc);uid=subject(user_id);policy=preferences(store,uid,now.timestamp())
    entities,_,_=permitted_entities(store,uid,now);allowed={e['source'] for e in entities}
    if policy['rest_active']:allowed=set()
    with store.connection() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM connection_changes WHERE user_id=? AND observed_at>? AND observed_at<=? ORDER BY observed_at DESC LIMIT 100',(uid,(now-timedelta(days=7)).timestamp(),now.timestamp())) if r['source'] in allowed]
    result=[]
    names={'food':'Food','gym':'Gym Diary','supply':'Supply'}
    for row in rows[:12]:
        p=json.loads(row.pop('body'));row['details']=p
        if row['kind']=='weight':text=f"Вес в Supply изменён: {p['before'] if p['before'] is not None else 'не указан'} → {p['after']:g} кг."
        elif row['kind']=='goal':text='Личная цель КБЖУ изменена в Food.'
        elif row['kind']=='supplement':text=f"Supply: {p['name']} — "+('включён приём.' if p['after_active'] else 'приём выключен.')
        elif row['kind']=='timezone':text=f"Часовой пояс {names[row['source']]}: {p['before']} → {p['after']}."
        elif row['kind']=='food':text='Food: изменились записанные КБЖУ за '+str(p.get('date') or 'день')+'. Это может быть новая еда или исправление записи.'
        else:text=(f"Записанная нагрузка Gym Diary изменена: подходов {p['before_sets']} → {p['after_sets']}." if p['before_sets'] is not None else f"Gym Diary: сохранена тренировка, рабочих подходов {p['after_sets']}.")
        result.append({**row,'text':text})
    return {'items':result,'message':'Изменения в ваших записях за неделю. Совпадение по времени не устанавливает причину самочувствия.'}

def hints(store,user_id,target,now=None):
    from .connections import preferences,permitted_entities
    now=now or datetime.now(timezone.utc);policy=preferences(store,user_id,now.timestamp())
    if not policy['hints'] or policy['rest_active']:return []
    entities,_,_=permitted_entities(store,user_id,now)
    if target not in {e['source'] for e in entities}:return []
    changes=recent(store,user_id,now)['items'];result=[]
    for item in changes:
        if now.timestamp()-item['observed_at']>2*86400:continue
        if item['kind']=='weight' and policy['weight_notifications'] and target=='food' and policy['sources']['food']:
            if item['observed_at'] < max(policy.get('weight_enabled_at') or now.timestamp(),policy.get('last_pause_started_at',0)):continue
            # Actual goal edit after this change completes the review. Reading a
            # hint or opening a screen does not complete it.
            if any(c['kind']=='goal' and c['observed_at']>=item['observed_at'] for c in changes):continue
            title='Новый вес — проверить цель?';message=item['text']+' Проверьте, подходит ли текущая цель питания. Самостоятельно мы её не меняли.'
        elif item['kind']=='goal' and policy['goal_links'] and target in ('gym','supply'):
            # A view is not completion. A later saved workout/intake is an
            # actual native action; imported historical records do not count.
            if any(e['source']==target and e['entity_id'].startswith('workout:' if target=='gym' else 'intake:') and e['occurred_at']>item['details']['occurred_at'] and not e['payload'].get('backfilled') and (e['payload'].get('session_complete',True) if target=='gym' else e['payload'].get('status')=='taken') for e in entities):continue
            title='Новая цель питания';message='В Food изменена цель. Можно сверить ваш план в '+('Gym Diary: сохраняйте силовые, а посильную аэробную активность выбирайте по самочувствию. Упражнения автоматически не меняются.' if target=='gym' else 'Supply. Добавки для похудения не назначаем по смене цели; проверьте уже выбранные вами приёмы.')
        else:continue
        key='change_'+item['kind']+'.v1';delivery=key+':'+item['id']
        result.append({'key':key,'targets':[target],'priority':12,'rule_version':1,'delivery':'inline_only',
            'delivery_key':delivery,'title':title,'message':message,'action':{'kind':'open_food' if target=='food' else 'gym_plan' if target=='gym' else 'supply_plan','label':'Проверить цель Food' if target=='food' else 'Мой план тренировок' if target=='gym' else 'Мои приёмы'},
            'basis':[{'source':item['source'],'event_id':item['details']['event_id']}],
            'details':item['text']+' Личные цели и записи меняются только обычным подтверждённым действием в своём продукте.'})
        break
    return result

def revoke_coach_permissions(db):
    # Run after a successful fresh Gym reconcile, including tombstones. A link
    # accepted again later cannot resurrect the old consent automatically.
    allowed={(r['user_id'],p['coach_id'],p['link_id']) for r in db.execute("SELECT user_id,payload FROM entities WHERE source='gym' AND deleted=0")
        for p in (json.loads(r['payload']),) if p.get('profile_kind')=='coach_link' and p.get('status')=='accepted' and p.get('coach_enabled') is True}
    for row in db.execute('SELECT trainee_id,coach_id,link_id FROM coach_nutrition_permissions WHERE macros=1'):
        if tuple(row) not in allowed:db.execute('UPDATE coach_nutrition_permissions SET macros=0,top_dishes=0,expires_at=0 WHERE trainee_id=? AND coach_id=?',(row['trainee_id'],row['coach_id']))
