"""Cross-product links for the home screen: deterministic rules over the owner's own records.

No AI, no writes, no clinical claims. A food estimate says what was recorded, never what the
body has; a supplement card never tells anyone to start or stop, only what the records show.
Sources the owner has not paid for or connected are absent from `data`, so their rules are silent.
"""
from datetime import datetime, timedelta

# Adult reference intakes used only as a yardstick for recorded food, with the unit the
# nutrient catalog stores. Supplement names are matched by these stems.
NUTRIENTS = (
    ('vitamin_c', 'витамина C', 90, 'mg', ('витамин c', 'витамин с', 'vitamin c', 'аскорбин')),
    ('vitamin_d', 'витамина D', 15, 'ug', ('витамин d', 'vitamin d', 'd3', 'д3', 'холекальциферол')),
    ('vitamin_b12', 'витамина B12', 2.4, 'ug', ('b12', 'b-12', 'в12', 'кобаламин', 'cobalamin')),
    ('iron', 'железа', 14, 'mg', ('желез', 'iron', 'ferr')),
    ('magnesium', 'магния', 400, 'mg', ('магни', 'magnesium')),
    ('zinc', 'цинка', 12, 'mg', ('цинк', 'zinc')),
    ('calcium', 'кальция', 1000, 'mg', ('кальци', 'calcium')),
    ('omega_3', 'омега-3', 1.1, 'g', ('омега', 'omega', 'рыбий жир', 'fish oil')),
)
FAT_SOLUBLE = ('d3', 'д3', 'витамин d', 'vitamin d', 'омега', 'omega', 'рыбий жир', 'k2', 'к2', 'витамин e', 'витамин е', 'витамин a', 'витамин а', 'куркумин', 'коэнзим', 'q10')
CONFLICTS = ((('желез', 'iron', 'ferr'), ('кальци', 'calcium'), 'Железо и кальций'), (('желез', 'iron', 'ferr'), ('цинк', 'zinc'), 'Железо и цинк'),
             (('кальци', 'calcium'), ('магни', 'magnesium'), 'Кальций и магний'))
UNIT = {'mg': 'мг', 'ug': 'мкг', 'g': 'г'}


def _has(names, stems):
    return next((name for name in names if any(stem in name.lower() for stem in stems)), None)


def _number(value):
    return f'{value:g}' if value < 10 else f'{round(value):g}'


def _card(key, sources, title, text, action=None, priority=50):
    return {'key': key, 'sources': sources, 'title': title, 'text': text, 'action': action, 'priority': priority}


def _dates(entities, zone):
    """Local days with at least one record, per source."""
    days = {'gym': set(), 'food': set(), 'supply': set()}
    for entity in entities:
        payload = entity['payload']
        if entity['source'] == 'food' and entity['entity_id'].startswith('daily:') and payload.get('logged_meal_count'):
            days['food'].add(payload['source_local_date'])
        elif entity['source'] == 'supply' and entity['entity_id'].startswith('intake:') and payload.get('status') == 'taken':
            days['supply'].add(payload['source_local_date'])
        elif entity['source'] == 'gym' and payload.get('completed_at') and payload.get('session_complete', True):
            try:
                days['gym'].add(datetime.fromisoformat(payload['completed_at'].replace('Z', '+00:00')).astimezone(zone).date().isoformat())
            except (ValueError, TypeError):
                pass
    return days


def build(data, entities, now, day, zone):
    nutrition, supply, activity = data.get('nutrition'), data.get('supply'), data.get('activity')
    seven = ((nutrition or {}).get('history') or {}).get('7') or {}
    targets = (nutrition or {}).get('targets') or {}
    today = (nutrition or {}).get('today') or {}
    names = [str(item.get('name') or '') for item in (supply or {}).get('active_supplements') or []]
    days = _dates(entities, zone)
    week = [(day - timedelta(days=offset)).isoformat() for offset in range(7)]
    cards = []

    # Food ↔ Supply: what recorded food already covers, and what it does not.
    solid = seven.get('logged_days', 0) >= 5 and seven.get('logged_meals', 0) >= 10
    if nutrition and solid:
        for code, label, reference, unit, stems in NUTRIENTS:
            observed = (seven.get('nutrients') or {}).get(code) or {}
            average = observed.get('average_on_observed_days')
            if observed.get('unit') != unit or average is None or observed.get('observed_days') != seven['logged_days']:
                continue
            taking = _has(names, stems) if supply else None
            amount = f"{_number(average)} {UNIT[unit]} в день при ориентире {_number(reference)} {UNIT[unit]}"
            if taking and average >= reference * 1.2:
                cards.append(_card('covered_' + code, ['food', 'supply'], f'Из еды хватает {label}',
                    f"За {seven['logged_days']} записанных дней в еде в среднем {amount}. В добавках у вас «{taking}». Это оценка по дневнику, а не анализ: нужна ли добавка, решать вам и врачу.",
                    {'kind': 'supply_plan', 'label': 'Мои добавки'}, 20))
            elif not taking and average < reference * .5:
                cards.append(_card('low_' + code, ['food'] + (['supply'] if supply else []), f'В еде мало {label}',
                    f"За {seven['logged_days']} записанных дней в еде в среднем {amount}. Пропущенные блюда не учтены — сначала проверьте дневник, потом рацион.",
                    {'kind': 'open_food', 'label': 'Посмотреть питание'}, 30))

    # Supply ↔ Food: fat-soluble supplements and a day with almost no recorded fat.
    soluble = _has(names, FAT_SOLUBLE) if supply else None
    fat = (today.get('totals') or {}).get('fat')
    if soluble and today.get('logged_meal_count') and fat is not None and fat < 10:
        cards.append(_card('fat_soluble', ['supply', 'food'], 'Добавке нужен жир в еде',
            f"«{soluble}» лучше усваивается с едой, где есть жир. Сегодня в дневнике {_number(fat)} г жира.", {'kind': 'food_log', 'label': 'Записать еду'}, 25))

    # Supply ↔ Supply: pairs that compete when taken together.
    for first, second, title in CONFLICTS:
        a, b = (_has(names, first), _has(names, second)) if supply else (None, None)
        if a and b and a != b:
            cards.append(_card('conflict_' + first[0] + '_' + second[0], ['supply'], title + ' лучше разнести',
                f"«{a}» и «{b}» мешают друг другу усваиваться, если принимать их вместе. Удобнее в разные приёмы с разницей около двух часов.",
                {'kind': 'supply_plan', 'label': 'Расписание'}, 40))

    # Gym ↔ Food: protein left after today's workout; training hard while eating below the goal.
    remaining = today.get('remaining_to_personal_goal') or {}
    if activity and activity.get('completed_workout_count') and remaining.get('protein', 0) >= 20:
        cards.append(_card('protein_after_workout', ['gym', 'food'], 'После тренировки — белок',
            f"Тренировка сегодня записана. До вашей цели по белку осталось {_number(remaining['protein'])} г.", {'kind': 'food_log', 'label': 'Записать еду'}, 10))
    trained = [d for d in sorted(days['gym']) if (day - timedelta(days=14)).isoformat() <= d <= day.isoformat()]
    means = seven.get('averages_on_logged_days') or {}
    if nutrition and len(trained) >= 3 and seven.get('logged_days', 0) >= 4 and targets.get('kcal') and means.get('kcal') is not None and means['kcal'] < targets['kcal'] * .85:
        cards.append(_card('training_under_goal', ['gym', 'food'], 'Нагрузка есть, еды меньше цели',
            f"Тренировок за две недели — {len(trained)}, а в записанные дни в среднем {_number(means['kcal'])} ккал при цели {_number(targets['kcal'])}. Для роста силы этого может не хватать — или дневник неполный.",
            {'kind': 'open_food', 'label': 'Посмотреть питание'}, 35))

    # Gym ↔ Supply: creatine only works taken daily.
    creatine = _has(names, ('креатин', 'creatine')) if supply else None
    if creatine:
        taken = {e['payload']['source_local_date'] for e in entities if e['source'] == 'supply' and e['entity_id'].startswith('intake:')
                 and e['payload'].get('status') == 'taken' and any(s in str(e['payload'].get('name') or '').lower() for s in ('креатин', 'creatine'))}
        count = len(taken & set(week))
        if count < 5:
            cards.append(_card('creatine_daily', ['supply', 'gym'], 'Креатин работает при ежедневном приёме',
                f"«{creatine}» отмечен {count} из 7 последних дней. Эффект держится на ежедневном приёме, включая дни без тренировок.", {'kind': 'supply_plan', 'label': 'Отметить'}, 45))

    # All three: one shared streak and one weekly line.
    any_day = days['gym'] | days['food'] | days['supply']
    streak, cursor = 0, day if day.isoformat() in any_day else day - timedelta(days=1)
    while cursor.isoformat() in any_day and streak < 3650:
        streak += 1
        cursor -= timedelta(days=1)
    week_set = set(week)
    summary = {'workouts': len(days['gym'] & week_set) if activity is not None else None,
               'food_days': len(days['food'] & week_set) if nutrition is not None else None,
               'supply_days': len(days['supply'] & week_set) if supply is not None else None,
               'average_kcal': means.get('kcal') if nutrition and seven.get('logged_days') else None,
               'average_protein': means.get('protein') if nutrition and seven.get('logged_days') else None,
               'target_kcal': targets.get('kcal'), 'target_protein': targets.get('protein')}
    weakest = None
    scored = [(value / 7, name) for name, value in (('питание', summary['food_days']), ('добавки', summary['supply_days'])) if value is not None]
    if summary['workouts'] is not None:
        scored.append((min(summary['workouts'] / 3, 1), 'тренировки'))
    if scored and min(scored)[0] < .6:
        weakest = min(scored)[1]
    summary['headline'] = (f'На этой неделе просели {weakest}.' if weakest else 'Неделя идёт ровно по всем подключённым разделам.') if scored else None
    cards.sort(key=lambda card: (card['priority'], card['key']))
    return {'schema_version': 1, 'day': day.isoformat(), 'cards': cards[:6], 'streak': {'days': streak, 'today_recorded': day.isoformat() in any_day},
            'week': summary, 'coverage': 'Только ваши сохранённые записи. Оценки по еде — не анализы и не назначение.'}


def day_links(store, user_id, now=None, target=None, enabled_sources=None):
    from datetime import timezone
    from .adapters import zone
    from .context import build_context
    now = now or datetime.now(timezone.utc)
    food_zone = zone('Europe/Moscow')
    day = now.astimezone(food_zone).date()
    snapshot = store.context_snapshot(user_id, workout_day=day.isoformat())
    data = build_context(store, user_id, now, target=target, enabled_sources=enabled_sources, _request_data=snapshot, remember_recommendations=False)
    # The same access, freshness and consent filter the context applied: only sources it kept.
    kept = {source for source, present in (('gym', data.get('activity')), ('food', data.get('nutrition')), ('supply', data.get('supply'))) if present is not None}
    entities = [e for e in snapshot[0][0] if e['source'] in kept and (data.get('sources') or {}).get(e['source'], {}).get('status') == 'ok']
    if data.get('connections', {}).get('rest_active') or not data.get('connections', {}).get('hints', True):
        result = build({'nutrition': None, 'supply': None, 'activity': None}, entities, now, day, food_zone)
        result['cards'] = []
        return result
    return build(data, entities, now, day, food_zone)
