"""Factual completion of a cross-product journey, without inferring food needs."""
from datetime import datetime


def workout_follow_up(data, now):
    activity = data.get('activity') or {}
    records = activity.get('workouts') or []
    completed = [w for w in records if w.get('session_complete', True)]
    if not completed:
        return 'training_in_progress' if records else 'no_completed_workout'
    if data.get('sources', {}).get('food', {}).get('status') != 'ok':
        return 'food_unavailable'
    today = (data.get('nutrition') or {}).get('today') or {}
    if today.get('day_complete'):
        return 'food_day_confirmed'
    value = today.get('latest_meal_at')
    if value:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        last_workout = max(datetime.fromisoformat(w['completed_at'].replace('Z', '+00:00')) for w in completed)
        if last_workout <= stamp <= now:
            return 'food_recorded_after_workout'
    return 'food_review_available'
