"""Temporary v1 snapshot adapters: short read-only transactions, no domain imports."""
import math
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .contracts import subject, utc
from .nutrients import CATALOG
from shared.workout_metrics import set_metrics


def zone(name):
    name = name or 'UTC'
    match = re.fullmatch(r'(?:UTC|GMT)?([+-])(0\d|1[0-4]):([0-5]\d)', name)
    if match:
        minutes = int(match[2]) * 60 + int(match[3])
        return timezone(timedelta(minutes=minutes * (1 if match[1] == '+' else -1)))
    return ZoneInfo(name)


def instant(value, source_timezone='UTC'):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone(source_timezone))
    return utc(parsed.isoformat())


def local_day_instant(value, source_timezone):
    day = date.fromisoformat(value)
    return instant(day.isoformat() + 'T00:00:00', source_timezone)


def number(value):
    result = float(value or 0)
    if not math.isfinite(result) or result < 0:
        raise ValueError('invalid_source_number')
    return result


@contextmanager
def read_only(path):
    resolved = Path(path).resolve()
    db = sqlite3.connect(resolved.as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    start = time.monotonic()
    db.set_progress_handler(lambda: int(time.monotonic() - start > 5), 10000)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def entity(entity_id, user_id, event_type, occurred_at, **payload):
    return {'entity_id': entity_id, 'user_id': subject(user_id), 'event_type': event_type, 'occurred_at': occurred_at, 'payload': payload}


def gym(db):
    users = {row['id']: dict(row) for row in db.execute('SELECT id,tg_id,tz,created_at FROM users')}
    subscriptions={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='subscriptions'").fetchone():
        for row in db.execute("SELECT user_id,expires_at FROM subscriptions WHERE status='active'"):
            expires=instant(row['expires_at']) if row['expires_at'] else None
            if expires: subscriptions[row['user_id']]=max(subscriptions.get(row['user_id'],''),expires)
    members = [{'local_id': str(i), 'user_id': subject(u['tg_id'])} for i, u in users.items()]
    entities = []
    for uid, user in users.items():
        tz = user['tz'] or 'UTC'
        zone(tz)
        entities.append(entity('profile:' + str(uid), user['tg_id'], 'profile.updated', instant(user['created_at']), timezone=tz,paid_until=subscriptions.get(uid),access_basis='native_subscription'))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='trainer_links'").fetchone():
        columns={r['name'] for r in db.execute('PRAGMA table_info(users)')}
        if 'is_trainer' in columns:
            for link in db.execute('SELECT l.*,u.is_trainer FROM trainer_links l JOIN users u ON u.id=l.trainer_user_id'):
                trainee=users.get(link['trainee_user_id']);coach=users.get(link['trainer_user_id'])
                if not trainee or not coach:continue
                entities.append(entity('profile:coach:'+str(link['id']),trainee['tg_id'],'profile.updated',instant(link['created_at']),
                    profile_kind='coach_link',link_id=str(link['id']),coach_id=subject(coach['tg_id']),
                    coach_enabled=bool(link['is_trainer']),status=link['status'],label='Тренер Gym Diary'))
    seen_sessions=set(); represented_sessions=set()
    from .workout_time import GymFreeTime, canonical_clock
    free_times = GymFreeTime(db, users)
    sets_columns={r['name'] for r in db.execute('PRAGMA table_info(sets)')}
    detailed_sets={'reps','seconds','weight_kg','user_exercise_id'}.issubset(sets_columns)
    has_details=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='workout_session_details'").fetchone())
    for row in db.execute('SELECT h.* FROM day_completion_history h JOIN users u ON u.id=h.user_id ORDER BY h.id'):
        user = users[row['user_id']]
        completed_at = instant(row['completed_at'])
        from shared.timezone_history import at as historical_zone
        tz = historical_zone(db,user['tg_id'],completed_at,user['tz'] or 'UTC')
        day = datetime.fromisoformat(completed_at.replace('Z', '+00:00')).astimezone(zone(tz)).date().isoformat()
        session_key=(row['user_id'],row['system_id'],row['day_index'],day)
        if session_key in seen_sessions: continue
        seen_sessions.add(session_key)
        session = db.execute('SELECT id FROM sessions WHERE user_id=? AND date=? AND day_index=? AND system_id IS ? ORDER BY id DESC LIMIT 1', (row['user_id'], day, row['day_index'], row['system_id'])).fetchone()
        sets_count, run_count, run_seconds = 0, 0, 0
        strength_metrics=None; recorded_strength_duration=None
        if session:
            represented_sessions.add(session['id'])
            done_ids=None
            if row['day_index']==0 and db.execute("SELECT 1 FROM sqlite_master WHERE name='session_exercises'").fetchone():
                marks=list(db.execute('SELECT user_exercise_id,is_done FROM session_exercises WHERE session_id=?',(session['id'],)))
                if marks: done_ids={m['user_exercise_id'] for m in marks if m['is_done']}
            sets_count = db.execute('SELECT count(*) FROM sets WHERE session_id=? AND COALESCE(is_warmup,0)=0', (session['id'],)).fetchone()[0]
            if detailed_sets:
                strength_metrics=set_metrics([dict(r) for r in db.execute('SELECT * FROM sets WHERE session_id=?',(session['id'],)) if done_ids is None or r['user_exercise_id'] in done_ids])
                sets_count=strength_metrics['working_sets']
            if has_details:
                details=db.execute('SELECT duration_seconds FROM workout_session_details WHERE session_id=?',(session['id'],)).fetchone()
                if details and type(details[0]) is int and 300<=details[0]<=14400: recorded_strength_duration=details[0]
            for run in db.execute('SELECT * FROM running_entries WHERE session_id=? AND COALESCE(is_draft,0)=0', (session['id'],)):
                if done_ids is not None and ('user_exercise_id' not in run.keys() or run['user_exercise_id'] not in done_ids): continue
                run_count += 1
                run_seconds += number(run['duration_sec'] if run['duration_sec'] else number(run['duration_ms']) / 1000)
        kind = 'mixed' if sets_count and run_count else 'strength' if sets_count else 'cardio' if run_count else 'unspecified'
        entities.append(entity('workout:' + str(row['id']), user['tg_id'], 'workout.completed', completed_at, completed_at=completed_at, source_local_date=day, timezone=tz, workout_type=kind, duration_seconds=recorded_strength_duration if kind=='strength' else run_seconds if kind=='cardio' else None, recorded_strength_duration_seconds=recorded_strength_duration if kind=='strength' else None, recorded_cardio_seconds=run_seconds if run_count else None, energy_kcal_range=None, strength_sets=sets_count, strength_metrics=strength_metrics,program_id=row['system_id'],day_index=row['day_index'],session_id=session['id'] if session else None, estimate_quality='recorded_session_duration' if recorded_strength_duration and kind=='strength' else 'duration_not_recorded' if sets_count or not run_count else 'recorded_cardio_duration', timestamp_basis='source_utc'))
    # Explicit exercise completion exists in both native views independently of day completion.
    # A session already represented above must never also become a second workout.
    if detailed_sets and db.execute("SELECT 1 FROM sqlite_master WHERE name='session_exercises'").fetchone():
        for session in db.execute("SELECT DISTINCT s.* FROM sessions s JOIN session_exercises se ON se.session_id=s.id WHERE se.is_done=1 ORDER BY s.id"):
            logical_key=(session['user_id'],session['system_id'],session['day_index'],session['date'])
            if session['id'] in represented_sessions or logical_key in seen_sessions or session['user_id'] not in users: continue
            user=users[session['user_id']];tz=user['tz'] or 'UTC'
            done=[dict(r) for r in db.execute("SELECT user_exercise_id,done_at FROM session_exercises WHERE session_id=? AND is_done=1",(session['id'],))]
            ids={r['user_exercise_id'] for r in done}
            rows=[dict(r) for r in db.execute('SELECT * FROM sets WHERE session_id=?',(session['id'],)) if r['user_exercise_id'] in ids]
            metrics=set_metrics(rows)
            runs=[dict(r) for r in db.execute('SELECT * FROM running_entries WHERE session_id=? AND COALESCE(is_draft,0)=0',(session['id'],))
                  if 'user_exercise_id' in r.keys() and r['user_exercise_id'] in ids]
            seconds=sum(number(r['duration_sec'] if r['duration_sec'] else number(r['duration_ms'])/1000) for r in runs)
            if not metrics['working_sets'] and not seconds: continue
            seen_sessions.add(logical_key)
            recorded=max((instant(r['done_at']) for r in done if r['done_at']),default=None)
            kind='mixed' if metrics['working_sets'] and seconds else 'strength' if metrics['working_sets'] else 'cardio'
            duration=None
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_session_durations'").fetchone():
                row=db.execute('SELECT duration_seconds FROM progressor_session_durations WHERE session_id=?',(session['id'],)).fetchone()
                if row and type(row[0]) is int and 300<=row[0]<=14400: duration=row[0]
            free=None
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_free_sessions'").fetchone():
                free=db.execute('SELECT * FROM progressor_free_sessions WHERE session_id=?',(session['id'],)).fetchone()
            finished=bool(free and free['status']=='finished')
            timing=free_times.resolve(session,free,recorded,local_day_instant(session['date'],tz))
            entities.append(entity('workout:session:'+str(session['id']),user['tg_id'],'workout.updated',timing['recorded_at'] or timing['completed_at'],
                source_local_date=session['date'],**timing,
                workout_type=kind,duration_seconds=duration if kind=='strength' else seconds if kind=='cardio' else None,
                recorded_strength_duration_seconds=duration,recorded_cardio_seconds=seconds or None,
                strength_duration_scope='explicit_strength_part' if duration else None,
                energy_kcal_range=None,strength_sets=metrics['working_sets'],strength_metrics=metrics,
                program_id=session['system_id'],day_index=session['day_index'],session_id=session['id'],
                completion_basis=free['completion_basis'] if finished else 'explicit_exercise_marks',session_complete=finished,
                completion_recorded_at=canonical_clock(free['last_finished_at']) if finished else None,
                estimate_quality='duration_not_recorded'))
    for row in db.execute("SELECT m.* FROM user_measurements m JOIN users u ON u.id=m.user_id WHERE m.metric='body_weight'"):
        user = users[row['user_id']]
        entities.append(entity('weight:' + str(row['id']), user['tg_id'], 'bodyweight.updated', instant(row['created_at']), value=number(row['value']), unit='kg', measured_at=instant(row['created_at'])))
    return {'memberships': members, 'entities': entities}


def food(db):
    # Existing Food date and naive timestamps are generated in server Europe/Moscow.
    tz = 'Europe/Moscow'
    users = {row['telegram_id']: dict(row) for row in db.execute('SELECT * FROM users')}
    members = [{'local_id': str(uid), 'user_id': subject(uid)} for uid in users]
    entities, days = [], {}
    resets={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='progressor_food_resets'").fetchone():
        resets={row['user_id']:row['revision'] for row in db.execute('SELECT * FROM progressor_food_resets')}
        if any(type(value) is not int or not 0<=value<2**63 for value in resets.values()):raise ValueError('invalid_food_reset_revision')
    trial_limit=6
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='app_settings'").fetchone():
        row=db.execute("SELECT value FROM app_settings WHERE key='trial_limit'").fetchone()
        if row and type(row[0]) is int and 1<=row[0]<=1000: trial_limit=row[0]
    nutrient_rows = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meal_nutrients'").fetchone():
        for observation in db.execute('SELECT n.* FROM meal_nutrients n JOIN meals m ON m.id=n.meal_id JOIN users u ON u.telegram_id=m.user_id WHERE n.meal_version=m.version AND n.value IS NOT NULL'):
            clean = {k: observation[k] for k in ('nutrient_code', 'unit', 'source', 'confidence', 'reference', 'revision', 'updated_at')}
            clean['value'] = number(observation['value'])
            if clean['nutrient_code'] not in CATALOG or clean['unit'] != CATALOG[clean['nutrient_code']]['unit']:
                raise ValueError('unknown_source_nutrient_or_unit')
            coverage = json.loads(observation['coverage_json'] or '{}') if 'coverage_json' in observation.keys() else {}
            observed = coverage.get('observed_components',1)
            total = coverage.get('total_components',1)
            if type(observed) is not int or type(total) is not int or not 0 <= observed <= total <= 100:
                raise ValueError('invalid_nutrient_coverage')
            clean['coverage'] = {'observed_components': observed,'total_components':total,'basis':coverage.get('basis','whole_portion_observation')}
            nutrient_rows.setdefault(observation['meal_id'], []).append(clean)
    for uid, user in users.items():
        paid=instant(user['premium_until']) if user.get('is_premium') and user.get('premium_until') else None
        trial=instant(user['trial_until']) if user.get('trial_until') and (user.get('trial_used_count') or 0)<trial_limit else None
        entities.append(entity('profile:' + str(uid), uid, 'profile.updated', instant(user['created_at'], tz), timezone=tz, timezone_basis='legacy_server_timezone',paid_until=paid,access_basis='native_subscription',native_trial_until=trial,data_reset_revision=resets.get(uid,0)))
    meal_columns={r['name'] for r in db.execute('PRAGMA table_info(meals)')}
    raw_column=',m.raw_json' if 'raw_json' in meal_columns else ''
    for row in db.execute('SELECT m.id,m.user_id,m.date,m.kcal,m.protein,m.fat,m.carbs,m.created_at,m.version'+raw_column+' FROM meals m JOIN users u ON u.telegram_id=m.user_id'):
        day = date.fromisoformat(row['date']).isoformat()
        macros = {key: number(row[key]) for key in ('kcal', 'protein', 'fat', 'carbs')}
        occurred_at = instant(row['created_at'], tz) if row['created_at'] else local_day_instant(day, tz)
        observations = sorted(nutrient_rows.get(row['id'], []), key=lambda n: n['nutrient_code'])
        display_title=''
        if raw_column:
            try:
                raw=json.loads(row['raw_json'] or '{}');raw=raw.get('analysis',raw)
                display_title=', '.join(i['name'].strip() for i in raw.get('items',[]) if isinstance(i,dict) and isinstance(i.get('name'),str))[:120]
                if not display_title and isinstance(raw.get('template_name'),str):display_title=raw['template_name'][:120]
            except (TypeError,ValueError,AttributeError):pass
        entities.append(entity('meal:' + str(row['id']), row['user_id'], 'meal.logged', occurred_at, source_local_date=day, timezone=tz, timestamp_basis='legacy_server_timezone', recorded_at=occurred_at if row['created_at'] else None, recorded_at_basis='legacy_server_timezone' if row['created_at'] else 'missing', consumed_at=None, consumed_at_basis='not_reported', source_revision=row['version'], macros=macros, nutrients=observations, estimate_quality='food_logged_estimate',display_title=display_title))
        total = days.setdefault((row['user_id'], day), {'totals': {k: 0.0 for k in macros}, 'logged_meal_count': 0, 'nutrients': {}})
        total['logged_meal_count'] += 1
        # Save-time provenance belongs to the source's existing diary day. Never
        # shift a backdated meal into today merely because it was entered today.
        if row['created_at']:
            total['latest_meal_at'] = max(total.get('latest_meal_at', ''), occurred_at)
        for key, value in macros.items():
            total['totals'][key] += value
        for observation in observations:
            code = observation['nutrient_code']
            group = total['nutrients'].setdefault(code, {'value': 0, 'unit': observation['unit'], 'observed_meals': 0, 'qualities': [], 'observed_components':0, 'assessed_components':0})
            if group['unit'] != observation['unit']:
                raise ValueError('source_nutrient_unit_conflict')
            group['value'] += observation['value']
            group['observed_meals'] += 1
            group['observed_components'] += observation['coverage']['observed_components']
            group['assessed_components'] += observation['coverage']['total_components']
            group['qualities'] = sorted(set(group['qualities']) | {observation['source'] + ':' + observation['confidence']})
    for (uid, day), total in days.items():
        complete=False
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_day_closure'").fetchone():
            closure=db.execute('SELECT meal_versions FROM progressor_day_closure WHERE user_id=? AND day=?',(uid,day)).fetchone()
            versions=[[r[0],r[1]] for r in db.execute('SELECT id,version FROM meals WHERE user_id=? AND date=? ORDER BY id',(uid,day))]
            complete=bool(closure and json.loads(closure[0])==versions and versions)
        total['day_complete']=complete
        entities.append(entity('daily:' + str(uid) + ':' + day, uid, 'daily_nutrition.updated', local_day_instant(day, tz), source_local_date=day, timezone=tz, timestamp_basis='legacy_local_day', coverage='logged_meals_only', **total))
    for row in db.execute('SELECT g.* FROM goals g JOIN users u ON u.telegram_id=g.user_id'):
        targets = {key: number(row[key]) for key in ('kcal', 'protein', 'fat', 'carbs')}
        entities.append(entity('target:' + str(row['user_id']), row['user_id'], 'nutrition_target.changed', instant(row['updated_at'], tz), targets=targets, timezone=tz, target_basis='current_personal_food_goal'))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_food_profile'").fetchone():
        from shared.nutrition_plan import normalize_profile
        for row in db.execute('SELECT * FROM progressor_food_profile WHERE sharing_enabled=1'):
            if row['user_id'] not in users: continue
            fields=normalize_profile(json.loads(row['profile_json']))
            entities.append(entity('profile:nutrition:'+str(row['user_id']),row['user_id'],'profile.updated',instant(row['updated_at']),
                profile_kind='reported_nutrition',reported_profile=fields,sharing_basis='explicit_food_profile_consent'))
    return {'memberships': members, 'entities': entities}


def _supply_intake_histories(db, users):
    """Proven owner intervals only; a current zone cannot date old intakes.

    A first before_zone is not evidence for an unbounded legacy prefix. Load
    chains once per snapshot, bound by Telegram subject rather than local id.
    Broken/missing lineage is optional unknown metadata, never a source write.
    """
    from shared.timezone_history import zone as owner_zone
    owners = {str(user['tg_user_id']): uid for uid, user in users.items()}
    chains = {uid: [] for uid in users}
    invalid = set()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_timezone_history'").fetchone():
        return {}
    try:
        rows = db.execute('SELECT user_id,changed_at,before_zone,after_zone FROM progressor_timezone_history ORDER BY user_id,changed_at')
        for row in rows:
            uid = owners.get(row['user_id'])
            if uid is None:
                continue
            stamp, before, after = row['changed_at'], row['before_zone'], row['after_zone']
            try:
                if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0 or before == after:
                    raise ValueError('invalid_owner_transition')
                owner_zone(before); owner_zone(after)
                if chains[uid] and (stamp <= chains[uid][-1][0] or before != chains[uid][-1][2]):
                    raise ValueError('broken_owner_transition')
                chains[uid].append((stamp, before, after))
            except (ValueError, TypeError, KeyError, OverflowError):
                invalid.add(uid)
    except sqlite3.Error:
        return {}
    return {uid: (tuple(row[0] for row in chain), tuple(row[2] for row in chain))
            for uid, chain in chains.items() if chain and uid not in invalid
            and chain[-1][2] == users[uid]['tz_name']}


def _supply_intake_timezone(history, occurred_at):
    """Unknown prefix/cutover second stays explicit; never default it to UTC."""
    unknown = {'timezone_basis': 'not_recorded'}
    if not history:
        return unknown
    times, zones = history
    stamp = datetime.fromisoformat(occurred_at.replace('Z', '+00:00')).timestamp()
    interval = bisect_right(times, stamp) - 1
    if interval < 0:
        return unknown
    # Native SQLite created_at records seconds. A transition inside that saved
    # second has no proven before/after order, even if its ledger has fractions.
    cutover = bisect_left(times, stamp)
    if cutover < len(times) and times[cutover] < stamp + 1:
        return unknown
    return {'timezone': zones[interval], 'timezone_basis': 'owner_transition_ledger'}


def supply(db):
    # Domain functions take Telegram ids but convert to users.id before these SQL writes.
    users = {row['id']: dict(row) for row in db.execute("SELECT * FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(deleted_at_utc,'')='' ")}
    members = [{'local_id': str(uid), 'user_id': subject(user['tg_user_id'])} for uid, user in users.items()]
    entities = []
    from .owner_policy import parse_supply_metadata
    owner_consent=parse_supply_metadata(db,users)
    intake_histories = _supply_intake_histories(db, users)
    for uid, user in users.items():
        tz = user['tz_name'] or 'UTC'
        zone(tz)
        paid=instant(user['premium_until_utc']) if user.get('premium_until_utc') else None
        trial=instant(user['starter_trial_until_utc']) if user.get('starter_trial_until_utc') else None
        entities.append(entity('profile:' + str(uid), user['tg_user_id'], 'profile.updated', instant(user['created_at']), timezone=tz, consent_given=bool(user['consent_given']),owner_consent=owner_consent[uid],paid_until=paid,access_basis='native_subscription',native_trial_until=trial))
    supplement_names = {r['id']: str(r['name_ru'] or r['name'] or '')[:160] for r in db.execute('SELECT id,name,name_ru FROM supplements')} if db.execute("SELECT 1 FROM sqlite_master WHERE name='supplements'").fetchone() else {}
    for row in db.execute('SELECT * FROM user_supplements'):
        user = users.get(row['user_id'])
        if not user:
            continue
        active = bool(row['is_active'] and row['enabled'] and not row['user_frozen'])
        dose = str(row['dose_text'] or '')[:256] if 'dose_text' in row.keys() else ''
        entities.append(entity('supplement:' + str(row['id']), user['tg_user_id'], 'supplement.started' if active else 'supplement.stopped', instant(row['created_at']), supplement_id=str(row['supplement_id']), name=supplement_names.get(row['supplement_id'],'Добавка'), active=active, reported_dose_text=dose, dose_known=False, dose_basis='unparsed_user_report; do_not_add_to_food_amounts'))
    for row in db.execute('SELECT * FROM supplement_day_state'):
        user = users.get(row['user_id'])
        if not user:
            continue
        try: doses=json.loads(row['dose_snapshot_json'] or '[]') if 'dose_snapshot_json' in row.keys() else []
        except (TypeError,ValueError): doses=[]
        doses=[str(d)[:256] for d in doses[:10]] if isinstance(doses,list) else []
        recorded = instant(row['created_at'])
        entities.append(entity('intake:' + str(row['user_id']) + ':' + str(row['supplement_id']) + ':' + row['day'], user['tg_user_id'], 'supplement.taken', recorded, source_local_date=row['day'], **_supply_intake_timezone(intake_histories.get(row['user_id']), recorded), supplement_id=str(row['supplement_id']), name=supplement_names.get(row['supplement_id'],'Добавка'), status=row['status'], reported_doses=doses, dose_basis='historical_source_snapshot; unparsed_amounts'))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='user_health_profile'").fetchone():
        for row in db.execute('SELECT * FROM user_health_profile'):
            user=users.get(row['user_id'])
            if not user or not user['consent_given']: continue
            fields={k:row[k] for k in ('sex_at_birth','birth_year','height_cm','weight_kg','diet_type','training_sessions_per_week','training_minutes_per_week')}
            if 'country_code' in row.keys() and row['country_code']:fields['country_code']=str(row['country_code'])[:2]
            entities.append(entity('profile:health:'+str(row['user_id']),user['tg_user_id'],'profile.updated',instant(row['updated_at_utc'] or row['created_at_utc']),profile_kind='reported_health',reported_profile=fields))
    for row in db.execute('SELECT id,user_id,report_date,parse_status,updated_at_utc,created_at_utc FROM lab_reports'):
        user = users.get(row['user_id'])
        if not user or not user['consent_given']:
            continue
        observations = db.execute('SELECT count(*) FROM lab_results WHERE report_id=? AND user_id=?', (row['id'], row['user_id'])).fetchone()[0]
        values=[]
        for observed in db.execute('SELECT * FROM lab_results WHERE report_id=? AND user_id=? ORDER BY id LIMIT 50',(row['id'],row['user_id'])):
            if 'analyte_code' not in observed.keys(): continue
            numeric=observed['value_num']
            numeric=float(numeric) if numeric is not None and math.isfinite(float(numeric)) else None
            values.append({'analyte_code':str(observed['analyte_code'])[:80],'name':str(observed['analyte_name'])[:160],'value':numeric,'value_text':str(observed['value_text'] or '')[:160],'unit':str(observed['unit'] or '')[:32],'measured_at':observed['measured_at'],'interpretation':'source_observation; no_core_diagnosis'})
        entities.append(entity('lab:' + str(row['id']), user['tg_user_id'], 'lab.created', instant(row['updated_at_utc'] or row['created_at_utc']), report_date=row['report_date'], confirmation_state=row['parse_status'], observation_count=observations, observations=values, observations_truncated=observations>len(values)))
    return {'memberships': members, 'entities': entities}


ADAPTERS = {'gym': gym, 'food': food, 'supply': supply}


def snapshot(source, path, max_age=None):
    if max_age is not None:
        age=time.time()-Path(path).stat().st_mtime
        if not -5<=age<=max_age:raise FileNotFoundError('source_snapshot_stale')
    with read_only(path) as db:
        return ADAPTERS[source](db)
