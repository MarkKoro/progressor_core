"""Read-only candidate calculation. The existing Food bot owns opt-in and delivery."""
import sqlite3
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from .context import build_context


def candidate(store,user_id,prefs,now=None,enabled_sources=None):
    now=now or datetime.now(timezone.utc)
    from .connections import preferences
    policy=preferences(store,user_id)
    if policy['rest_active'] or not policy['notifications'] or not policy['hints']:return None
    local=now.astimezone(ZoneInfo(prefs.get('timezone','Europe/Moscow')))
    # Delay through quiet hours without sending obsolete workouts in the morning.
    if not 8<=local.hour<22 or store.hints_dismissed(user_id,'food'): return None
    c=build_context(store,user_id,now=now,target='food',enabled_sources=enabled_sources,
                    remember_recommendations=False)
    if not c['access']['domains']['food'] or 'food' not in c['memberships'] or c['sources'].get('food',{}).get('status')!='ok': return None
    from .weekly_plan import notification
    weekly=notification(store,user_id,prefs,now)
    if weekly:return weekly
    if policy['frequency']!='quiet' and policy['weight_notifications']:
        hint=next((h for h in c['hints'] if h['key']=='change_weight.v1'),None)
        if hint and not store.hint_was_seen(user_id,'food',hint['delivery_key']):
            return {'kind':'weight_review','day':local.date().isoformat(),'delivery_key':hint['delivery_key'],
                'text':hint['title']+'\n\n'+hint['message'],'action':'open_food'}
    def unseen(h): return not any(store.hint_was_seen(user_id,t,h['delivery_key']) for t in ('food','gym') if t in h['targets'])
    if prefs.get('workout_enabled'):
        workouts=(c.get('activity') or {}).get('workouts',[])
        from .workout_notification_compat import legacy_programmed_workout
        from .free_workout_notifications import allowed
        from .workout_time import free_activity_instant
        admitted=set()
        if any(not legacy_programmed_workout(w) for w in workouts):
            try:
                with store.connection() as db:
                    for w in workouts:
                        if not legacy_programmed_workout(w) and free_activity_instant(w) is not None and allowed(db,user_id,w.get('entity_id'),w,now=now.timestamp()):
                            admitted.add(w['entity_id'])
            except sqlite3.Error:
                admitted.clear()
        fresh=[]
        for w in workouts:
            if not legacy_programmed_workout(w) and w.get('entity_id') not in admitted: continue
            if w.get('session_complete') is False: continue
            stamp=datetime.fromisoformat(w['completed_at'].replace('Z','+00:00'))
            if now-timedelta(hours=2)<=stamp<=now-timedelta(minutes=30) and stamp.timestamp()>max(prefs.get('enabled_at',now.timestamp()),policy.get('last_pause_started_at',0)) and not w.get('backfilled'):
                fresh.append(w)
        hint=next((h for h in c['hints'] if h['key']=='workout_today.v1'),None)
        if fresh and hint and unseen(hint) and not any(w.get('session_complete') is False for w in workouts) and c.get('workout_follow_up') not in ('food_day_confirmed','food_recorded_after_workout'):
            day=(c.get('nutrition') or {}).get('today') or {};remaining=day.get('remaining_to_personal_goal')
            text='Тренировка записана в Gym. '
            if remaining:
                text+=f"До вашей текущей цели в журнале Food осталось: {remaining['kcal']:g} ккал; белки {remaining['protein']:g} г, жиры {remaining['fat']:g} г, углеводы {remaining['carbs']:g} г. "
            elif not (c.get('nutrition') or {}).get('targets'):
                text+='Задайте свою цель питания в Food, чтобы сравнивать её с записями. '
            else:
                text+='Сегодня в Food ещё нет записанных блюд. Проверьте полноту дневника. '
            text+='Это разница с вашей целью по записанным блюдам, а не назначение дополнительной еды. Обычная активность уже может входить в цель.'
            estimates=[w.get('energy_estimate') for w in fresh]
            if all(estimates):
                lo=sum(e['net_above_rest_kcal_range'][0] for e in estimates);hi=sum(e['net_above_rest_kcal_range'][1] for e in estimates)
                text+=f' По записанной длительности сверх покоя примерно {lo}–{hi} ккал; оценка не прибавлена к цели.'
            return {'kind':'post_workout','day':local.date().isoformat(),'delivery_key':hint['delivery_key'],'text':text,'action':'open_food'}
    # Sunday evening: one line about the whole week across the connected products. It uses the
    # weekly-review opt-in and the same delivery kind, so the Food bot needs no new consumer.
    if policy['frequency']!='quiet' and prefs.get('nutrient_enabled') and local.weekday()==6 and 17<=local.hour<21 and now.timestamp()-prefs.get('enabled_at',now.timestamp())>=86400:
        from .day_links import day_links
        links=day_links(store,user_id,now=now,target='food',enabled_sources=enabled_sources)
        week=links['week'];parts=[]
        if week.get('workouts') is not None:parts.append(f"Тренировок — {week['workouts']}.")
        if week.get('food_days') is not None:
            line=f"Питание записано {week['food_days']} из 7 дней"
            if week.get('average_kcal') is not None:line+=f", в среднем {week['average_kcal']:g} ккал"+(f" при цели {week['target_kcal']:g}" if week.get('target_kcal') else '')+(f" и {week['average_protein']:g} г белка" if week.get('average_protein') is not None else '')
            parts.append(line+'.')
        if week.get('average_water_ml'):parts.append(f"Воды в отмеченные дни — в среднем {week['average_water_ml']/1000:.1f} л.".replace('.',',',1))
        if week.get('supply_days') is not None:parts.append(f"Добавки отмечены {week['supply_days']} из 7 дней.")
        key='week_summary:'+local.strftime('%G-W%V')
        if parts and (week.get('food_days') or week.get('workouts') or week.get('supply_days')) and not store.hint_was_seen(user_id,'food',key):
            text='Итог недели\n\n'+' '.join(parts)
            if links['streak']['days']>1:text+=f" Серия — {links['streak']['days']} дн. подряд."
            if week.get('headline'):text+='\n\n'+week['headline']
            return {'kind':'nutrient_review','day':local.date().isoformat(),'delivery_key':key,'text':text+'\n\nЭто сводка ваших записей, а не оценка здоровья.','action':'open_food'}
    if policy['frequency']!='quiet' and prefs.get('nutrient_enabled') and 12<=local.hour<20 and now.timestamp()-prefs.get('enabled_at',now.timestamp())>=86400:
        hint=next((h for h in c['hints'] if h['key'].startswith('food_sources_') and unseen(h)),None)
        if hint:
            return {'kind':'nutrient_review','day':local.date().isoformat(),'delivery_key':hint['delivery_key'],
                'text':hint['title']+'\n\n'+hint['message']+'\n\nПроверьте полноту дневника. Это оценка источников в записанных блюдах; по ней нельзя установить дефицит организма или выбрать дозу добавки.', 'action':'open_food'}
    return None
