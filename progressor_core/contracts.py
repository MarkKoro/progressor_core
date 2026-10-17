import hashlib
import json
import math
from datetime import date
from datetime import datetime, timezone
from .nutrients import CATALOG

SOURCES = ('gym', 'food', 'supply')
TYPES = {
    'gym': {'workout.completed', 'workout.updated', 'workout.deleted', 'bodyweight.updated', 'profile.updated', 'goal.updated'},
    'food': {'meal.logged', 'meal.updated', 'meal.deleted', 'daily_nutrition.updated', 'nutrition_target.changed', 'profile.updated', 'goal.updated'},
    'supply': {'supplement.taken', 'supplement.started', 'supplement.stopped', 'lab.created', 'lab.updated', 'profile.updated', 'goal.updated'},
}
for _source in TYPES: TYPES[_source].add('entity.deleted')


def subject(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or value.startswith('0') or not 0 < int(value) < 2**63:
        raise ValueError('invalid_subject')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc(value):
    if not isinstance(value,str):
        raise ValueError('invalid_timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def nonnegative(value, nullable=False, integer=False):
    if value is None and nullable: return
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not 0 <= value < 2**63:
        raise ValueError('invalid_payload_number')


def macros(value):
    if not isinstance(value,dict): raise ValueError('invalid_macros')
    for key in ('kcal','protein','fat','carbs'): nonnegative(value.get(key))


def nutrient(value, code=None):
    if not isinstance(value,dict): raise ValueError('invalid_nutrient')
    code = code or value.get('nutrient_code')
    if code not in CATALOG or value.get('unit') != CATALOG[code]['unit']: raise ValueError('invalid_nutrient_unit')
    nonnegative(value.get('value'))


def validate_payload(kind,payload):
    if kind == 'entity.deleted':
        if payload.get('deleted') is not True: raise ValueError('invalid_tombstone')
        return
    prefix={'workout':'workout:','bodyweight':'weight:','meal':'meal:','daily_nutrition':'daily:','nutrition_target':'target:','supplement':'intake:' if kind=='supplement.taken' else 'supplement:','lab':'lab:','profile':'profile:','goal':'goal:'}[kind.split('.')[0]]
    if not payload['entity_id'].startswith(prefix): raise ValueError('invalid_entity_type')
    if kind.endswith(('.deleted','.stopped')): return
    if 'source_local_date' in payload: date.fromisoformat(payload['source_local_date'])
    if 'timezone' in payload:
        from .adapters import zone
        zone(payload['timezone'])
    if kind.startswith('workout.'):
        utc(payload.get('completed_at'))
        if payload.get('workout_type') not in ('strength','cardio','mixed','unspecified'): raise ValueError('invalid_workout_type')
        nonnegative(payload.get('duration_seconds'),nullable=True)
        nonnegative(payload.get('strength_sets'),integer=True)
        metrics=payload.get('strength_metrics')
        if metrics is not None:
            if not isinstance(metrics,dict) or metrics.get('schema_version')!=1: raise ValueError('invalid_strength_metrics')
            for field in ('working_sets','repetitions'): nonnegative(metrics.get(field),integer=True)
            nonnegative(metrics.get('external_volume_kg'))
            exercises=metrics.get('exercises')
            if not isinstance(exercises,dict) or len(exercises)>100: raise ValueError('invalid_exercise_metrics')
            for key,values in exercises.items():
                if not isinstance(key,str) or not key.isdecimal() or not isinstance(values,dict): raise ValueError('invalid_exercise_metrics')
                for field in ('sets','reps','hold_seconds'): nonnegative(values.get(field),integer=True)
                nonnegative(values.get('external_volume_kg'))
        if payload.get('recorded_strength_duration_seconds') is not None:
            value=payload['recorded_strength_duration_seconds'];nonnegative(value,integer=True)
            if not 300<=value<=14400: raise ValueError('invalid_strength_duration')
        energy=payload.get('energy_kcal_range')
        if energy is not None:
            if not isinstance(energy,list) or len(energy)!=2: raise ValueError('invalid_energy_range')
            for value in energy: nonnegative(value)
            if energy[0]>energy[1]: raise ValueError('invalid_energy_range')
    elif kind.startswith('bodyweight.'):
        nonnegative(payload.get('value'))
        if payload.get('unit')!='kg': raise ValueError('invalid_weight_unit')
        utc(payload.get('measured_at'))
    elif kind.startswith('meal.'):
        macros(payload.get('macros'))
        rows=payload.get('nutrients',[])
        if not isinstance(rows,list) or len(rows)>len(CATALOG): raise ValueError('invalid_nutrients')
        for row in rows: nutrient(row)
    elif kind=='daily_nutrition.updated':
        date.fromisoformat(payload['source_local_date'])
        if payload.get('latest_meal_at') is not None: utc(payload['latest_meal_at'])
        macros(payload.get('totals')); nonnegative(payload.get('logged_meal_count'),integer=True)
        rows=payload.get('nutrients',{})
        if not isinstance(rows,dict) or len(rows)>len(CATALOG): raise ValueError('invalid_nutrients')
        for code,row in rows.items():
            nutrient(row,code); nonnegative(row.get('observed_meals'),integer=True)
            if row['observed_meals']>payload['logged_meal_count']: raise ValueError('invalid_nutrient_coverage')
            qualities=row.get('qualities')
            if not isinstance(qualities,list) or any(not isinstance(q,str) or len(q)>64 for q in qualities): raise ValueError('invalid_nutrient_quality')
    elif kind=='nutrition_target.changed': macros(payload.get('targets'))
    elif kind=='supplement.started':
        if type(payload.get('active')) is not bool: raise ValueError('invalid_supplement_state')
    elif kind=='supplement.taken':
        if payload.get('status') not in ('taken','skipped','none'): raise ValueError('invalid_intake_state')
    elif kind.startswith('lab.'):
        nonnegative(payload.get('observation_count'),integer=True)


def validate(event):
    if not isinstance(event, dict) or len(canonical(event).encode()) > 32768:
        raise ValueError('invalid_envelope')
    if event.get('source') not in SOURCES or event.get('event_type') not in TYPES[event['source']]:
        raise ValueError('invalid_source_or_type')
    if type(event.get('schema_version')) is not int or event['schema_version'] != 1:
        raise ValueError('unsupported_schema_version')
    for key in ('event_id', 'correlation_id'):
        if not isinstance(event.get(key), str) or not 1 <= len(event[key]) <= 128:
            raise ValueError('invalid_' + key)
    if not isinstance(event.get('user_id'), str):
        raise ValueError('subject_must_be_string')
    subject(event['user_id'])
    utc(event['occurred_at'])
    payload = event.get('payload')
    if not isinstance(payload, dict) or not isinstance(payload.get('entity_id'), str) or not 1 <= len(payload['entity_id']) <= 128:
        raise ValueError('invalid_entity')
    if type(payload.get('revision')) is not int or not 0 < payload['revision'] < 2**63:
        raise ValueError('invalid_revision')
    validate_payload(event['event_type'],payload)
    return {k: event[k] for k in ('event_id', 'event_type', 'schema_version', 'source', 'user_id', 'occurred_at', 'correlation_id', 'payload')}
