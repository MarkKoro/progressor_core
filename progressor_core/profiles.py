"""Field-level read-only profile reconciliation of authorized fresh source entities."""
from datetime import datetime, timedelta
from shared.nutrition_plan import normalize_profile, calculate_plan


def parsed(value): return datetime.fromisoformat(value.replace('Z','+00:00'))


def resolve_profile(entities, now, at=None):
    at = at or now
    candidates = []
    for e in entities:
        stamp = parsed(e['occurred_at'])
        if not at-timedelta(days=90) <= stamp <= at: continue
        p = e['payload']; source = e['source']
        if source == 'food' and p.get('profile_kind') == 'reported_nutrition':
            candidates.append((0, stamp, e, normalize_profile(p.get('reported_profile',{}))))
        elif source == 'supply' and p.get('profile_kind') == 'reported_health':
            raw = dict(p.get('reported_profile') or {})
            normalized = normalize_profile(raw)
            birth = raw.get('birth_year')
            if type(birth) is int and 1900 <= birth <= at.year:
                normalized['birth_year']=birth
                normalized['age_interval_years'] = [at.year-birth-1, at.year-birth]
            candidates.append((1, stamp, e, normalized))
        elif source == 'gym' and e['entity_id'].startswith('weight:'):
            normalized = normalize_profile({'weight_kg':p.get('value')})
            candidates.append((2, stamp, e, normalized))
    # The current Food answers have priority; blank/invalid fields never erase a fallback.
    candidates.sort(key=lambda row:(row[0], -row[1].timestamp()))
    values = {}; provenance = {}; conflicts = []
    for _, stamp, e, fields in candidates:
        for field, value in fields.items():
            if field not in values:
                values[field] = value
                provenance[field] = {'source':e['source'], 'event_id':e['event_id'], 'observed_at':stamp.isoformat(), 'basis':'self_reported' if e['source']!='gym' else 'recorded_measurement'}
            elif field in ('weight_kg','height_cm') and abs((stamp-parsed(provenance[field]['observed_at'])).total_seconds()) <= 7*86400:
                threshold = values[field]*.10 if field=='weight_kg' else 5
                if abs(value-values[field]) > threshold:
                    conflicts.append({'field':field,'sources':[provenance[field]['source'],e['source']], 'reason':'recent_values_disagree'})
            elif field=='sex_at_birth' and values[field]!=value:
                conflicts.append({'field':field,'sources':[provenance[field]['source'],e['source']], 'reason':'profile_values_disagree'})
    if 'age_years' in values and 'age_interval_years' in values:
        lo,hi=values['age_interval_years']
        if not lo-1<=values['age_years']<=hi+1:
            conflicts.append({'field':'age_years','sources':[provenance['age_years']['source'],provenance['age_interval_years']['source']],'reason':'reported_age_and_birth_year_disagree'})
    if 'age_years' in values:
        observed = parsed(provenance['age_years']['observed_at'])
        # An age entered without a birthday is an interval after its observation day.
        values['age_interval_years'] = [values['age_years'],values['age_years'] + int(at.date()>observed.date())]
        provenance['age_interval_years'] = provenance['age_years']
    plan = calculate_plan(values) if not conflicts else {'status':'conflicting_profile','missing_fields':[]}
    return {'values':values,'provenance':provenance,'conflicts':conflicts,'nutrition_plan_preview':plan,
        'priority':'food_explicit_then_consented_supply_then_gym_missing_fields',
        'uncertainty':'Поля не перезаписывают исходные профили. При расхождении недавних значений автоматический расчёт приостановлен.'}
