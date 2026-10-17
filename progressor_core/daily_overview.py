"""Small personal day view and explainable connection health; no AI or native writes."""
import time
from datetime import datetime, timezone
from .access import entitlements
from .adapters import zone
from .connections import preferences
from .contracts import SOURCES, subject

NAMES = {'gym': 'Gym Diary', 'food': 'Food', 'supply': 'Supply'}
STATUS = {
    'ready': ('Данные актуальны', 'Сохранённые записи участвуют в общей картине.'),
    'paused': ('Сейчас отдых', 'Подсказки и напоминания на паузе. Записи и сроки подписок сохраняются.'),
    'disabled': ('Связь выключена вами', 'Её можно включить в разделе «Связи и напоминания».'),
    'not_connected': ('Профиль ещё не подключён', 'Откройте этот бот и завершите его обычную настройку.'),
    'access_required': ('Для связи нужен активный доступ', 'История сохраняется. Доступ к каждому продукту виден в «Подписках».'),
    'target_unavailable': ('Общая картина в этом продукте недоступна', 'Проверьте его доступ и включение связи. Остальные продукты продолжают работать.'),
    'consent_required': ('Нужно согласие в Supply', 'Подтвердите использование данных в собственном профиле Supply.'),
    'stale': ('Обновление временно задерживается', 'Старые данные не используются для новых подсказок. Попробуйте обновить позже.'),
    'unavailable': ('Связь временно недоступна', 'Текущий продукт и ваши записи продолжают работать.'),
}


def connection_health(store, user_id, now=None, *, target=None, snapshot=None, access=None, policy=None):
    uid = subject(user_id)
    now = now or datetime.now(timezone.utc)
    entities, members, state = snapshot if snapshot is not None else store.settings_snapshot(uid)
    access = access if access is not None else entitlements(store, uid, now, entities)
    policy = policy if policy is not None else preferences(store, uid)
    enabled = set(getattr(store, 'enabled_sources', SOURCES))
    profiles = {e['source']: e['payload'] for e in entities
                if e['entity_id'].startswith('profile:') and e['payload'].get('profile_kind') is None}
    joined = {m['source'] for m in members if m['active']}
    target_ready = target is None or (target in enabled and target in joined
                   and access['domains'][target] and policy['sources'][target])
    rows = []
    for source in SOURCES:
        observed = state.get(source, {})
        stamp = observed.get('last_success')
        age = time.time() - stamp if isinstance(stamp, (int, float)) else None
        if source not in enabled: status = 'unavailable'
        elif policy['rest_active']: status = 'paused'
        elif not policy['sources'][source]: status = 'disabled'
        elif not target_ready: status = 'target_unavailable'
        elif source not in joined: status = 'not_connected'
        elif not access['domains'][source]: status = 'access_required'
        elif source == 'supply' and not profiles.get(source, {}).get('consent_given'): status = 'consent_required'
        elif observed.get('status') != 'ok' or age is None or not -5 <= age < 120: status = 'stale'
        else: status = 'ready'
        title, message = STATUS[status]
        rows.append({'source': source, 'name': NAMES[source], 'status': status, 'label': title,
                     'message': message, 'last_synced_at': datetime.fromtimestamp(stamp, timezone.utc).isoformat()
                     if status in ('ready', 'stale') and stamp else None})
    return {'items': rows, 'rest_active': policy['rest_active'], 'hints_enabled': policy['hints'],
            'notifications_enabled': policy['notifications'],
            'note': 'Изменения обычно появляются в течение минуты. Отсутствие записи не означает нулевой показатель.'}


def daily_overview(store, user_id, now=None, *, target=None):
    from .journey import workout_follow_up
    uid = subject(user_id)
    if target is not None and target not in SOURCES: raise ValueError('invalid_target')
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(zone('Europe/Moscow')).date().isoformat()
    snapshot, intake_counts = store.daily_snapshot(uid, day)
    entities, _, _ = snapshot
    policy = preferences(store, uid)
    health = connection_health(store, uid, now, target=target, snapshot=snapshot, policy=policy)
    ready = {r['source'] for r in health['items'] if r['status'] == 'ready'}
    sections = []
    workouts = [e['payload'] for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:')] if 'gym' in ready else []
    current = next((e['payload'] for e in entities if e['source']=='food' and e['entity_id'].startswith('daily:')), None) if 'food' in ready else None
    food = {'totals':current['totals'] if current else None,'logged_meal_count':current['logged_meal_count'] if current else 0,
            'day_complete':bool(current and current.get('day_complete')),'latest_meal_at':current.get('latest_meal_at') if current else None}
    if 'gym' in ready:
        total = len(workouts)
        completed = sum(w.get('session_complete', True) for w in workouts)
        working = sum((w.get('strength_metrics') or {}).get('working_sets', w.get('strength_sets', 0))
                      for w in workouts)
        text = (f'Завершено занятий — {completed}; незавершённых записей — {total - completed}. '
                f'Рабочих подходов — {working}.') if total else 'За этот день тренировочных записей пока нет.'
        sections.append({'source': 'gym', 'name': NAMES['gym'], 'day': day, 'timezone': 'Europe/Moscow',
                         'text': text, 'recorded_sessions': total, 'completed_sessions': completed,
                         'working_sets': working})
    if 'food' in ready:
        totals = food['totals']
        if totals is None:
            text = 'Блюд за этот день пока не записано. Фактический рацион неизвестен.'
        else:
            text = (f"Записано блюд — {food['logged_meal_count']}: {totals['kcal']:g} ккал; "
                    f"Б {totals['protein']:g}, Ж {totals['fat']:g}, У {totals['carbs']:g} г. ")
            text += 'Полнота дня подтверждена вами.' if food['day_complete'] else 'Дневник ещё не подтверждён как полный.'
        sections.append({'source': 'food', 'name': NAMES['food'], 'day': day, 'timezone': 'Europe/Moscow',
                         'text': text, 'logged_meals': food['logged_meal_count'], 'totals': totals,
                         'day_complete': food['day_complete']})
    if 'supply' in ready:
        profile = next(e['payload'] for e in entities if e['source'] == 'supply'
                       and e['entity_id'].startswith('profile:') and e['payload'].get('profile_kind') is None)
        tz = profile.get('timezone') or 'UTC'
        supply_day = now.astimezone(zone(tz)).date().isoformat()
        # Count the entire owned local day, not the bounded recent-intake list.
        counts = {r['status']:r['records'] for r in intake_counts if r['day']==supply_day}
        taken, skipped = counts.get('taken', 0), counts.get('skipped', 0)
        sections.append({'source': 'supply', 'name': NAMES['supply'], 'day': supply_day, 'timezone': tz,
                         'text': f'Отметок «принято» — {taken}; «пропущено» — {skipped}. Неотмеченные приёмы неизвестны.',
                         'taken_records': taken, 'skipped_records': skipped})
    follow_up = workout_follow_up({'activity':{'workouts':workouts},'nutrition':{'today':food},
        'sources':{'food':{'status':'ok'}}},now) if {'gym', 'food'} <= ready else None
    relationship = {
        'training_in_progress': 'Свободная тренировка ещё не завершена. Напоминание после тренировки пока не требуется.',
        'food_recorded_after_workout': 'После последней завершённой тренировки вы уже записали еду. Повторное напоминание о питании не требуется.',
        'food_day_confirmed': 'День питания подтверждён. Повторное напоминание после тренировки не требуется.',
        'food_review_available': 'Тренировка учтена в Food. Сравнение идёт с вашей сохранённой целью; расход не добавляется к ней повторно.',
    }.get(follow_up)
    return {'schema_version': 1, 'title': 'Сегодня вместе', 'generated_at': now.isoformat(), 'day': day,
            'day_timezone': 'Europe/Moscow', 'day_label': 'Тренировки и питание — день журнала Food, Москва (UTC+3). Приёмы Supply — по его часовому поясу.',
            'sections': sections, 'health': health, 'relationship': relationship,
            'workout_follow_up': follow_up, 'coverage': 'Только ваши сохранённые записи. Это сводка, а не оценка здоровья или назначение.'}
