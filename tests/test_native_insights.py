import gc,json,os,sqlite3,tempfile,unittest
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path
from test_integration import fixture,USER,NOW
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core.context import build_context
from progressor_core.ai_context import build_ai_context


class NativeContext(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db');self.sync()
    def tearDown(self):
        # sqlite3's context manager commits but does not close fixture handles;
        # release their statement-cache cycles before Windows removes the files.
        gc.collect()
        self.tmp.cleanup()
    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
    def context(self,target):return build_context(self.store,str(USER),NOW,target=target)
    def detailed_gym(self):
        with sqlite3.connect(self.paths['gym']) as db:
            for col,spec in (('user_exercise_id','INTEGER'),('reps','INTEGER'),('seconds','INTEGER'),('weight_kg','REAL')):
                db.execute(f'ALTER TABLE sets ADD COLUMN {col} {spec}')
            db.execute('UPDATE sets SET user_exercise_id=700,reps=10,seconds=0,weight_kg=75')
            db.execute('CREATE TABLE workout_session_details(session_id INTEGER PRIMARY KEY,history_id INTEGER,duration_seconds INTEGER,recorded_at TEXT)')
            db.execute("INSERT INTO workout_session_details VALUES(20,10,3600,'2026-10-07T09:00:00Z')")
            for i,day in enumerate(('2026-10-01','2026-10-03','2026-10-05'),100):
                db.execute('INSERT INTO day_completion_history VALUES(?,7,1,1,?)',(i,day+'T09:00:00Z'))
                db.execute('INSERT INTO sessions VALUES(?,7,?,1,1)',(i,day))
                db.execute('INSERT INTO sets(id,session_id,is_warmup,user_exercise_id,reps,seconds,weight_kg) VALUES(?,?,0,700,10,0,50)',(i,i))
        self.sync()
    def profile(self):
        p={'entity_id':'profile:health:test','revision':1,'profile_kind':'reported_health','reported_profile':{'birth_year':1990,'weight_kg':80}}
        self.store.accept({'event_id':'reported-profile-test','event_type':'profile.updated','schema_version':1,'source':'supply','user_id':str(USER),'occurred_at':(NOW-timedelta(days=1)).isoformat(),'correlation_id':'test','payload':p})

    def test_workout_card_only_after_completion_and_current_day(self):
        self.assertEqual(self.context('food')['inline_hint']['key'],'workout_today.v1')
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM day_completion_history')
        self.sync();self.assertIsNone(self.context('food')['inline_hint'])

    def test_context_projection_matches_full_history_without_repeated_history_reads(self):
        from copy import deepcopy
        from test_integration import OTHER
        original=next(e for e in self.store.data(str(USER))[0] if e['entity_id'].startswith('intake:'))
        with self.store.connection() as db:
            for i in range(130):
                payload=deepcopy(original['payload'])
                payload.update(entity_id='intake:projection-'+str(i),revision=1,status='taken' if i%3==0 else 'skipped',source_local_date=(NOW-timedelta(days=i)).date().isoformat())
                self.store.accept(dict(event_id='projection-'+str(i),event_type='supplement.taken',schema_version=1,source='supply',user_id=str(USER),occurred_at=(NOW-timedelta(days=i)).isoformat(),correlation_id='test',payload=payload),db)
            other=deepcopy(original['payload']);other.update(entity_id='intake:other-projection',revision=1)
            self.store.accept(dict(event_id='other-projection',event_type='supplement.taken',schema_version=1,source='supply',user_id=str(OTHER),occurred_at=NOW.isoformat(),correlation_id='test',payload=other),db)
        full=self.store.data(str(USER))
        taken=sum(e['source']=='supply' and e['entity_id'].startswith('intake:') and e['payload'].get('status')=='taken' for e in full[0])
        with patch.object(self.store,'context_snapshot',return_value=(full,{'supply_taken_count':taken})):
            expected=self.context('food')
        with patch.object(self.store,'data',side_effect=AssertionError('full history read during context')),patch.object(self.store,'context_snapshot',wraps=self.store.context_snapshot) as read:
            actual=self.context('food')
            self.assertEqual(read.call_count,1)
        self.assertEqual(actual,expected)
        self.assertEqual(actual['supply']['recorded_intake_count'],taken)
        self.assertEqual(len(actual['supply']['recent_intakes']),90)
        projected,counts=self.store.context_snapshot(str(USER))
        self.assertFalse(any(e['entity_id'].startswith('meal:') for e in projected[0]))
        self.assertLessEqual(sum(e['entity_id'].startswith('intake:') for e in projected[0]),91)
        self.assertTrue(all(e['user_id']==str(USER) for e in projected[0]))

    def test_ai_uses_one_request_projection_and_keeps_same_permitted_output(self):
        full=self.store.data(str(USER))
        taken=sum(e['entity_id'].startswith('intake:') and e['payload'].get('status')=='taken' for e in full[0])
        with patch.object(self.store,'context_snapshot',return_value=(full,{'supply_taken_count':taken})):
            expected=build_ai_context(self.store,str(USER),'gym',NOW)
        with patch.object(self.store,'data',side_effect=AssertionError('full history read during AI context')),patch.object(self.store,'context_snapshot',wraps=self.store.context_snapshot) as read:
            actual=build_ai_context(self.store,str(USER),'gym',NOW)
            self.assertEqual(read.call_count,1)
        self.assertEqual(actual,expected)

    def test_launch_entitlements_read_membership_profiles_without_domain_history(self):
        from progressor_core.access import entitlements
        expected=entitlements(self.store,str(USER),NOW,self.store.data(str(USER))[0])
        with patch.object(self.store,'data',side_effect=AssertionError('launch read full domain history')):
            actual=entitlements(self.store,str(USER),NOW)
        self.assertEqual(actual,expected)

    def test_subscription_metadata_ignores_coach_profiles_and_full_journal_reads(self):
        from progressor_core.subscriptions import subscription_view
        from test_integration import OTHER
        payload=dict(entity_id='profile:coach:quality',revision=1,profile_kind='coach_link',coach_id=str(OTHER),link_id='11',status='accepted',coach_enabled=True)
        self.store.accept(dict(event_id='subscription-coach-quality',event_type='profile.updated',schema_version=1,source='gym',user_id=str(USER),occurred_at=NOW.isoformat(),correlation_id='test',payload=payload))
        with patch.object(self.store,'data',side_effect=AssertionError('subscriptions read full journals')):
            actual=subscription_view(self.store,str(USER))
        self.assertTrue(next(p for p in actual['products'] if p['source']=='gym')['premium_active'])
        self.assertEqual(actual['premium_count'],3)

    def test_historical_day_keeps_its_comparison_vectors_without_loading_all_old_vectors(self):
        from copy import deepcopy
        self.detailed_gym();self.profile()
        original=next(e for e in self.store.data(str(USER))[0] if e['entity_id'].startswith('workout:'))
        stamp=(NOW-timedelta(days=150)).isoformat()
        payload=deepcopy(original['payload']);payload.update(entity_id='workout:historical-quality',revision=1,completed_at=stamp,source_local_date=stamp[:10])
        self.store.accept(dict(event_id='historical-quality',event_type='workout.completed',schema_version=1,source='gym',user_id=str(USER),occurred_at=stamp,correlation_id='test',payload=payload))
        current=self.store.context_snapshot(str(USER),workout_day=NOW.date().isoformat())[0][0]
        old=next(e for e in current if e['entity_id']=='workout:historical-quality')
        self.assertNotIn('strength_metrics',old['payload'])
        self.assertEqual(old['payload']['completed_at'],stamp)
        historic=self.store.context_snapshot(str(USER),workout_day=stamp[:10])[0][0]
        self.assertEqual(next(e for e in historic if e['entity_id']=='workout:historical-quality')['payload']['strength_metrics'],payload['strength_metrics'])
        full=self.store.data(str(USER));counts={'supply_taken_count':1}
        expected=build_context(self.store,str(USER),NOW,requested_day=stamp[:10],target='food',_request_data=(full,counts))
        actual=build_context(self.store,str(USER),NOW,requested_day=stamp[:10],target='food')
        self.assertEqual(actual,expected)

    def test_settings_projection_preserves_weight_coach_and_rhythm_without_journals(self):
        from progressor_core.connections import weight_choices,coach_permissions
        from progressor_core.training_rhythm import proposal,active
        self.detailed_gym();self.profile()
        functions=(weight_choices,coach_permissions,proposal,active)
        expected=[function(self.store,str(USER)) for function in functions]
        snapshot=self.store.settings_snapshot(str(USER))
        self.assertFalse(any(e['entity_id'].startswith(('meal:','daily:','intake:','supplement:','lab:')) for e in snapshot[0]))
        self.assertTrue(all('strength_metrics' not in e['payload'] for e in snapshot[0] if e['entity_id'].startswith('workout:')))
        with patch.object(self.store,'data',side_effect=AssertionError('settings read full journals')):
            actual=[function(self.store,str(USER),snapshot=snapshot) for function in functions]
        self.assertEqual(actual,expected)

    def test_weekly_intake_total_is_not_truncated_to_public_recent_rows(self):
        from copy import deepcopy
        from progressor_core.connections import weekly_overview,save_preferences
        from test_integration import OTHER
        original=next(e for e in self.store.data(str(USER))[0] if e['entity_id'].startswith('intake:'))
        with self.store.connection() as db:
            for i in range(132):
                owner=str(OTHER) if i==131 else str(USER)
                payload=deepcopy(original['payload']);payload.update(entity_id='intake:weekly-'+str(i),revision=1,status='skipped' if i==130 else 'taken')
                self.store.accept(dict(event_id='weekly-'+str(i),event_type='supplement.taken',schema_version=1,source='supply',user_id=owner,occurred_at=NOW.isoformat(),correlation_id='test',payload=payload),db)
        self.assertEqual(len(self.context('food')['supply']['recent_intakes']),90)
        self.assertEqual(weekly_overview(self.store,str(USER),NOW)['supply']['recorded_intakes'],131)
        save_preferences(self.store,str(USER),{'sources':{'gym':True,'food':True,'supply':False}},0)
        self.assertIsNone(weekly_overview(self.store,str(USER),NOW)['supply'])

    def test_projection_retains_latest_real_taken_action_outside_recent_rows(self):
        from copy import deepcopy
        original=next(e for e in self.store.data(str(USER))[0] if e['entity_id'].startswith('intake:'))
        with self.store.connection() as db:
            for i in range(100):
                payload=deepcopy(original['payload']);payload.update(entity_id='intake:skipped-projection-'+str(i),revision=1,status='skipped',source_local_date=NOW.date().isoformat())
                self.store.accept(dict(event_id='skipped-projection-'+str(i),event_type='supplement.taken',schema_version=1,source='supply',user_id=str(USER),occurred_at=NOW.isoformat(),correlation_id='test',payload=payload),db)
        projected,counts=self.store.context_snapshot(str(USER))
        ids={e['entity_id'] for e in projected[0]}
        self.assertIn(original['entity_id'],ids)
        self.assertEqual(counts['supply_taken_count'],1)

    def test_load_comparison_and_energy_arrive_without_llm(self):
        self.detailed_gym();self.profile()
        c=self.context('food');w=c['activity']['workouts'][0]
        self.assertEqual(w['load_comparison']['status'],'higher_recorded_load')
        self.assertEqual(w['energy_estimate']['gross_kcal_range'],[280,480])
        self.assertIn('200–400',c['inline_hint']['message'])
        self.assertIsNone(c['activity']['calorie_target_adjustment'])

    def test_context_does_not_enrich_all_old_sessions_on_every_view(self):
        from copy import deepcopy
        from progressor_core.profiles import resolve_profile
        original=next(e for e in self.store.data(str(USER))[0] if e['source']=='gym' and e['entity_id'].startswith('workout:'))
        for i in range(60):
            stamp=(NOW-timedelta(days=30+i)).isoformat()
            payload=deepcopy(original['payload'])
            payload.update(entity_id='workout:old-quality-'+str(i),revision=1,completed_at=stamp,source_local_date=stamp[:10])
            self.store.accept({'event_id':'old-quality-'+str(i),'event_type':'workout.completed','schema_version':1,
                'source':'gym','user_id':str(USER),'occurred_at':stamp,'correlation_id':'test','payload':payload})
        with patch('progressor_core.native_insights.resolve_profile',wraps=resolve_profile) as resolve:
            self.context('food')
            self.assertEqual(resolve.call_count,1)
        with patch('progressor_core.native_insights.resolve_profile',wraps=resolve_profile) as resolve:
            build_ai_context(self.store,str(USER),'food',NOW)
            self.assertEqual(resolve.call_count,2)

    def test_later_profile_weight_is_not_assigned_to_older_workout(self):
        self.detailed_gym();self.profile()
        with sqlite3.connect(self.paths['gym']) as db:db.execute('DELETE FROM user_measurements')
        self.sync();self.profile()
        old=self.context('food')['activity']['workouts'][0]
        self.assertIsNotNone(old['energy_estimate'])
        later={'entity_id':'profile:health:test','revision':2,'profile_kind':'reported_health','reported_profile':{'birth_year':1990,'weight_kg':120}}
        self.store.accept({'event_id':'later-profile-test','event_type':'profile.updated','schema_version':1,'source':'supply','user_id':str(USER),'occurred_at':NOW.isoformat(),'correlation_id':'test','payload':later})
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])

    def test_missing_age_or_unpaid_supply_never_borrows_profile(self):
        self.detailed_gym()
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])
        self.profile()
        with sqlite3.connect(self.paths['supply']) as db:db.execute("UPDATE users SET premium_until_utc=NULL")
        self.sync();self.profile()
        self.assertIsNone(self.context('food')['activity']['workouts'][0]['energy_estimate'])
        self.assertIsNone(self.context('supply')['inline_hint'])

    def test_old_duplicate_completion_does_not_double_count(self):
        with sqlite3.connect(self.paths['gym']) as db:db.execute("INSERT INTO day_completion_history VALUES(11,7,1,1,'2026-10-07T09:01:00Z')")
        self.sync();self.assertEqual(self.context('food')['activity']['completed_workout_count'],1)

    def test_dismissal_is_account_and_target_scoped_survives_read(self):
        self.store.dismiss_hints(str(USER),'food')
        self.assertIsNone(self.context('food')['inline_hint'])
        self.assertIsNotNone(self.context('supply')['inline_hint'])
        self.assertFalse(self.store.hints_dismissed(str(USER+1),'food'))
        self.assertTrue(Store(self.root/'core.db').hints_dismissed(str(USER),'food'))

    def test_stale_sources_have_no_inline_claims(self):
        self.store.failed('gym','test')
        self.assertIsNone(self.context('food')['inline_hint'])
        self.store.failed('food','test')
        self.assertIsNone(self.context('supply')['inline_hint'])

    def test_partial_micronutrient_history_is_not_deficiency(self):
        c=self.context('supply')
        self.assertFalse(any(h['key'].startswith('food_sources_') for h in c['hints']))
        self.assertNotIn('недостаток железа',json.dumps(c['hints'],ensure_ascii=False))

    def test_complete_estimated_food_sources_have_manual_action_not_diagnosis(self):
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('DELETE FROM meal_nutrients');db.execute('DELETE FROM meals')
            for i in range(10):
                day=(NOW-timedelta(days=i//2+1)).date().isoformat()
                db.execute('INSERT INTO meals VALUES(?,?,?,750,40,25,100,?,0)',(i+1,USER,day,day+' 12:00:00'))
                for code,value,unit in (('iron',1,'mg'),('vitamin_b12',0.3,'ug')):
                    db.execute("INSERT INTO meal_nutrients VALUES(?,?,?,?,'ai_estimate','low','estimated',0,1,?)",(i+1,code,value,unit,NOW.isoformat()))
        self.sync();c=self.context('supply')
        self.assertEqual(c['inline_hint']['key'],'food_sources_iron.v1')
        self.assertEqual(c['inline_hint']['secondary_action']['kind'],'supply_catalog')
        self.assertIn('не устанавливает дефицит',c['inline_hint']['details'])
        self.assertNotIn('дозировка',c['inline_hint']['message'])
        with sqlite3.connect(self.paths['food']) as db:
            db.execute("DELETE FROM meal_nutrients WHERE nutrient_code='iron' AND meal_id IN (1,2,3)")
        self.sync();self.assertFalse(any(h['key']=='food_sources_iron.v1' for h in self.context('supply')['hints']))

    def test_ai_context_has_bounded_metrics_without_exercise_vectors(self):
        self.detailed_gym();self.profile()
        c=build_ai_context(self.store,str(USER),'food',NOW)
        self.assertEqual(c['prompt_version'],'progressor.cross_context.v2')
        workouts=c['data']['gym']['completed_workouts_14_days']
        self.assertLessEqual(len(workouts),20)
        self.assertNotIn('exercises',workouts[-1]['strength_metrics'])
        self.assertEqual(workouts[-1]['strength_metrics']['external_volume_kg'],750)
