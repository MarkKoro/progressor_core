"""Canonical deterministic nutrition planning v1; Food contains a verbatim mirror.

Rounded Mifflin-St Jeor estimates resting energy. Activity/goal multipliers and
macro distribution are editable product defaults, not measured requirements.
No network calls, medical inference, automatic exercise eat-back or missing defaults.
"""
import math
import re

ACTIVITY = {'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55, 'high': 1.725}
GOAL = {'lose': .85, 'maintain': 1., 'gain': 1.10}
FIELDS = ('sex_at_birth', 'age_years', 'height_cm', 'weight_kg', 'activity', 'goal')


def numeric(value, low, high, integer=False):
    if isinstance(value, bool): return None
    if isinstance(value, str):
        value = value.strip().replace(',', '.')
        if not re.fullmatch(r'\d+(?:\.\d+)?', value): return None
    try: result = float(value)
    except (TypeError, ValueError): return None
    if not math.isfinite(result) or not low <= result <= high: return None
    if integer and not result.is_integer(): return None
    return int(result) if integer else result


def normalize_profile(values):
    """Only allow listed structured fields. Free-form health text is never shared."""
    out = {}
    maps = {
        'sex_at_birth': ('sex', {'М': 'male', 'Ж': 'female', 'm':'male','f':'female','male': 'male', 'female': 'female'}),
        'activity': ('activity', {'Сидячая': 'sedentary', 'Лёгкая': 'light', 'Средняя': 'moderate', 'Высокая': 'high', **{k:k for k in ACTIVITY}}),
        'goal': ('goal', {'Похудеть': 'lose', 'Поддерживать': 'maintain', 'Набрать': 'gain', **{k:k for k in GOAL}}),
        'training': ('training', {'Нет': 'none', 'Кардио': 'cardio', 'Силовые': 'strength', 'Смешанные': 'mixed', **{k:k for k in ('none','cardio','strength','mixed')}}),
        'diet_type': ('diet', {'Обычное':'ordinary','Вегетариан.':'vegetarian','Веган':'vegan','Кето/low-carb':'low_carb','Другое':'other', **{k:k for k in ('ordinary','vegetarian','vegan','low_carb','other')}}),
    }
    for field, (alias, options) in maps.items():
        value = values.get(field, values.get(alias))
        if isinstance(value, str) and value in options: out[field] = options[value]
    for field, alias, lo, hi, integer in (
        ('age_years','age',1,110,True), ('height_cm','height',100,230,False), ('weight_kg','weight',30,250,False)):
        value = numeric(values.get(field, values.get(alias)), lo, hi, integer)
        if value is not None: out[field] = value
    constraints = values.get('has_special_constraints')
    if type(constraints) is bool: out['has_special_constraints'] = constraints
    elif any(str(values.get(k) or '').strip().lower() not in ('','нет','-','нету','no') for k in ('health','note')):
        out['has_special_constraints'] = True
    return out


def calculate_plan(values):
    p = normalize_profile(values)
    interval = values.get('age_interval_years')
    if 'age_years' not in p and isinstance(interval,list) and len(interval)==2 and all(type(v) is int for v in interval) and 19<=interval[0]<=interval[1]<=78 and interval[1]-interval[0]<=1:
        p['age_years'] = sum(interval)/2
    missing = [key for key in FIELDS if key not in p]
    if missing: return {'status':'incomplete_profile', 'missing_fields':missing}
    if not 19 <= p['age_years'] <= 78 or p.get('has_special_constraints') or p.get('diet_type') in ('low_carb','other'):
        return {'status':'manual_goal_required', 'missing_fields':[]}
    bmi = p['weight_kg'] / (p['height_cm']/100)**2
    if not 18.5 <= bmi <= 40:
        return {'status':'manual_goal_required', 'missing_fields':[]}
    resting = 10*p['weight_kg'] + 6.25*p['height_cm'] - 5*p['age_years'] + (5 if p['sex_at_birth']=='male' else -161)
    maintenance = resting * ACTIVITY[p['activity']]
    kcal = int(math.floor(max(resting, maintenance * GOAL[p['goal']]) / 25 + .5) * 25)
    active = p.get('training','none') != 'none' or p['activity'] in ('moderate','high')
    protein = round(p['weight_kg'] * (1.6 if active else 1.0))
    fat = round(kcal * .30 / 9)
    carbs = round((kcal - protein*4 - fat*9) / 4)
    if carbs < 0: return {'status':'manual_goal_required','missing_fields':[]}
    return {'status':'estimated', 'targets':{'kcal':kcal,'protein':protein,'fat':fat,'carbs':carbs},
        'method':'mifflin_rounded_activity_goal.v1', 'resting_kcal':round(resting),
        'maintenance_kcal':round(maintenance), 'includes_usual_activity':True,
        'activity_factor':ACTIVITY[p['activity']], 'goal_factor':GOAL[p['goal']],
        'protein_g_per_kg':1.6 if active else 1.0,
        'age_basis':'reported_age_interval_midpoint' if 'age_years' not in normalize_profile(values) else 'reported_age',
        'uncertainty':'Ориентир по формуле. Обычная активность уже учтена; калории тренировки повторно не прибавляются. Цель можно изменить.'}
