"""Home-screen links are deterministic, read only the kept sources and make no clinical claim."""
import unittest
from datetime import date, datetime, timezone, timedelta
from progressor_core.day_links import build

ZONE = timezone(timedelta(hours=3))
DAY = date(2026, 11, 15)
NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def nutrient(value, unit, days=6):
    return {'unit': unit, 'average_on_observed_days': value, 'observed_days': days}


def data(nutrients=None, supplements=(), fat=40, protein_left=0, workouts=0, kcal=2200, logged=6):
    return {'nutrition': {'history': {'7': {'logged_days': logged, 'logged_meals': 18, 'nutrients': nutrients or {}, 'averages_on_logged_days': {'kcal': kcal, 'protein': 120}}},
                          'targets': {'kcal': 2400, 'protein': 150},
                          'today': {'logged_meal_count': 2, 'totals': {'fat': fat}, 'remaining_to_personal_goal': {'protein': protein_left}}},
            'supply': {'active_supplements': [{'name': n} for n in supplements]},
            'activity': {'completed_workout_count': workouts}}


def keys(result):
    return [card['key'] for card in result['cards']]


class DayLinks(unittest.TestCase):
    def test_food_covering_a_taken_supplement_is_reported_without_advice_to_stop(self):
        result = build(data({'vitamin_c': nutrient(140, 'mg')}, ['Витамин C 500']), [], NOW, DAY, ZONE)
        self.assertEqual(keys(result), ['covered_vitamin_c'])
        text = result['cards'][0]['text']
        self.assertIn('не анализ', text)
        for word in ('отмените', 'прекратите', 'дефицит'):
            self.assertNotIn(word, text)

    def test_low_nutrient_only_without_a_matching_supplement_and_with_enough_days(self):
        low = {'magnesium': nutrient(150, 'mg')}
        self.assertEqual(keys(build(data(low), [], NOW, DAY, ZONE)), ['low_magnesium'])
        self.assertEqual(keys(build(data(low, ['Магний B6']), [], NOW, DAY, ZONE)), [])
        self.assertEqual(keys(build(data(low, logged=3), [], NOW, DAY, ZONE)), [])

    def test_wrong_unit_or_partly_observed_nutrient_is_ignored(self):
        self.assertEqual(keys(build(data({'iron': nutrient(2, 'ug')}), [], NOW, DAY, ZONE)), [])
        self.assertEqual(keys(build(data({'iron': nutrient(2, 'mg', days=4)}), [], NOW, DAY, ZONE)), [])

    def test_fat_soluble_conflict_protein_and_creatine_rules(self):
        intakes = [{'source': 'supply', 'entity_id': f'intake:1:9:2026-11-{d}', 'payload': {'status': 'taken', 'source_local_date': f'2026-11-{d}', 'name': 'Креатин'}} for d in (14, 15)]
        result = build(data(supplements=['Витамин D3', 'Железо', 'Кальций', 'Креатин'], fat=4, protein_left=38, workouts=1), intakes, NOW, DAY, ZONE)
        self.assertEqual(keys(result), ['protein_after_workout', 'fat_soluble', 'conflict_желез_кальци', 'creatine_daily'])
        self.assertIn('2 из 7', result['cards'][-1]['text'])

    def test_training_while_eating_below_goal_needs_three_workouts(self):
        def workouts(count):
            return [{'source': 'gym', 'entity_id': f'w{i}', 'payload': {'completed_at': f'2026-11-{10 + i}T10:00:00Z'}} for i in range(count)]
        self.assertIn('training_under_goal', keys(build(data(kcal=1800), workouts(3), NOW, DAY, ZONE)))
        self.assertNotIn('training_under_goal', keys(build(data(kcal=1800), workouts(2), NOW, DAY, ZONE)))
        self.assertNotIn('training_under_goal', keys(build(data(kcal=2300), workouts(3), NOW, DAY, ZONE)))

    def test_shared_streak_counts_any_source_and_survives_until_today_is_recorded(self):
        def food(day):
            return {'source': 'food', 'entity_id': 'daily:' + day, 'payload': {'source_local_date': day, 'logged_meal_count': 1}}
        entities = [food('2026-11-12'), {'source': 'gym', 'entity_id': 'w', 'payload': {'completed_at': '2026-11-13T10:00:00Z'}},
                    {'source': 'supply', 'entity_id': 'intake:1:1:2026-11-14', 'payload': {'status': 'taken', 'source_local_date': '2026-11-14', 'name': 'D3'}}]
        result = build(data(), entities, NOW, DAY, ZONE)
        self.assertEqual(result['streak'], {'days': 3, 'today_recorded': False})
        self.assertEqual(build(data(), entities + [food('2026-11-15')], NOW, DAY, ZONE)['streak'], {'days': 4, 'today_recorded': True})
        self.assertEqual(build(data(), [food('2026-11-10')], NOW, DAY, ZONE)['streak']['days'], 0)

    def test_absent_sources_stay_silent_and_week_marks_them_unknown(self):
        result = build({'nutrition': None, 'supply': None, 'activity': None}, [], NOW, DAY, ZONE)
        self.assertEqual(result['cards'], [])
        self.assertEqual((result['week']['workouts'], result['week']['food_days'], result['week']['supply_days'], result['week']['headline']), (None, None, None, None))

    def test_week_names_the_weakest_connected_area(self):
        result = build(data(), [{'source': 'food', 'entity_id': 'daily:2026-11-15', 'payload': {'source_local_date': '2026-11-15', 'logged_meal_count': 2}}], NOW, DAY, ZONE)
        self.assertEqual(result['week']['food_days'], 1)
        self.assertIn(result['week']['headline'], ('На этой неделе просели добавки.', 'На этой неделе просели тренировки.'))


if __name__ == '__main__':
    unittest.main()
