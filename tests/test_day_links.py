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


def keys(result, starters=False):
    return [card['key'] for card in result['cards'] if starters or not card['key'].startswith(('first_', 'streak_', 'supply_missed'))]


class DayLinks(unittest.TestCase):
    def test_food_covering_a_taken_supplement_is_reported_without_advice_to_stop(self):
        result = build(data({'vitamin_c': nutrient(140, 'mg')}, ['Витамин C 500']), [], NOW, DAY, ZONE)
        self.assertEqual(keys(result), ['covered_vitamin_c'])
        text = next(card['text'] for card in result['cards'] if card['key'] == 'covered_vitamin_c')
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

    def test_cold_start_offers_one_first_step_per_connected_empty_product(self):
        result = build(data(), [], NOW, DAY, ZONE)
        self.assertEqual(keys(result, starters=True)[:3], ['first_gym', 'first_food', 'first_supply'])
        recorded = [{'source': 'food', 'entity_id': 'daily:2026-11-14', 'payload': {'source_local_date': '2026-11-14', 'logged_meal_count': 1}}]
        self.assertNotIn('first_food', keys(build(data(supplements=['D3']), recorded, NOW, DAY, ZONE), starters=True))
        self.assertNotIn('first_supply', keys(build(data(supplements=['D3']), recorded, NOW, DAY, ZONE), starters=True))

    def test_goal_changes_how_the_same_calories_read(self):
        def with_goal(goal, kcal):
            d = data(kcal=kcal)
            d['profile'] = {'values': {'goal': goal}}
            return build(d, [], NOW, DAY, ZONE)
        self.assertIn('goal_gain_under', keys(with_goal('gain', 2000)))
        self.assertIn('goal_lose_over', keys(with_goal('lose', 2800)))
        self.assertEqual(keys(with_goal('maintain', 2000)), [])
        self.assertEqual((with_goal('gain', 2400)['goal'], with_goal('gain', 2400)['goal_label']), ('gain', 'набрать'))
        self.assertIsNone(with_goal('nonsense', 2400)['goal'])

    def test_partners_powder_and_diet_quality(self):
        nutrients = {'vitamin_c': nutrient(20, 'mg'), 'vitamin_d': nutrient(3, 'ug'), 'fiber': nutrient(9, 'g'), 'sodium': nutrient(3600, 'mg'), 'sugar': nutrient(40, 'g')}
        d = data(nutrients, ['Железо хелат', 'Кальций цитрат', 'Сывороточный протеин'])
        d['nutrition']['history']['7']['averages_on_logged_days']['protein'] = 90
        found = keys(build(d, [], NOW, DAY, ZONE))
        for key in ('partner_iron_c', 'partner_calcium_d', 'powder_not_logged'):
            self.assertIn(key, found)
        self.assertLessEqual(len(build(d, [], NOW, DAY, ZONE)['cards']), 8)
        quality = keys(build(data({'fiber': nutrient(9, 'g'), 'sodium': nutrient(3600, 'mg'), 'sugar': nutrient(40, 'g')}, ['D3']), [], NOW, DAY, ZONE))
        self.assertEqual(quality, ['fiber_low', 'sodium_high'])

    def test_snack_before_the_usual_training_hour_only_on_a_usual_weekday(self):
        sunday_evenings = [{'source': 'gym', 'entity_id': f'w{i}', 'payload': {'completed_at': f'2026-{m}T15:30:00Z'}} for i, m in enumerate(('10-18', '10-25', '11-01', '11-08'))]
        afternoon = datetime(2026, 11, 15, 13, tzinfo=timezone.utc)  # 16:00 local, usual end 18:00
        self.assertIn('pre_workout_meal', keys(build(data(), sunday_evenings, afternoon, DAY, ZONE)))
        self.assertNotIn('pre_workout_meal', keys(build(data(), sunday_evenings, NOW.replace(hour=5), DAY, ZONE)))
        mondays = [{'source': 'gym', 'entity_id': f'm{i}', 'payload': {'completed_at': f'2026-{m}T15:30:00Z'}} for i, m in enumerate(('10-19', '10-26', '11-02', '11-09'))]
        self.assertNotIn('pre_workout_meal', keys(build(data(), mondays, afternoon, DAY, ZONE)))

    def test_late_stimulant_week_gap_and_rest_day_keeping_the_streak(self):
        evening = {'source': 'supply', 'entity_id': 'intake:1:3:2026-11-15', 'occurred_at': '2026-11-15T17:30:00Z', 'payload': {'status': 'taken', 'source_local_date': '2026-11-15', 'name': 'Предтрен'}}
        self.assertIn('late_stimulant', keys(build(data(supplements=['Предтрен']), [evening], NOW, DAY, ZONE)))
        morning = {**evening, 'occurred_at': '2026-11-15T06:00:00Z'}
        self.assertNotIn('late_stimulant', keys(build(data(supplements=['Предтрен']), [morning], NOW, DAY, ZONE)))
        last_week = [{'source': 'gym', 'entity_id': f'g{i}', 'payload': {'completed_at': f'2026-11-0{d}T10:00:00Z'}} for i, d in enumerate((3, 5))]
        self.assertIn('gym_week_gap', keys(build(data(), last_week, NOW, DAY, ZONE)))
        self.assertNotIn('gym_week_gap', keys(build(data(), last_week, NOW, DAY, ZONE, rest_days={'2026-11-14'})))
        food = lambda day: {'source': 'food', 'entity_id': 'daily:' + day, 'payload': {'source_local_date': day, 'logged_meal_count': 1}}
        self.assertEqual(build(data(), [food('2026-11-13'), food('2026-11-15')], NOW, DAY, ZONE)['streak']['days'], 1)
        self.assertEqual(build(data(), [food('2026-11-13'), food('2026-11-15')], NOW, DAY, ZONE, rest_days={'2026-11-14'})['streak']['days'], 3)

    def test_streak_milestone_is_celebrated_once_it_is_reached_today(self):
        food = [{'source': 'food', 'entity_id': f'daily:2026-11-{d}', 'payload': {'source_local_date': f'2026-11-{d}', 'logged_meal_count': 1}} for d in (13, 14, 15)]
        self.assertIn('streak_3', keys(build(data(), food, NOW, DAY, ZONE), starters=True))
        self.assertNotIn('streak_3', keys(build(data(), food[:2], NOW, DAY, ZONE), starters=True))

    def test_absent_sources_stay_silent_and_week_marks_them_unknown(self):
        result = build({'nutrition': None, 'supply': None, 'activity': None}, [], NOW, DAY, ZONE)
        self.assertEqual(result['cards'], [])
        self.assertEqual((result['week']['workouts'], result['week']['food_days'], result['week']['supply_days'], result['week']['headline']), (None, None, None, None))

    def test_week_names_the_weakest_connected_area(self):
        result = build(data(), [{'source': 'food', 'entity_id': 'daily:2026-11-15', 'payload': {'source_local_date': '2026-11-15', 'logged_meal_count': 2}}], NOW, DAY, ZONE)
        self.assertEqual(result['week']['food_days'], 1)
        self.assertIn(result['week']['headline'], ('На этой неделе просели добавки.', 'На этой неделе просели тренировки.'))

    def test_protein_packed_into_one_meal_needs_four_full_days_and_a_majority(self):
        def meals(packed_days):
            out = []
            for offset in range(5):
                day = (DAY - timedelta(days=offset)).isoformat()
                split = (90, 10, 10) if offset < packed_days else (40, 35, 35)
                out += [{'source': 'food', 'entity_id': f'meal:{offset}{i}', 'payload': {'source_local_date': day, 'macros': {'protein': p}}} for i, p in enumerate(split)]
            return out
        self.assertIn('protein_spread', keys(build(data(), meals(3), NOW, DAY, ZONE)))
        self.assertNotIn('protein_spread', keys(build(data(), meals(2), NOW, DAY, ZONE)))
        self.assertNotIn('protein_spread', keys(build(data(), meals(3)[:9], NOW, DAY, ZONE)))

    def test_intake_planned_inside_the_usual_training_window_and_trained_today(self):
        evenings = [{'source': 'gym', 'entity_id': f'workout:{i}', 'payload': {'completed_at': (datetime(2026, 11, 8, 17, tzinfo=timezone.utc) - timedelta(days=7 * i)).isoformat(), 'session_complete': True}} for i in range(4)]
        def planned(clock, active=True):
            return [{'source': 'supply', 'entity_id': 'supplement:1', 'payload': {'name': 'Магний', 'active': active, 'scheduled_time': clock}}]
        self.assertIn('slot_during_training', keys(build(data(supplements=['Магний']), evenings + planned('19:00'), NOW, DAY, ZONE)))
        for clock, active in (('21:00', True), ('08:00', True), ('19:00', False), (None, True)):
            self.assertNotIn('slot_during_training', keys(build(data(supplements=['Магний']), evenings + planned(clock, active), NOW, DAY, ZONE)), (clock, active))
        self.assertFalse(build(data(), evenings, NOW, DAY, ZONE)['trained_today'])
        today = [{'source': 'gym', 'entity_id': 'workout:t', 'payload': {'completed_at': NOW.isoformat(), 'session_complete': True}}]
        self.assertTrue(build(data(), today, NOW, DAY, ZONE)['trained_today'])

    def test_water_rules_only_for_people_who_record_water(self):
        def daily(offset, ml):
            d = (DAY - timedelta(days=offset)).isoformat()
            return {'source': 'food', 'entity_id': 'daily:1:' + d, 'payload': {'source_local_date': d, 'logged_meal_count': 2, 'water_ml': ml}}
        today = [{'source': 'gym', 'entity_id': 'workout:t', 'payload': {'completed_at': NOW.isoformat(), 'session_complete': True}}]
        logged = [daily(1, 2000), daily(2, 1800), daily(0, 500)]
        self.assertIn('water_after_workout', keys(build(data(), today + logged, NOW, DAY, ZONE)))
        self.assertNotIn('water_after_workout', keys(build(data(), today + logged, NOW.replace(hour=6), DAY, ZONE)))
        self.assertNotIn('water_after_workout', keys(build(data(), today + [daily(0, None), daily(1, None)], NOW, DAY, ZONE)))
        self.assertNotIn('water_after_workout', keys(build(data(), today + [daily(1, 2000), daily(2, 1800), daily(0, 1600)], NOW, DAY, ZONE)))
        low = build(data(), [daily(i, 800) for i in range(1, 5)], NOW, DAY, ZONE)
        self.assertIn('water_low', keys(low))
        self.assertEqual(low['week']['average_water_ml'], 800)
        self.assertIsNone(build(data(), [], NOW, DAY, ZONE)['week']['average_water_ml'])


if __name__ == '__main__':
    unittest.main()
