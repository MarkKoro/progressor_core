"""One optional weekly review, using complete saved days and the current goal.

No provider request, guessed missing meals, clinical thresholds, or automatic
goal changes. The weekday/hour are a product default, not a universal optimum.
"""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from .connections import permitted_entities,preferences
from .contracts import digest

EXAMPLES={
 'protein':('Бобовые, тофу или обычные яйца, рыба, птица, творог — выберите привычный источник белка.',
            'Бобовые, тофу или соевые продукты — примеры источников белка.'),
 'fat':('Растительное масло, орехи или семена — примеры источников жиров.',)*2,
 'carbs':('Крупа, картофель, хлеб или фрукты — простые источники углеводов.',)*2}
LABELS={'kcal':'ккал','protein':'белка, г','fat':'жиров, г','carbs':'углеводов, г'}

def review(store,user_id,now=None):
    now=now or datetime.now(timezone.utc)
    entities,_,access=permitted_entities(store,user_id,now)
    policy=preferences(store,user_id,now.timestamp())
    food=[e for e in entities if e['source']=='food']
    end=now.astimezone(ZoneInfo('Europe/Moscow')).date();start=end-timedelta(days=7)
    days=sorted([e for e in food if e['entity_id'].startswith('daily:') and start.isoformat()<=e['payload']['source_local_date']<end.isoformat()],key=lambda e:e['payload']['source_local_date'])
    confirmed=[e for e in days if e['payload'].get('day_complete') is True]
    goal=next((e for e in food if e['entity_id'].startswith('target:')),None)
    goal_stable=bool(goal and datetime.fromisoformat(goal['occurred_at'].replace('Z','+00:00')).astimezone(ZoneInfo('Europe/Moscow')).date()<=start)
    enough=len(confirmed)>=5 and goal_stable
    means={k:round(sum(e['payload']['totals'][k] for e in confirmed)/len(confirmed),1) if confirmed else None for k in LABELS}
    gaps={k:round(max(goal['payload']['targets'][k]-means[k],0),1) for k in LABELS} if enough else None
    text=f'План на неделю · {start:%d.%m}–{end-timedelta(days=1):%d.%m}\n\nЗаписаны {len(days)} дней из 7; полнота подтверждена для {len(confirmed)}.'
    suggestions=[]
    if enough:
        text+='\nВ подтверждённых днях в среднем: '+', '.join(f'{means[k]:g} {LABELS[k]}' for k in LABELS)+'.'
        substantial={k:v for k,v in gaps.items() if v>max(5,goal['payload']['targets'][k]*.1)}
        if substantial:text+='\nДо вашей цели в этих днях обычно оставалось: '+', '.join(f'{v:g} {LABELS[k]}' for k,v in substantial.items())+'.'
        else:text+='\nБольших повторяющихся расхождений с вашей текущей целью в этих записях нет.'
        from shared.food_sources import macro_examples
        health=next((e['payload'].get('reported_profile',{}) for e in entities if e['source']=='supply' and e['payload'].get('profile_kind')=='reported_health'),{})
        for k in ('protein','fat','carbs'):
            if k in substantial:
                foods=macro_examples(k,policy,health.get('country_code'))
                suggestions.append('Простые варианты '+LABELS[k].split(',')[0]+': '+('; '.join(foods) if foods else 'уточните подходящие продукты в пищевых источниках')+'. Проверьте состав конкретного продукта.')
        if suggestions:text+='\n\n'+'\n'.join(suggestions)
    else:
        text+='\nПока показываем записи без вывода о недоедании: '+('цель менялась в течение недели.' if goal and not goal_stable else 'для сравнения нужны ваша цель и хотя бы пять подтверждённых дней.')
    text+='\n\nЭто обзор дневника. Незаписанные блюда неизвестны, цель питания не менялась. Количество еды выбирайте с учётом вашей цели и самочувствия.'
    return {'available':bool(food and 'food' in access['accessible_domains']),'window_start':start.isoformat(),
        'window_end_exclusive':end.isoformat(),'logged_days':len(days),'confirmed_days':len(confirmed),
        'goal_stable':goal_stable,'averages_on_confirmed_days':means,'remaining_to_personal_goal':gaps,
        'suggestions':suggestions,'text':text,'coverage':'user_confirmed_logged_days_only',
        'provenance':[{'source':'food','event_id':e['event_id']} for e in days]+([{'source':'food','event_id':goal['event_id']}] if goal else [])}

def notification(store,user_id,prefs,now=None):
    now=now or datetime.now(timezone.utc);policy=preferences(store,user_id,now.timestamp())
    if not policy['weekly_plan'] or policy['rest_active'] or not policy['hints'] or not policy['notifications']:return None
    local=now.astimezone(ZoneInfo(prefs.get('timezone','Europe/Moscow')))
    weekday=0 if policy['weekly_day']=='monday' else 6
    if local.weekday()!=weekday or not policy['weekly_hour']<=local.hour<min(policy['weekly_hour']+2,22):return None
    item=review(store,user_id,now)
    if not item['available'] or not item['logged_days']:return None
    # Monday/Sunday choices for the same ISO week share one durable reservation.
    key='weekly_plan:'+local.strftime('%G-W%V')
    return {'kind':'weekly_plan','day':local.date().isoformat(),'delivery_key':key,'text':item['text'],'action':'open_food'}
