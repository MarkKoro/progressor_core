"""Pure owner-side session metrics v1; no AI and no kcal per repetition fiction."""
import math
from statistics import median

MODEL = 'compendium_strength_2024.v1'
SOURCE = 'https://pacompendium.com/conditioning-exercise/'


def energy_estimate(duration_seconds, weight_kg, *, age_years=None):
    # Adult compendium. Age is required; a missing age never silently means adult.
    if not isinstance(age_years,(int,float)) or not 19<=age_years<=59: return None
    if isinstance(duration_seconds,bool) or isinstance(weight_kg,bool): return None
    if not isinstance(duration_seconds,(int,float)) or not isinstance(weight_kg,(int,float)): return None
    if not math.isfinite(duration_seconds) or not math.isfinite(weight_kg): return None
    if not 300<=duration_seconds<=14400 or not 30<=weight_kg<=250: return None
    # Standard MET approximation: kcal ~= MET * kg * hours, not an individual CI.
    base=weight_kg*duration_seconds/3600
    return {'model':MODEL,'source':SOURCE,'met_range':[3.5,6.0],
            'gross_kcal_range':[round(3.5*base),round(6*base)],
            'net_above_rest_kcal_range':[round(2.5*base),round(5*base)],
            'weight_kg':weight_kg,'duration_seconds':duration_seconds,'age_years':age_years,
            'quality':'population_model_range_not_confidence_interval',
            'uncertainty':'Приблизительно: паузы, темп и интенсивность меняют расход. Диапазон не является измерением или доверительным интервалом.'}


def set_metrics(rows):
    exercises={}
    for row in rows:
        if row.get('is_warmup'): continue
        reps=max(0,int(row.get('reps') or 0)); kg=max(0,float(row.get('weight_kg') or 0))
        seconds=max(0,int(row.get('seconds') or 0))
        if not math.isfinite(kg): continue
        # Empty drafts are not work. Static holds are recorded separately.
        if not reps and not seconds: continue
        key=str(row['user_exercise_id'])
        item=exercises.setdefault(key,{'sets':0,'reps':0,'external_volume_kg':0.0,'hold_seconds':0})
        item['sets']+=1;item['reps']+=reps;item['external_volume_kg']+=kg*reps;item['hold_seconds']+=seconds
    return {'schema_version':1,'working_sets':sum(x['sets'] for x in exercises.values()),
            'repetitions':sum(x['reps'] for x in exercises.values()),
            'external_volume_kg':round(sum(x['external_volume_kg'] for x in exercises.values()),2),
            'exercises':exercises,'basis':'recorded_non_warmup_sets; external_volume_is_not_energy'}


def compare_load(current, previous):
    """Compare the same recorded exercises and modality, not different muscle days."""
    ratios=[]
    current_ex=current.get('exercises') or {}
    for old in previous[:8]:
        prior=old.get('exercises') or {}
        if set(current_ex)!=set(prior) or not current_ex: continue
        # Same exercise ids do not imply comparable weighted/bodyweight/hold work.
        modalities=lambda items:{k:('weighted' if v.get('external_volume_kg',0)>0 else 'reps' if v.get('reps',0)>0 else 'hold') for k,v in items.items()}
        if modalities(current_ex)!=modalities(prior): continue
        measures={'weighted':'external_volume_kg','reps':'reps','hold':'hold_seconds'}
        per_ex=[]
        for key,mode in modalities(current_ex).items():
            field=measures[mode]; denominator=prior[key].get(field,0)
            if denominator<=0: break
            per_ex.append(current_ex[key][field]/denominator)
        if len(per_ex)==len(current_ex): ratios.append(median(per_ex))
    if len(ratios)<3: return {'status':'insufficient_comparable_history','comparable_sessions':len(ratios)}
    ratio=median(ratios)
    return {'status':'higher_recorded_load' if ratio>=1.2 else 'usual_recorded_load',
            'comparison_ratio':round(ratio,3),'comparable_sessions':len(ratios),
            'method':'median_exercise_ratios_against_last_8_same_day_program_sessions.v1',
            'threshold_basis':'20_percent_display_rule_not_physiological_threshold',
            'uncertainty':'Объём записанных упражнений не измеряет усталость или расход калорий.'}
