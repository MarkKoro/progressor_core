import concurrent.futures
import os
import tempfile
import unittest
from pathlib import Path
from shared.ai_guard import acquire,finish,AttemptLimited
from shared.workout_metrics import energy_estimate,set_metrics,compare_load


class Metrics(unittest.TestCase):
    def test_population_range_and_net_are_separate(self):
        e=energy_estimate(3600,80,age_years=30)
        self.assertEqual(e['gross_kcal_range'],[280,480])
        self.assertEqual(e['net_above_rest_kcal_range'],[200,400])
        self.assertEqual(e['quality'],'population_model_range_not_confidence_interval')

    def test_unknown_invalid_child_older_age_not_adult_default(self):
        for d,w,a in ((None,80,30),(3600,None,30),(3600,80,None),(3600,80,16),(3600,80,75),(True,80,30),(3600,float('nan'),30)):
            self.assertIsNone(energy_estimate(d,w,age_years=a))

    def test_sets_are_work_metrics_never_calories(self):
        rows=[{'user_exercise_id':1,'reps':10,'weight_kg':50,'is_warmup':False} for _ in range(15)]
        rows.append({'user_exercise_id':1,'reps':5,'weight_kg':20,'is_warmup':True})
        m=set_metrics(rows)
        self.assertEqual((m['working_sets'],m['repetitions'],m['external_volume_kg']),(15,150,7500))
        self.assertNotIn('energy_kcal_range',m)

    def test_comparable_baseline_and_new_program_do_not_mix(self):
        def m(kg,key=1):return set_metrics([{'user_exercise_id':key,'reps':10,'weight_kg':kg}])
        self.assertEqual(compare_load(m(50),[m(50)]*3)['status'],'usual_recorded_load')
        self.assertEqual(compare_load(m(75),[m(50)]*3)['status'],'higher_recorded_load')
        self.assertEqual(compare_load(m(75,2),[m(50)]*3)['status'],'insufficient_comparable_history')
        self.assertEqual(compare_load(m(75),[m(0)]*3)['status'],'insufficient_comparable_history')


class AttemptControl(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path=Path(self.tmp.name)/'owner.db'
    def tearDown(self):self.tmp.cleanup()

    def test_parallel_actions_start_one_call(self):
        def start(_):
            try:return acquire(self.path,1,'ai',now=1000)
            except AttemptLimited:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:tokens=list(pool.map(start,range(8)))
        self.assertEqual(sum(bool(t) for t in tokens),1)
        acquire(self.path,2,'ai',now=1000)

    def test_failure_is_not_an_unlimited_refund(self):
        for stamp in (1000,1020,1040):
            t=acquire(self.path,1,'ai',now=stamp,hourly=3);finish(self.path,t)
        with self.assertRaises(AttemptLimited) as e:acquire(self.path,1,'ai',now=1060,hourly=3)
        self.assertEqual(e.exception.reason,'hourly_attempts')
        acquire(self.path,1,'ai',now=4700,hourly=3)

    def test_cooldown_expiry_and_token_owned_release(self):
        a=acquire(self.path,1,'ai',now=1000,lease_seconds=30)
        b=acquire(self.path,1,'ai',now=1031,lease_seconds=30)
        finish(self.path,a)
        with self.assertRaises(AttemptLimited):acquire(self.path,1,'ai',now=1032)
        finish(self.path,b)
        with self.assertRaises(AttemptLimited) as e:acquire(self.path,1,'ai',now=1032)
        self.assertEqual(e.exception.reason,'cooldown')

    def test_saved_success_allows_next_distinct_action_without_failure_pause(self):
        t=acquire(self.path,1,'ai',now=1000,success_cooldown=0)
        finish(self.path,t,successful=True)
        acquire(self.path,1,'ai',now=1001,success_cooldown=0)
