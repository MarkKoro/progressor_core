"""Account-owned connection choices and explicit commands to source owners.

Core stores permissions/commands only. It never opens an owner's live database.
Rest is an operational overlay; it does not alter any subscription or saved choice.
"""
import copy
import json
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from .access import entitlements
from .contracts import SOURCES, canonical, digest, subject

SCHEMA = '''
CREATE TABLE IF NOT EXISTS connection_preferences(
 user_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS connection_commands(
 id TEXT NOT NULL,user_id TEXT NOT NULL,source TEXT NOT NULL,body TEXT NOT NULL,
 created_at REAL NOT NULL,expires_at REAL NOT NULL,status TEXT NOT NULL,result TEXT,
 PRIMARY KEY(id,source));
CREATE INDEX IF NOT EXISTS connection_commands_pending ON connection_commands(source,status,expires_at);
CREATE TABLE IF NOT EXISTS coach_nutrition_permissions(
 trainee_id TEXT NOT NULL,coach_id TEXT NOT NULL,link_id TEXT NOT NULL,
 macros INTEGER NOT NULL,top_dishes INTEGER NOT NULL,expires_at REAL NOT NULL,
 updated_at REAL NOT NULL,PRIMARY KEY(trainee_id,coach_id));
CREATE TABLE IF NOT EXISTS connection_changes(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,kind TEXT NOT NULL,
 observed_at REAL NOT NULL,body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS connection_changes_user ON connection_changes(user_id,observed_at);
CREATE TABLE IF NOT EXISTS connection_watermark(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS confirmed_training_rhythm(
 user_id TEXT PRIMARY KEY,body TEXT NOT NULL,confirmed_at REAL NOT NULL,expires_at REAL NOT NULL);
'''
DEFAULTS = {'sources':{s:True for s in SOURCES},'hints':True,'notifications':True,
 'frequency':'normal','diet':'any','excluded_food_groups':[],
 'weight_notifications':False,'goal_links':True,'paused':False,'pause_until':None,
 'day_prompt':True,'weekly_plan':False,'weekly_day':'monday','weekly_hour':10}
FOOD_GROUPS = ('fish','shellfish','meat','poultry','eggs','dairy','soy','nuts','gluten','sesame')

def preferences(store, user_id, now=None):
    stamp=time.time() if now is None else now
    with store.connection() as db:
        row=db.execute('SELECT * FROM connection_preferences WHERE user_id=?',(subject(user_id),)).fetchone()
    data=copy.deepcopy(DEFAULTS)
    if row: data.update(json.loads(row['body']))
    paused=bool(data['paused'] and (data['pause_until'] is None or data['pause_until']>stamp))
    return {**data,'revision':row['revision'] if row else 0,'updated_at':row['updated_at'] if row else None,
            'rest_active':paused,'subscription_time_continues':True}

def save_preferences(store,user_id,patch,expected_revision):
    uid=subject(user_id)
    if not isinstance(patch,dict) or set(patch)-set(DEFAULTS) or type(expected_revision) is not int:
        raise ValueError('invalid_preferences')
    for field in ('hints','notifications','weight_notifications','goal_links','paused','day_prompt','weekly_plan'):
        if field in patch and type(patch[field]) is not bool:raise ValueError('invalid_preference')
    if 'sources' in patch and (not isinstance(patch['sources'],dict) or set(patch['sources'])!=set(SOURCES)
            or any(type(v) is not bool for v in patch['sources'].values())):raise ValueError('invalid_sources')
    if 'frequency' in patch and patch['frequency'] not in ('normal','quiet'):raise ValueError('invalid_frequency')
    if 'weekly_day' in patch and patch['weekly_day'] not in ('monday','sunday'):raise ValueError('invalid_weekly_day')
    if 'weekly_hour' in patch and (type(patch['weekly_hour']) is not int or not 8<=patch['weekly_hour']<=20):raise ValueError('invalid_weekly_hour')
    if 'diet' in patch and patch['diet'] not in ('any','vegetarian','vegan'):raise ValueError('invalid_diet')
    if 'excluded_food_groups' in patch:
        values=patch['excluded_food_groups']
        if not isinstance(values,list) or len(values)>len(FOOD_GROUPS) or any(v not in FOOD_GROUPS for v in values):raise ValueError('invalid_exclusions')
        patch={**patch,'excluded_food_groups':sorted(set(values))}
    if patch.get('pause_until') is not None:
        value=patch['pause_until']
        if type(value) not in (int,float) or not math.isfinite(value) or not time.time()<value<=time.time()+366*86400:
            raise ValueError('invalid_pause_time')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM connection_preferences WHERE user_id=?',(uid,)).fetchone()
        if (old['revision'] if old else 0)!=expected_revision:raise ValueError('preferences_changed')
        body=copy.deepcopy(DEFAULTS)
        if old:body.update(json.loads(old['body']))
        if patch.get('weight_notifications') is True and not body['weight_notifications']:
            body['weight_enabled_at']=time.time()
        if patch.get('paused') is True and not body['paused']:body['last_pause_started_at']=time.time()
        body.update(patch)
        if not body['paused']:body['pause_until']=None
        db.execute('INSERT INTO connection_preferences VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,body=excluded.body,updated_at=excluded.updated_at',
                   (uid,expected_revision+1,canonical(body),time.time()))
    return preferences(store,uid)

def permitted_entities(store,user_id,now=None,*,snapshot=None,respect_rest=False):
    from .owner_policy import eligible_sources
    now=now or datetime.now(timezone.utc)
    current=snapshot if snapshot is not None else store.data(subject(user_id))
    entities,members,state=current
    access=entitlements(store,subject(user_id),now,entities)
    allowed=eligible_sources(store,user_id,current,now,access=access,respect_rest=respect_rest)
    return [e for e in entities if e['source'] in allowed],members,access

def weight_choices(store,user_id,*,snapshot=None):
    entities,members,access=permitted_entities(store,user_id,snapshot=snapshot)
    latest={};now=datetime.now(timezone.utc)
    for entity in entities:
        p=entity['payload'];value=None
        if entity['source']=='gym' and entity['entity_id'].startswith('weight:'):value=p.get('value')
        elif p.get('profile_kind') in ('reported_nutrition','reported_health'):value=(p.get('reported_profile') or {}).get('weight_kg')
        if type(value) not in (int,float) or not math.isfinite(value) or not 30<=value<=350:continue
        stamp=datetime.fromisoformat(entity['occurred_at'].replace('Z','+00:00'))
        if not now-timedelta(days=90)<=stamp<=now:continue
        old=latest.get(entity['source'])
        if old and (old['observed_at'],old['event_id'])>=(entity['occurred_at'],entity['event_id']):continue
        latest[entity['source']]={'source':entity['source'],'value':float(value),'unit':'kg',
            'event_id':entity['event_id'],'entity_id':entity['entity_id'],'observed_at':entity['occurred_at']}
    items=[latest[s] for s in SOURCES if s in latest]
    values=[i['value'] for i in items]
    # Targets must be currently eligible as well as paid. An unknown or closed
    # Supply owner decision cannot receive a new cross-product profile command.
    targets=[s for s in SOURCES if any(e['source']==s for e in entities)]
    return {'items':items,'fingerprint':digest(items),'targets':targets,
        'conflict':bool(len(values)>1 and max(values)-min(values)>.2),
        'explanation':'Выберите актуальный вес. Остальные профили обновятся после подтверждения; история измерений и цель питания сохраняются.'}

def reconcile_weight(store,user_id,event_id,fingerprint,operation_id):
    uid=subject(user_id)
    try:
        if str(uuid.UUID(operation_id))!=operation_id:raise ValueError('invalid_operation')
    except (ValueError,TypeError,AttributeError):raise ValueError('invalid_operation')
    choices=weight_choices(store,uid)
    if choices['fingerprint']!=fingerprint:raise ValueError('weight_values_changed')
    selected=next((i for i in choices['items'] if i['event_id']==event_id),None)
    if not selected:raise ValueError('weight_not_available')
    expected={i['source']:i for i in choices['items']}
    stamp=time.time()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT count(*) FROM connection_commands WHERE user_id=? AND created_at>?',(uid,stamp-86400)).fetchone()[0]>=60:
            raise ValueError('too_many_profile_changes')
        for source in choices['targets']:
            body={'kind':'confirmed_weight','weight_kg':selected['value'],'expected':expected.get(source),
                  'selected_source':selected['source'],'selection_fingerprint':fingerprint}
            prior=db.execute('SELECT user_id,body FROM connection_commands WHERE id=? AND source=?',(operation_id,source)).fetchone()
            if prior and (prior['user_id']!=uid or prior['body']!=canonical(body)):raise ValueError('operation_conflict')
            db.execute("INSERT OR IGNORE INTO connection_commands VALUES(?,?,?,?,?,?,'pending',NULL)",
                       (operation_id,uid,source,canonical(body),stamp,stamp+3600))
    return weight_operation(store,uid,operation_id)

def weight_operation(store,user_id,operation_id):
    with store.connection() as db:
        rows=[dict(r) for r in db.execute('SELECT source,status,result,expires_at FROM connection_commands WHERE id=? AND user_id=?',(operation_id,subject(user_id)))]
    for row in rows:
        if row['status']=='pending' and row['expires_at']<=time.time():row['status']='expired'
        row['result']=json.loads(row['result']) if row['result'] else None
    return {'operation_id':operation_id,'items':rows,'complete':bool(rows) and all(r['status']=='applied' for r in rows)}

def owner_sync(store,source,people,acks):
    if source not in SOURCES or not isinstance(people,list) or len(people)>100 or not isinstance(acks,list) or len(acks)>100:raise ValueError('invalid_sync')
    people=[subject(p) for p in people]
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for ack in acks:
            if ack.get('status') not in ('applied','conflict','consent_required','missing_owner','expired'):raise ValueError('invalid_ack')
            row=db.execute('SELECT user_id,status FROM connection_commands WHERE id=? AND source=?',(ack['id'],source)).fetchone()
            if not row or row['user_id']!=subject(ack['user_id']):raise ValueError('command_owner_mismatch')
            if row['status']=='pending':
                result={k:ack[k] for k in ('weight_kg','reason') if k in ack}
                db.execute('UPDATE connection_commands SET status=?,result=? WHERE id=? AND source=?',
                           (ack['status'],canonical(result),ack['id'],source))
        known={r[0] for r in db.execute('SELECT user_id FROM memberships WHERE source=? AND active=1',(source,))}
        commands=[dict(r) for r in db.execute("SELECT id,user_id,body,expires_at,created_at FROM connection_commands WHERE source=? AND status='pending' AND expires_at>? ORDER BY created_at LIMIT 100",(source,time.time())) if r['user_id'] in known]
    from .training_rhythm import active
    settings=[{'user_id':uid,'preferences':{**preferences(store,uid),'rhythm':active(store,uid),'synced_at':time.time()}} for uid in sorted(set(people)|{c['user_id'] for c in commands}) if uid in known]
    ready=[]
    for command in commands:
        entities,_,_=permitted_entities(store,command['user_id'])
        if not any(e['source']==source for e in entities):continue
        if source=='supply':
            from .owner_policy import changes_since
            opened_at=changes_since(store,command['user_id'])
            if opened_at is not None and command['created_at']<opened_at:continue
        ready.append({**command,'body':json.loads(command['body'])})
    return {'settings':settings,'commands':ready}

def coach_links(store,trainee_id,*,snapshot=None):
    entities,_,state=snapshot if snapshot is not None else store.data(subject(trainee_id))
    if state.get('gym',{}).get('status')!='ok' or time.time()-(state.get('gym',{}).get('last_success') or 0)>=120:return []
    return [e for e in entities if e['source']=='gym' and e['payload'].get('profile_kind')=='coach_link'
            and e['payload'].get('status')=='accepted' and e['payload'].get('coach_enabled') is True]

def coach_permissions(store,trainee_id,*,snapshot=None):
    links=coach_links(store,trainee_id,snapshot=snapshot)
    with store.connection() as db:
        rows={r['coach_id']:dict(r) for r in db.execute('SELECT * FROM coach_nutrition_permissions WHERE trainee_id=?',(subject(trainee_id),))}
    result=[]
    for link in links:
        p=link['payload'];row=rows.get(p['coach_id'],{})
        active=row.get('expires_at',0)>time.time() and row.get('link_id')==p['link_id']
        result.append({'coach_id':p['coach_id'],'link_id':p['link_id'],'label':p.get('label') or 'Ваш тренер',
                       'macros':bool(active and row.get('macros')),'top_dishes':bool(active and row.get('top_dishes')),
                       'expires_at':row.get('expires_at') if active else None})
    return {'items':result,'explanation':'Тренеру передаются только дневные КБЖУ. Пять частых блюд — отдельное разрешение. Каждый приём пищи, состав добавок и анализы не передаются.'}

def save_coach_permission(store,trainee_id,coach_id,macros,top_dishes,days):
    uid=subject(trainee_id);coach=subject(coach_id)
    if type(macros) is not bool or type(top_dishes) is not bool or type(days) is not int or days not in (7,30,90):raise ValueError('invalid_coach_permission')
    if top_dishes and not macros:raise ValueError('macros_permission_required')
    link=next((e for e in coach_links(store,uid) if e['payload']['coach_id']==coach),None)
    if not link:raise ValueError('accepted_coach_link_required')
    with store.connection() as db:
        db.execute('INSERT INTO coach_nutrition_permissions VALUES(?,?,?,?,?,?,?) ON CONFLICT(trainee_id,coach_id) DO UPDATE SET link_id=excluded.link_id,macros=excluded.macros,top_dishes=excluded.top_dishes,expires_at=excluded.expires_at,updated_at=excluded.updated_at',
                   (uid,coach,link['payload']['link_id'],int(macros),int(top_dishes),time.time()+days*86400 if macros else 0,time.time()))
    return coach_permissions(store,uid)

def coach_nutrition(store,coach_id,trainee_id,day=None):
    coach=subject(coach_id);trainee=subject(trainee_id)
    permission=next((r for r in coach_permissions(store,trainee)['items'] if r['coach_id']==coach and r['macros']),None)
    if not permission:raise PermissionError('nutrition_sharing_disabled')
    policy=preferences(store,trainee)
    if policy['rest_active'] or not policy['sources']['food'] or not policy['sources']['gym']:raise PermissionError('connection_paused')
    entities,_,access=permitted_entities(store,trainee)
    if not access['domains']['food'] or not access['domains']['gym'] or not entitlements(store,coach)['domains']['gym']:raise PermissionError('connection_access_required')
    if not any(e['source']=='food' for e in entities):raise PermissionError('food_temporarily_unavailable')
    from datetime import date
    if day is not None:date.fromisoformat(day)
    from zoneinfo import ZoneInfo
    selected=day or datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
    rows=[e for e in entities if e['source']=='food' and e['entity_id'].startswith('daily:') and e['payload']['source_local_date']==selected]
    total=rows[0]['payload'] if rows else None
    output={'date':selected,'timezone':total.get('timezone','Europe/Moscow') if total else 'Europe/Moscow','totals':total['totals'] if total else None,
            'logged_meal_count':total['logged_meal_count'] if total else 0,'coverage':'logged_meals_only',
            'top_dishes_enabled':permission['top_dishes'],'expires_at':permission['expires_at']}
    if permission['top_dishes']:
        from collections import Counter
        start=(date.fromisoformat(selected)-timedelta(days=29)).isoformat()
        names=Counter(e['payload']['display_title'] for e in entities if e['source']=='food' and e['entity_id'].startswith('meal:')
                      and start<=e['payload']['source_local_date']<=selected and e['payload'].get('display_title'))
        output['top_dishes']=[{'name':name,'logged_count':count} for name,count in names.most_common(5)]
        output['top_dishes_window_days']=30
    return output

FAQ = [
 {'id':'sources','title':'Что откуда берётся?','text':'Food передаёт сохранённые КБЖУ и оценённый состав пищи; Gym Diary — отмеченные упражнения и тренировки; Supply — собственные добавки и согласованные поля профиля. Для личной связи нужны доступ к обоим продуктам, свежие данные и включённая связь.'},
 {'id':'calories','title':'Почему тренировка не меняет цель сама?','text':'Обычная активность уже может входить в цель. Повторения сами по себе не измеряют калории. При записанной длительности и подходящем профиле показывается отдельная приблизительная оценка; сохранённая цель меняется только по вашему подтверждению.'},
 {'id':'unknown','title':'Нет записи — значит не ел или не тренировался?','text':'Нет. Незанесённое блюдо или упражнение остаётся неизвестным. Оценка нутриентов по фото приблизительна и не является диагнозом дефицита.'},
 {'id':'rest','title':'Как работает отдых?','text':'На время отдыха обычные напоминания и автоматические подсказки приостанавливаются во всех продуктах. Записи, расписания и настройки остаются. Срок оплаченной подписки продолжается. После возврата работают следующие актуальные напоминания; пропущенные не догоняют.'},
 {'id':'coach','title':'Что увидит тренер?','text':'Только если вы разрешили: дневные КБЖУ, а по отдельному переключателю — пять самых частых блюд за 30 дней. Тренер не получает список отдельных приёмов, нутриенты блюд, добавки, анализы или доступ ИИ к питанию.'},
 {'id':'frequency','title':'Как уменьшить подсказки?','text':'Режим «Меньше подсказок» показывает не больше одной новой подсказки за неделю во всех продуктах. Уже открытая подсказка может остаться до подтверждённого действия; само чтение не означает выполнение. Её можно скрыть на неделю. Отдельные напоминания включаются добровольно.'},
 {'id':'day','title':'Нужно отмечать каждый день?','text':'Нет. Итог остаётся предварительным, пока вы добровольно не подтвердите полноту записей. После новой еды или исправления дневник снова откроется. Ночная смена и пропущенная отметка не доказывают недоедание.'},
 {'id':'cache','title':'Повторный расчёт и лимиты ИИ','text':'Точный повтор неизменённых входов может использовать ваш сохранённый результат. Изменившиеся данные и разрешения требуют нового расчёта. Просмотр, обычные подсказки, порции и недавние блюда не вызывают ИИ. Доступ и защита от частых запросов продолжают проверяться.'},
 {'id':'payments','title':'Что будет после окончания одной подписки?','text':'История сохраняется; оплаченные продукты продолжают работать. Связь с завершившимся доступом прекращается. Общую подписку или недостающий продукт можно выбрать в экране подписок; пробные дни дают доступ, но не денежный зачёт.'},
]

def weekly_overview(store,user_id,now=None):
    from .context import build_context
    now=now or datetime.now(timezone.utc)
    data=build_context(store,subject(user_id),now=now)
    nutrition=data.get('nutrition') or {};activity=data.get('activity') or {}
    entities,_,_=permitted_entities(store,user_id,now)
    start=now-timedelta(days=7)
    workouts=[e for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:')
              and start<=datetime.fromisoformat(e['payload']['completed_at'].replace('Z','+00:00'))<=now]
    # Context retains a degraded Supply shell to explain source health. It is
    # not permission to turn an old ledger into a current weekly aggregate.
    supply=data.get('supply') if (data['sources'].get('supply',{}).get('status')=='ok'
        and any(e['source']=='supply' for e in entities)) else None
    intake_count=None
    if supply:
        # The public context carries only 90 recent rows. A weekly aggregate
        # must count the complete permitted window, including busy schedules.
        with store.connection() as db:
            intake_count=db.execute("SELECT count(*) FROM entities WHERE user_id=? AND source='supply' AND deleted=0 AND entity_id GLOB 'intake:*' AND json_extract(payload,'$.status')='taken' AND json_extract(payload,'$.source_local_date')>=?",(subject(user_id),start.date().isoformat())).fetchone()[0]
    return {'nutrition':(nutrition.get('history') or {}).get('7'),'workouts':{'recorded_sessions':len(workouts),
        'completed_sessions':sum(e['payload'].get('session_complete',True) for e in workouts),
        'working_sets':sum(e['payload'].get('strength_sets',0) for e in workouts)} if 'gym' in data['memberships'] else None,
        'supply':{'active_supplements':supply['active_supplement_count'],'recorded_intakes':intake_count} if supply else None,
        'sources':data['sources'],'coverage':'Только сохранённые записи. Отсутствие отметки не означает отсутствие еды, тренировки или приёма.'}
