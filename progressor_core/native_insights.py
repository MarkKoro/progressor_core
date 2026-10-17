"""Deterministic, source-gated, bounded contextual guidance. Never calls an LLM."""
from datetime import datetime, timedelta, timezone
from shared.workout_metrics import compare_load, energy_estimate
from .profiles import resolve_profile
from .journey import workout_follow_up
from shared.food_sources import examples, macro_examples


def parsed(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def enrich_workouts(entities, now, *, selected_ids=None):
    workouts=[e for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:')]
    selected=workouts if selected_ids is None else [e for e in workouts if e['entity_id'] in selected_ids]
    # Birth year gives an age interval; reject boundary cases rather than guessing.
    for item in selected:
        p=item['payload']; completed=parsed(p['completed_at'])
        candidates=[e for e in workouts if e['entity_id']!=item['entity_id']
                    and completed-timedelta(days=90)<=parsed(e['payload']['completed_at'])<completed
                    and e['payload'].get('program_id')==p.get('program_id') and e['payload'].get('day_index')==p.get('day_index')]
        candidates.sort(key=lambda e:e['payload']['completed_at'],reverse=True)
        p['load_comparison']=compare_load(p.get('strength_metrics') or {},[e['payload'].get('strength_metrics') or {} for e in candidates[:8]])
        resolved=resolve_profile(entities,now,at=completed);values=resolved['values']
        interval=values.get('age_interval_years')
        age=interval[0] if interval and 19<=interval[0]<=interval[1]<=59 else None
        kg=values.get('weight_kg') if not resolved['conflicts'] else None
        strength_duration=p.get('workout_type')=='strength' or p.get('strength_duration_scope')=='explicit_strength_part'
        estimate=energy_estimate(p.get('recorded_strength_duration_seconds'),kg,age_years=age) if strength_duration else None
        if estimate:
            estimate.pop('age_years',None)
            estimate['reported_age_interval_years']=interval
            estimate['provenance']=[{'source':'gym','event_id':item['event_id'],'basis':'user_recorded_duration'},
                {**resolved['provenance']['weight_kg'],'basis':'recent_body_weight'},
                {**resolved['provenance'].get('age_interval_years',resolved['provenance'].get('age_years',{})),'basis':'reported_adult_age_range'}]
        p['energy_estimate']=estimate
        p['energy_kcal_range']=estimate['gross_kcal_range'] if estimate else None
    return selected


def native_hints(data, entities, now, day, *, food_preferences=None):
    hints=[]; activity=data.get('activity'); nutrition=data.get('nutrition'); supply=data.get('supply')
    seven=(nutrition or {}).get('history',{}).get('7',{}) if (nutrition or {}).get('history') else {}
    targets=(nutrition or {}).get('targets') or {}
    source=lambda name:data['sources'].get(name,{}).get('status')=='ok'
    base={'rule_version':1,'delivery':'inline_only','dismiss_days':7}
    recorded_today=activity.get('workouts',[]) if activity and source('gym') else []
    today=[w for w in recorded_today if w.get('session_complete',True)]
    follow_up=workout_follow_up(data,now)
    if today and follow_up not in ('food_day_confirmed','food_recorded_after_workout'):
        working_sets=sum((w.get('strength_metrics') or {}).get('working_sets',w.get('strength_sets',0)) for w in recorded_today)
        reps=sum((w.get('strength_metrics') or {}).get('repetitions',0) for w in recorded_today)
        increased=any(w.get('load_comparison',{}).get('status')=='higher_recorded_load' for w in today)
        decreased=not increased and any(w.get('load_comparison',{}).get('status')=='lower_recorded_load' for w in today)
        title='Сегодня больше нагрузки' if increased else 'Сегодня меньше записанной нагрузки' if decreased else 'Тренировка учтена'
        partial=len(recorded_today)!=len(today)
        message=f"Сегодня учтено тренировочных записей — {len(recorded_today)}; завершено — {len(today)}." if partial else f"Сегодня завершено занятий — {len(today)}."
        if working_sets: message+=f" Рабочих подходов — {working_sets}"+(f", повторений — {reps}." if reps else '.')
        if increased: message+=' Объём тех же упражнений выше обычного.'
        elif decreased:message+=' Объём тех же упражнений ниже обычного. Это не измерение расхода энергии.'
        remaining=(nutrition or {}).get('today',{}).get('remaining_to_personal_goal')
        if source('food') and remaining:
            message+=f" До вашей цели в журнале: {remaining['kcal']:g} ккал, Б {remaining['protein']:g} г, Ж {remaining['fat']:g} г, У {remaining['carbs']:g} г."
        if source('food') and seven.get('logged_days',0)>=3:
            means=seven.get('averages_on_logged_days',{})
            if targets.get('protein') and means.get('protein') is not None and means['protein']<targets['protein']*.8:
                message+=f" За последнюю неделю записано дней — {seven['logged_days']}. Белок в среднем по этим дням — {means['protein']:g} г/день при вашей цели {targets['protein']:g} г."
            elif targets.get('kcal') and means.get('kcal') is not None and means['kcal']<targets['kcal']*.8:
                message+=f" За последнюю неделю записано дней — {seven['logged_days']}. В среднем по этим дням: {means['kcal']:g} ккал при вашей цели {targets['kcal']:g} ккал."
        estimates=[w['energy_estimate'] for w in today if w.get('energy_estimate')]
        if len(estimates)==len(recorded_today):
            lo=sum(e['net_above_rest_kcal_range'][0] for e in estimates); hi=sum(e['net_above_rest_kcal_range'][1] for e in estimates)
            message+=f" Сверх покоя примерно {lo}–{hi} ккал."
        message+=' Цель питания не менялась.'
        hints.append({**base,'key':'workout_today.v1','targets':['food']+(['gym'] if source('food') else []),'priority':10,'title':title,'message':message,
                      'action':{'kind':'food_log','label':'Проверить питание'},'basis':activity['provenance']+(seven.get('provenance',[]) if source('food') and seven.get('logged_days',0)>=3 else []),
                      'details':'Проверьте, все ли блюда внесены. Обычная активность уже может входить в вашу цель питания. Оценка зависит от длительности, веса, темпа и пауз; это диапазон модели, не измерение. Без записанной длительности/подходящего профиля калории не вычисляются. Средние по питанию учитывают записанные дни за последнюю завершённую неделю. Цель Food автоматически не меняется.'})
    protein=seven.get('averages_on_logged_days',{}).get('protein'); goal=targets.get('protein')
    low_protein=source('food') and seven.get('logged_days',0)>=3 and goal and protein is not None and protein<goal*.8
    training=[e for e in entities if e['source']=='gym' and e['entity_id'].startswith('workout:')
              and now-timedelta(days=14)<=parsed(e['payload']['completed_at'])<=now] if source('gym') else []
    if low_protein:
        message=f"За последнюю неделю записано дней — {seven['logged_days']}. Белок в среднем по этим дням — {protein:g} г/день при вашей цели {goal:g} г."
        if len(training)>=3: message+=f" Тренировок за 14 дней — {len(training)}."
        message+=' Проверьте полноту дневника и цель.'
        foods=macro_examples('protein',food_preferences)
        if foods: message+=' Возможные пищевые источники: '+ '; '.join(foods)+'.'
        hints.append({**base,'key':'logged_protein.v2','targets':['supply','gym']+(['food'] if len(training)>=3 else []),'priority':20,'title':'Белок в вашем журнале',
                      'message':message,'action':{'kind':'open_food','label':'Посмотреть питание'},
                      'basis':seven.get('provenance',[])+([{'source':'gym','event_id':e['event_id'],'occurred_at':e['payload']['completed_at']} for e in training] if len(training)>=3 else []),'details':'80% личной цели — правило показа подсказки, не медицинский порог. По неполному дневнику нельзя определить недоедание или назначить добавку.'})
    # Intentionally conservative source-review rule. This is NOT personal RDA or
    # a clinical deficiency model. All logged days and most components must be known.
    if source('food') and seven.get('logged_days',0)>=5 and seven.get('logged_meals',0)>=10:
        for code,name,limit,unit in (
            ('iron','железа',4.0,'mg'),
            ('vitamin_b12','витамина B12',1.2,'ug')):
            n=seven.get('nutrients',{}).get(code,{})
            if (n.get('unit')!=unit or n.get('observed_days')!=seven['logged_days']
                or n.get('observed_meals',0)<seven['logged_meals']*.8
                or n.get('observed_components',0)<n.get('assessed_components',1)*.8
                or n.get('average_on_observed_days',limit)>=limit): continue
            # Existing stack amounts are unparsed. Never claim missing total intake.
            terms=('желез','iron','ferrous') if code=='iron' else ('b12','b-12','в12','cobalamin','кобаламин')
            already=any(any(t in p.get('name','').lower() for t in terms) for p in (supply or {}).get('active_supplements',[]))
            atlas=examples(code,food_preferences)
            foods=('Под ваши предпочтения: '+ '; '.join(i['name'] for i in atlas['items'][:3])+'.') if atlas['items'] else 'Под ваши исключения подтверждённых пищевых примеров пока нет; новый источник не выдумываем.'
            hints.append({**base,'key':'food_sources_'+code+'.v1','targets':['food']+(['supply'] if supply and source('supply') else []),'priority':15,
                'title':'Источники '+name+' в рационе',
                'message':f"За {seven['logged_days']} дней в записанных блюдах оценка {name} невысокая. {foods}"+(' В Supply уже есть соответствующая добавка; её дозу мы не складываем с едой.' if already else ''),
                'action':{'kind':'open_food','label':'Проверить блюда'},
                'secondary_action':None if already or not supply else {'kind':'supply_catalog','targets':['supply'],'query':'железо' if code=='iron' else 'B12','label':'Уже принимаю — добавить'},
                'basis':seven.get('provenance',[]),'details':f"Средняя оценка на записанных днях: {n['average_on_observed_days']:g} {'мг' if unit=='mg' else 'мкг'}. Пропущенные блюда неизвестны; состав пищи оценён приблизительно. Подсказка не устанавливает дефицит организма. Железо не следует начинать по дневнику без оценки необходимости; дозы здесь не назначаются. Кнопка предназначена для записи уже выбранного приёма."})
    return sorted(hints,key=lambda h:(h['priority'],h['key']))
