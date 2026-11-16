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
STIMULANTS = ('кофеин', 'caffeine', 'предтрен', 'pre-workout', 'preworkout', 'гуаран', 'энергет')
PROTEIN_POWDER = ('протеин', 'protein', 'whey', 'изолят', 'казеин', 'гейнер')
MILESTONES = (3, 7, 14, 30, 60, 100, 200, 365)
GOAL_NAMES = {'lose': 'сбросить', 'maintain': 'поддерживать', 'gain': 'набрать'}


def _local(value, zone):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(zone)
    except (ValueError, TypeError):
        return None


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


def build(data, entities, now, day, zone, rest_days=()):
    nutrition, supply, activity = data.get('nutrition'), data.get('supply'), data.get('activity')
    seven = ((nutrition or {}).get('history') or {}).get('7') or {}
    targets = (nutrition or {}).get('targets') or {}
    today = (nutrition or {}).get('today') or {}
    names = [str(item.get('name') or '') for item in (supply or {}).get('active_supplements') or []]
    days = _dates(entities, zone)
    local_now = now.astimezone(zone)
    goal = ((data.get('profile') or {}).get('values') or {}).get('goal')
    yesterday = (day - timedelta(days=1)).isoformat()
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
    enough = nutrition and seven.get('logged_days', 0) >= 4 and targets.get('kcal') and means.get('kcal') is not None
    # One goal for everything: the goal reported in Food decides how the same numbers read.
    goal_card = False
    if enough and goal == 'gain' and means['kcal'] < targets['kcal'] * .9:
        goal_card = True
        cards.append(_card('goal_gain_under', ['food', 'gym'], 'Для набора еды пока мало',
            f"Цель — набрать, а в записанные дни в среднем {_number(means['kcal'])} ккал при цели {_number(targets['kcal'])}." + (f" Тренировок за две недели — {len(trained)}." if trained else ''),
            {'kind': 'food_log', 'label': 'Записать еду'}, 32))
    elif enough and goal == 'lose' and means['kcal'] > targets['kcal'] * 1.1:
        goal_card = True
        cards.append(_card('goal_lose_over', ['food'], 'Калорий больше цели',
            f"Цель — сбросить, а в записанные дни в среднем {_number(means['kcal'])} ккал при цели {_number(targets['kcal'])}.", {'kind': 'open_food', 'label': 'Посмотреть питание'}, 32))
    if not goal_card and nutrition and len(trained) >= 3 and seven.get('logged_days', 0) >= 4 and targets.get('kcal') and means.get('kcal') is not None and means['kcal'] < targets['kcal'] * .85:
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

    # Supply ↔ Food: partners that help each other, and a protein powder missing from the diary.
    if nutrition and solid and supply:
        observed = seven.get('nutrients') or {}
        iron, vitamin_c = _has(names, ('желез', 'iron', 'ferr')), observed.get('vitamin_c') or {}
        if iron and vitamin_c.get('unit') == 'mg' and vitamin_c.get('average_on_observed_days') is not None and vitamin_c['average_on_observed_days'] < 45 and not _has(names, ('витамин c', 'витамин с', 'vitamin c', 'аскорбин')):
            cards.append(_card('partner_iron_c', ['supply', 'food'], 'Железу помогает витамин C',
                f"«{iron}» усваивается лучше вместе с витамином C, а в еде его в среднем {_number(vitamin_c['average_on_observed_days'])} мг в день. Подойдут цитрусовые, перец, ягоды.",
                {'kind': 'open_food', 'label': 'Посмотреть питание'}, 42))
        calcium, vitamin_d = _has(names, ('кальци', 'calcium')), observed.get('vitamin_d') or {}
        if calcium and not _has(names, ('витамин d', 'vitamin d', 'd3', 'д3')) and vitamin_d.get('unit') == 'ug' and vitamin_d.get('average_on_observed_days') is not None and vitamin_d['average_on_observed_days'] < 7.5:
            cards.append(_card('partner_calcium_d', ['supply', 'food'], 'Кальцию нужен витамин D',
                f"«{calcium}» усваивается с участием витамина D, а в еде его в среднем {_number(vitamin_d['average_on_observed_days'])} мкг в день. Это повод обсудить с врачом, а не назначение.",
                {'kind': 'supply_plan', 'label': 'Мои добавки'}, 43))
    powder = _has(names, PROTEIN_POWDER) if supply else None
    if powder and nutrition and seven.get('logged_days', 0) >= 3 and targets.get('protein') and means.get('protein') is not None and means['protein'] < targets['protein'] * .8:
        cards.append(_card('powder_not_logged', ['supply', 'food'], 'Протеин есть, белка в дневнике мало',
            f"В добавках «{powder}», а белка в записанные дни в среднем {_number(means['protein'])} г при цели {_number(targets['protein'])}. Если пьёте его — записывайте в еду, иначе итог занижен.",
            {'kind': 'food_log', 'label': 'Записать еду'}, 28))

    # Food alone, read against the goal: three things that most often spoil a diet.
    if nutrition and solid:
        observed = seven.get('nutrients') or {}
        for code, unit, test, key, title, text in (
                ('fiber', 'g', lambda v: v < 15, 'fiber_low', 'Мало клетчатки', 'в среднем {v} г в день при ориентире около 25–30 г. Овощи, бобовые и цельные крупы помогают и сытости.'),
                ('sodium', 'mg', lambda v: v > 3000, 'sodium_high', 'Много соли', 'в среднем {v} мг натрия в день при ориентире до 2000–2300 мг. Обычно это соусы, колбасы и готовая еда.'),
                ('sugar', 'g', lambda v: v > 75, 'sugar_high', 'Много сахара', 'в среднем {v} г сахара в день. Чаще всего его дают напитки и сладкое к чаю.')):
            n = observed.get(code) or {}
            value = n.get('average_on_observed_days')
            if n.get('unit') == unit and value is not None and n.get('observed_days') == seven['logged_days'] and test(value):
                cards.append(_card(key, ['food'], title, f"За {seven['logged_days']} записанных дней " + text.format(v=_number(value)), {'kind': 'open_food', 'label': 'Посмотреть питание'}, 48))

    # Gym ↔ Food: a snack before the usual training hour on a usual training weekday.
    sessions = [stamp for stamp in (_local(e['payload'].get('completed_at'), zone) for e in entities if e['source'] == 'gym' and e['payload'].get('session_complete', True)) if stamp and stamp.date() >= day - timedelta(days=42)]
    if nutrition and len(sessions) >= 4 and day.isoformat() not in days['gym'] and sum(1 for stamp in sessions if stamp.weekday() == day.weekday()) >= 2:
        usual = sorted(stamp.hour for stamp in sessions)[len(sessions) // 2]
        latest = _local(today.get('latest_meal_at'), zone)
        hungry = latest is None or (local_now - latest).total_seconds() > 4 * 3600
        if 1 <= usual - local_now.hour <= 3 and hungry:
            cards.append(_card('pre_workout_meal', ['gym', 'food'], 'Перекус перед тренировкой',
                f"В этот день недели вы обычно заканчиваете тренировку около {usual}:00, а последняя запись еды была " + ('давно' if latest else 'не сегодня') + '. Лёгкий приём за час-два до зала даст сил.',
                {'kind': 'food_log', 'label': 'Записать еду'}, 12))

    # Gym ↔ Food: water. Only for people who record it, and only from the afternoon on.
    drunk = {e['payload']['source_local_date']: e['payload']['water_ml'] for e in entities if e['source'] == 'food' and e['entity_id'].startswith('daily:')
             and e['payload'].get('source_local_date') in week and type(e['payload'].get('water_ml')) is int}
    recorded_water = [value for value in drunk.values() if value > 0]
    if len(recorded_water) >= 2 and day.isoformat() in days['gym'] and local_now.hour >= 15 and drunk.get(day.isoformat(), 0) < 1500:
        cards.append(_card('water_after_workout', ['gym', 'food'], 'После тренировки — вода',
            f"Тренировка сегодня записана, а воды в дневнике {_number(drunk.get(day.isoformat(), 0) / 1000)} л. С потом уходит жидкость — стоит добрать до конца дня. Стакан отмечается в строке «Вода» выше.", None, 14))
    elif len(recorded_water) >= 4 and sum(recorded_water) / len(recorded_water) < 1200:
        cards.append(_card('water_low', ['food'], 'Воды в записях мало',
            f"В дни, когда вы её отмечали, в среднем {_number(sum(recorded_water) / len(recorded_water) / 1000)} л. Возможно, не всё записано — стакан отмечается в одно касание в строке «Вода» выше.", None, 47))

    # Supply ↔ Gym: an intake scheduled inside the usual training window tends to be skipped.
    if supply and len(sessions) >= 4 and sum(1 for stamp in sessions if stamp.weekday() == day.weekday()) >= 2:
        usual = sorted(stamp.hour for stamp in sessions)[len(sessions) // 2]
        for entity in entities:
            payload = entity['payload']
            clock = str(payload.get('scheduled_time') or '')
            if entity['source'] == 'supply' and entity['entity_id'].startswith('supplement:') and payload.get('active') and len(clock) == 5 and clock[:2].isdecimal() and usual - 2 <= int(clock[:2]) < usual:
                cards.append(_card('slot_during_training', ['supply', 'gym'], 'Приём попадает на тренировку',
                    f"«{payload.get('name')}» запланирован на {clock}, а в этот день недели вы обычно заканчиваете тренировку около {usual}:00. Удобнее перенести приём на время после зала — так он не потеряется.",
                    {'kind': 'supply_plan', 'label': 'Расписание'}, 41))
                break

    # Food: protein packed into one meal. Counted only on days with at least two recorded meals.
    by_day = {}
    for entity in entities:
        payload = entity['payload']
        if entity['source'] == 'food' and entity['entity_id'].startswith('meal:') and payload.get('source_local_date') in week:
            by_day.setdefault(payload['source_local_date'], []).append(float((payload.get('macros') or {}).get('protein') or 0))
    full = [meals for meals in by_day.values() if len(meals) >= 2 and sum(meals) >= 40]
    packed = [meals for meals in full if max(meals) >= sum(meals) * .65]
    if nutrition and len(full) >= 4 and len(packed) * 2 > len(full):
        cards.append(_card('protein_spread', ['food'] + (['gym'] if activity else []), 'Белок собран в один приём',
            f"В {len(packed)} из {len(full)} последних дней больше половины белка пришлось на один приём пищи. Мышцам удобнее, когда он распределён: примерно 25–40 г за раз, три-четыре раза в день.",
            {'kind': 'open_food', 'label': 'Посмотреть питание'}, 46))

    # Supply ↔ Gym: a stimulant marked late in the day.
    if supply:
        late = next((e for e in entities if e['source'] == 'supply' and e['entity_id'].startswith('intake:') and e['payload'].get('status') == 'taken'
                     and e['payload'].get('source_local_date') == day.isoformat() and any(s in str(e['payload'].get('name') or '').lower() for s in STIMULANTS)
                     and (_local(e.get('occurred_at'), zone) or local_now.replace(hour=0)).hour >= 17), None)
        if late:
            cards.append(_card('late_stimulant', ['supply', 'gym'], 'Стимулятор вечером',
                f"«{late['payload'].get('name')}» отмечен после 17:00. Кофеин действует несколько часов и может помешать сну, а от сна зависит восстановление.", None, 38))
        if names and days['supply'] & set(week) and yesterday not in days['supply'] and day.isoformat() not in days['supply'] and yesterday not in set(rest_days):
            cards.append(_card('supply_missed_yesterday', ['supply'], 'Вчера добавки не отмечены',
                'Если принимали — отметьте сегодняшние, чтобы не сбить привычку. Если нет — начните с ближайшего приёма.', {'kind': 'supply_plan', 'label': 'Отметить'}, 44))

    # Gym: a week without training after an active one.
    previous = {(day - timedelta(days=offset)).isoformat() for offset in range(7, 14)}
    if activity is not None and len(days['gym'] & previous) >= 2 and not days['gym'] & set(week) and not set(rest_days) & set(week):
        cards.append(_card('gym_week_gap', ['gym'], 'Неделя без тренировок',
            f"На прошлой неделе было {len(days['gym'] & previous)}, на этой пока ни одной. Короткая тренировка лучше пропуска.", {'kind': 'gym_today', 'label': 'Открыть зал'}, 36))

    # Cold start: one concrete first step per connected product that has no records yet.
    recent = {(day - timedelta(days=offset)).isoformat() for offset in range(14)}
    if activity is not None and not days['gym'] & recent:
        cards.append(_card('first_gym', ['gym'], 'Первая тренировка', 'Запишите хотя бы одно упражнение — дальше приложение само подставит прошлые веса и посчитает неделю.', {'kind': 'gym_today', 'label': 'Открыть зал'}, 6))
    if nutrition is not None and not days['food'] & recent:
        cards.append(_card('first_food', ['food'], 'Первый приём пищи', 'Сфотографируйте тарелку или надиктуйте, что съели — калории и БЖУ посчитаются сами.', {'kind': 'food_log', 'label': 'Записать еду'}, 7))
    if supply is not None and not names:
        cards.append(_card('first_supply', ['supply'], 'Расписание добавок', 'Добавьте то, что принимаете, — появятся отметки в одно касание и проверка сочетаний с едой.', {'kind': 'supply_plan', 'label': 'Мои добавки'}, 8))

    # All three: one shared streak and one weekly line. A rest day keeps the streak.
    any_day = days['gym'] | days['food'] | days['supply'] | set(rest_days)
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
               'target_kcal': targets.get('kcal'), 'target_protein': targets.get('protein'),
               'average_water_ml': round(sum(recorded_water) / len(recorded_water)) if recorded_water else None}
    weakest = None
    scored = [(value / 7, name) for name, value in (('питание', summary['food_days']), ('добавки', summary['supply_days'])) if value is not None]
    if summary['workouts'] is not None:
        scored.append((min(summary['workouts'] / 3, 1), 'тренировки'))
    if scored and min(scored)[0] < .6:
        weakest = min(scored)[1]
    summary['headline'] = (f'На этой неделе просели {weakest}.' if weakest else 'Неделя идёт ровно по всем подключённым разделам.') if scored else None
    if streak in MILESTONES and day.isoformat() in any_day:
        cards.append(_card(f'streak_{streak}', sorted(k for k, v in days.items() if v), f'{streak} дней подряд',
            'Серия держится на любом действии в любом разделе: тренировка, запись еды или отметка добавок.', None, 4))
    cards.sort(key=lambda card: (card['priority'], card['key']))
    return {'schema_version': 1, 'day': day.isoformat(), 'cards': cards[:8], 'goal': goal if goal in GOAL_NAMES else None, 'goal_label': GOAL_NAMES.get(goal), 'streak': {'days': streak, 'today_recorded': day.isoformat() in any_day}, 'trained_today': day.isoformat() in days['gym'],
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
    from .connections import preferences
    policy = preferences(store, user_id)
    started = policy.get('last_pause_started_at')
    rest_days = {datetime.fromtimestamp(started, food_zone).date().isoformat()} if started else set()
    if policy['rest_active']:
        rest_days.add(day.isoformat())
    result = build(data, entities, now, day, food_zone, rest_days)
    result['rest_active'] = bool(policy['rest_active'])
    result['preferences_revision'] = policy['revision']
    if policy['rest_active'] or not policy['hints']:
        result['cards'] = []
    return result
