import time
from datetime import date, datetime, timedelta, timezone
from .adapters import zone
from .nutrients import CATALOG
from .access import entitlements
from .native_insights import enrich_workouts, native_hints
from .offers import bundle_preview
from .profiles import resolve_profile


def build_context(store, user_id, now=None, requested_day=None, target=None, enabled_sources=None):
    now = now or datetime.now(timezone.utc)
    entities, memberships, state = store.data(user_id)
    access=entitlements(store,user_id,now,entities)
    offer=bundle_preview(entities,access,target,now,enabled_sources)
    allowed={s for s in access['accessible_domains']}
    if enabled_sources is not None: allowed.intersection_update(enabled_sources)
    if target is not None and target not in allowed: allowed=set()
    entities=[e for e in entities if e['source'] in allowed]
    source_status = {}
    for source in ('gym', 'food', 'supply'):
        observed = state.get(source, {})
        fresh = observed.get('status') == 'ok' and time.time() - (observed.get('last_success') or 0) < 120
        source_status[source] = {'status': 'ok' if fresh else 'degraded', 'last_success': observed.get('last_success'), 'reason': None if fresh else observed.get('reason') or 'stale_or_missing_source'}
    active = {m['source'] for m in memberships if m['active'] and m['source'] in allowed}
    food_zone = zone('Europe/Moscow')
    day = date.fromisoformat(requested_day) if requested_day else now.astimezone(food_zone).date()
    fresh_entities=[e for e in entities if source_status[e['source']]['status']=='ok']
    enriched=enrich_workouts(fresh_entities,now)
    workouts = [e for e in enriched if datetime.fromisoformat(e['payload']['completed_at'].replace('Z', '+00:00')).astimezone(food_zone).date() == day]
    activity_reason = 'missing_gym_membership' if 'gym' not in active else 'stale_gym_source' if source_status['gym']['status'] != 'ok' else 'workout_recorded' if workouts else 'no_completed_workout_recorded'
    activity = {'date': day.isoformat(), 'day_timezone': 'Europe/Moscow', 'day_basis': 'food_legacy_day', 'reason': activity_reason, 'completed_workout_count': len(workouts) if source_status['gym']['status'] == 'ok' else None, 'workouts': [e['payload'] for e in workouts] if source_status['gym']['status'] == 'ok' else [], 'provenance': [{'source': 'gym', 'event_id': e['event_id'], 'occurred_at': e['payload']['completed_at']} for e in workouts], 'calorie_target_adjustment': None, 'uncertainty': 'Точное время и расход энергии силовой тренировки не записаны. Цель питания автоматически не изменяется.'}
    totals = sorted([e for e in entities if e['source'] == 'food' and e['entity_id'].startswith('daily:')], key=lambda e: e['payload']['source_local_date'])
    food_target = next((e for e in entities if e['source'] == 'food' and e['entity_id'].startswith('target:')), None)
    history = {}
    for window in (7, 30, 90):
        start = day - timedelta(days=window)
        rows = [e for e in totals if start.isoformat() <= e['payload']['source_local_date'] < day.isoformat()]
        nutrients = {}
        codes = sorted({code for e in rows for code in e['payload'].get('nutrients', {})})
        for code in codes:
            observations = [e['payload']['nutrients'][code] for e in rows if code in e['payload'].get('nutrients', {})]
            units = {o['unit'] for o in observations}
            if len(units) != 1:
                continue
            nutrients[code] = {'name': CATALOG[code]['name'], 'unit': units.pop(), 'sum_on_observed_days': round(sum(o['value'] for o in observations), 5), 'average_on_observed_days': round(sum(o['value'] for o in observations) / len(observations), 5), 'observed_days': len(observations), 'observed_meals': sum(o['observed_meals'] for o in observations), 'logged_days': len(rows), 'logged_meals': sum(e['payload']['logged_meal_count'] for e in rows), 'window_days': window, 'qualities': sorted({q for o in observations for q in o['qualities']}), 'observed_components':sum(o.get('observed_components',o['observed_meals']) for o in observations), 'assessed_components':sum(o.get('assessed_components',o['observed_meals']) for o in observations), 'coverage': 'known_components_only; meals_without_estimates_unknown'}
        history[str(window)] = {'window_start': start.isoformat(), 'window_end_exclusive': day.isoformat(), 'logged_days': len(rows), 'window_days': window, 'logged_meals': sum(e['payload']['logged_meal_count'] for e in rows), 'averages_on_logged_days': {key: round(sum(e['payload']['totals'][key] for e in rows) / len(rows), 2) if rows else None for key in ('kcal', 'protein', 'fat', 'carbs')}, 'coverage': 'logged_meals_only', 'nutrients': nutrients, 'micronutrients_available': bool(nutrients), 'provenance': [{'source': 'food', 'event_id': e['event_id'], 'date': e['payload']['source_local_date']} for e in rows]}
    seven = history['7']
    reason = 'missing_food_membership' if 'food' not in active else 'stale_food_source' if source_status['food']['status'] != 'ok' else 'insufficient_logged_days' if seven['logged_days'] < 3 else 'missing_protein_target' if not food_target or not food_target['payload']['targets']['protein'] else 'no_rule_triggered'
    recommendation = None
    protein_target = food_target['payload']['targets']['protein'] if food_target else None
    if reason == 'no_rule_triggered' and seven['averages_on_logged_days']['protein'] < protein_target * .8:
        reason = 'logged_protein_below_current_personal_target'
        recommendation = {'rule': 'logged_protein_vs_personal_goal.v1', 'title': 'Проверьте полноту записей питания', 'message': f"За {seven['logged_days']} записанных дней из последних 7 средний белок в журнале — {seven['averages_on_logged_days']['protein']:g} г, текущая личная цель Food — {protein_target:g} г. Проверьте, все ли приёмы пищи внесены, затем сравните журнал с вашей целью.", 'action': 'review_food_log', 'threshold_basis': 'display_rule_80_percent_of_personal_goal; not_a_medical_threshold', 'confidence': 'limited', 'uncertainty': 'Журнал может быть неполным. По этим записям нельзя установить клинический дефицит или необходимость добавки. Дозы и назначения не рассчитываются.', 'provenance': seven['provenance'] + [{'source': 'food', 'event_id': food_target['event_id'], 'basis': 'current_personal_food_goal'}], 'coverage': {'logged_days': seven['logged_days'], 'window_days': 7}, 'calculation': {'logged_protein_average_g': seven['averages_on_logged_days']['protein'], 'current_personal_target_g': protein_target, 'comparison_ratio': round(seven['averages_on_logged_days']['protein'] / protein_target, 3)}, 'rule_version': 1, 'window_start': seven['window_start'], 'window_end_exclusive': day.isoformat()}
    rec_id = store.remember(user_id, 'logged_protein_vs_personal_goal.v1', day.isoformat(), recommendation)
    if recommendation:
        recommendation = {**recommendation, 'id': rec_id}
    supply_entities = [e for e in entities if e['source'] == 'supply'] if source_status['supply']['status'] == 'ok' else []
    supply_context={'active_supplements':[e['payload'] for e in supply_entities if e['entity_id'].startswith('supplement:') and e['payload'].get('active')], 'recent_intakes':sorted([e['payload'] for e in supply_entities if e['entity_id'].startswith('intake:')],key=lambda p:p['source_local_date'],reverse=True)[:90], 'lab_reports':[e['payload'] for e in supply_entities if e['entity_id'].startswith('lab:')], 'reported_profile':next((e['payload']['reported_profile'] for e in supply_entities if e['payload'].get('profile_kind')=='reported_health'),None), 'uncertainty':'Дозы в Supply записаны текстом и не складываются с оценками пищи. Анализы сохраняют исходные единицы и статус обработки; Core не устанавливает диагнозы.'}
    data={'schema_version': 1, 'generated_at': now.isoformat(), 'user_id': user_id, 'memberships': sorted(active), 'sources': source_status, 'activity': activity, 'nutrition': {'reason': reason, 'day_timezone': 'Europe/Moscow', 'targets': food_target['payload']['targets'] if food_target and source_status['food']['status'] == 'ok' else None, 'history': history if source_status['food']['status'] == 'ok' else None}, 'recommendations': [recommendation] if recommendation else [], 'supply': {**supply_context,'active_supplement_count': sum(bool(e['payload'].get('active')) for e in supply_entities if e['entity_id'].startswith('supplement:')), 'recorded_intake_count': sum(e['payload'].get('status') == 'taken' for e in supply_entities if e['entity_id'].startswith('intake:')), 'lab_report_count': sum(e['entity_id'].startswith('lab:') for e in supply_entities), 'status': source_status['supply']['status']}, 'notification_delivery': 'webapp_only','access':access}
    # Unauthorized sources are absent rather than displayed as upsell/error/zero-intake hints.
    if 'gym' not in active: data['activity']=None
    if 'food' not in active: data['nutrition']=None; data['recommendations']=[]
    if 'supply' not in active: data['supply']=None
    data['sources']={s:status for s,status in source_status.items() if s in active}
    data['profile']=resolve_profile(fresh_entities,now)
    current=next((e for e in totals if e['payload']['source_local_date']==day.isoformat()),None)
    if data.get('nutrition') is not None and source_status['food']['status']=='ok':
        data['nutrition']['today']={'date':day.isoformat(),'logged_meal_count':current['payload']['logged_meal_count'] if current else 0,
            'totals':current['payload']['totals'] if current else None,'coverage':'logged_meals_only',
            'remaining_to_personal_goal':{k:round(max(v-current['payload']['totals'][k],0),1) for k,v in data['nutrition']['targets'].items()} if current and data['nutrition']['targets'] else None}
    if activity and any(w['payload'].get('energy_estimate') for w in workouts):
        activity['uncertainty']='Расход энергии приблизительный. Цель питания автоматически не изменяется: обычная активность уже может быть учтена.'
    if data.get('activity') is not None:
        data['activity']['recorded_session_count']=len(workouts)
        data['activity']['completed_workout_count']=sum(w['payload'].get('session_complete',True) for w in workouts)
    data['hints']=native_hints(data,fresh_entities,now,day)
    for hint in data['hints']:
        hint['delivery_key']=hint['key']+':'+day.isoformat()
        hint['date']=day.isoformat()
    data['inline_hint']=next((h for h in data['hints'] if target in h['targets']),None) if target and not store.hints_dismissed(user_id,target) else None
    data['offer_preview']=offer if target and not store.offers_dismissed(user_id,target) and not store.hints_dismissed(user_id,target) else None
    return data
