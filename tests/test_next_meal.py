"""Explicit intent with real SQLite/CAS; no source writer, provider or consumer."""
import json,os,tempfile,time,unittest,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from progressor_core.store import Store
from progressor_core import next_meal as meals,connections
from progressor_core.meal_ideas import ideas,IDEAS,COMPONENTS


class NextMeal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.store=Store(Path(self.tmp.name)/'core.db');self.now=datetime.now(timezone.utc)
        self.gate=Path(self.tmp.name)/'next-meal-v1-ready';self.gate.write_text('ready');self.store.next_meal_gate=self.gate
        for uid in ('123','456'):
            with self.store.connection() as db:
                db.execute('INSERT INTO identities VALUES(?,?)',(uid,self.now.isoformat()))
                db.execute("INSERT INTO memberships VALUES('food',?,?,1)",(uid,uid))
                payload=json.dumps({'paid_until':(self.now+timedelta(days=30)).isoformat(),'data_reset_revision':0})
                db.execute("INSERT INTO entities VALUES('food',?,?,1,'h','e','profile.updated',0,?)",('profile:'+uid,uid,payload))
                db.execute('INSERT INTO next_meal_owner_resets VALUES(?,0)',(uid,))
            connections.save_preferences(self.store,uid,{'diet':'any','excluded_food_groups':[]},0)
        self.fresh()
    def tearDown(self):self.tmp.cleanup()
    def fresh(self,now=None):
        stamp=(now or self.now).timestamp()
        with self.store.connection() as db:db.execute("INSERT OR REPLACE INTO source_state VALUES('food','ok',?,?,0,0,NULL)",(stamp,stamp))
    def view(self,uid='123',now=None,epoch=None):return meals.view(self.store,uid,now or self.now,epoch)
    def op(self,idea='beans_rice',uid='123',state=None):
        state=state or self.view(uid)
        return {k:state[k] for k in ('day','choice_revision','preferences_revision','catalog_version','data_reset_revision')}|{'operation_id':uuid.uuid4().hex,'action':'choose' if idea else 'cancel'}|({'idea_id':idea} if idea else {})
    def change(self,op,uid='123',now=None,epoch=None):return meals.change(self.store,uid,op,now or self.now,epoch)
    def prefs(self,patch,uid='123'):
        return connections.save_preferences(self.store,uid,patch,connections.preferences(self.store,uid)['revision'])
    def dump(self):
        with self.store.connection() as db:return '\n'.join(db.iterdump())
    def test_get_is_read_only_and_choice_never_marks_food_as_eaten(self):
        before=self.dump();view=self.view();self.assertTrue(view['available']);self.assertEqual(self.dump(),before)
        first=self.change(self.op());self.assertFalse(first['recorded_as_eaten']);self.assertEqual(first['choice']['id'],'beans_rice')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entities').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM recommendations').fetchone()[0],0)
    def test_repeat_once_and_replay_after_replacement_and_cancel(self):
        old=self.op();self.change(old);self.assertTrue(self.change(old)['duplicate'])
        self.change(self.op('poultry_rice'));replay=self.change(old)
        self.assertTrue(replay['duplicate']);self.assertFalse(replay['current_matches']);self.assertEqual(replay['choice']['id'],'poultry_rice')
        self.change(self.op(None));replay=self.change(old)
        self.assertIsNone(replay['choice']);self.assertFalse(replay['current_matches'])
        self.assertEqual(self.view()['choice_revision'],3)
    def test_receipt_cannot_be_reused_for_another_payload(self):
        op=self.op();self.change(op)
        with self.assertRaisesRegex(meals.ChoiceConflict,'operation_conflict'):self.change({**op,'idea_id':'poultry_rice'})
    def test_concurrent_different_operations_use_one_cas_winner(self):
        ops=[self.op(),self.op('poultry_rice')]
        def attempt(op):
            try:return self.change(op)['duplicate']
            except meals.ChoiceConflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:out=list(pool.map(attempt,ops))
        self.assertEqual(out.count(False),1);self.assertEqual(out.count('conflict'),1)
        self.assertEqual(self.view()['choice_revision'],1)
    def test_concurrent_same_operation_has_one_choice_and_receipt(self):
        op=self.op()
        with ThreadPoolExecutor(2) as pool:out=list(pool.map(lambda _:self.change(op)['duplicate'],range(2)))
        self.assertEqual(sorted(out),[False,True]);self.assertEqual(self.view()['choice_revision'],1)
    def test_receipt_failure_rolls_back_choice(self):
        with self.store.connection() as db:db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON next_meal_receipts BEGIN SELECT RAISE(ABORT,'offline');END")
        with self.assertRaises(Exception):self.change(self.op())
        self.assertEqual(self.view()['choice_revision'],0)
    def test_ordinary_and_raw_preference_aba_reject_stale_operation(self):
        for mode in ('normal','raw','delete'):
            with self.subTest(mode=mode):
                op=self.op()
                if mode=='normal':self.prefs({'diet':'vegan'});self.prefs({'diet':'any'})
                else:
                    with self.store.connection() as db:
                        row=db.execute('SELECT * FROM connection_preferences WHERE user_id=?',('123',)).fetchone()
                        if mode=='raw':
                            body=json.loads(row['body']);body['diet']='vegan'
                            db.execute('UPDATE connection_preferences SET body=? WHERE user_id=?',(json.dumps(body),'123'))
                            db.execute('UPDATE connection_preferences SET body=? WHERE user_id=?',(row['body'],'123'))
                        else:
                            db.execute('DELETE FROM connection_preferences WHERE user_id=?',('123',))
                            db.execute('INSERT INTO connection_preferences VALUES(?,?,?,?)',tuple(row))
                self.assertGreater(connections.preferences(self.store,'123')['revision'],op['preferences_revision'])
                with self.assertRaisesRegex(meals.ChoiceConflict,'choice_changed'):self.change(op)
    def test_version_seed_survives_reopen_and_deleted_preferences_can_be_saved(self):
        rev=self.prefs({'hints':False})['revision'];self.store=Store(self.store.path);self.store.next_meal_gate=self.gate
        self.assertEqual(connections.preferences(self.store,'123')['revision'],rev)
        with self.store.connection() as db:db.execute('DELETE FROM connection_preferences WHERE user_id=?',('123',))
        self.assertEqual(self.view()['unavailable_reason'],'preferences_required')
        self.assertGreater(self.prefs({'diet':'any'})['revision'],rev)
    def test_changed_settings_hide_previous_recipe_including_duplicate_response(self):
        op=self.op('poultry_rice');self.change(op);self.prefs({'diet':'vegan'})
        view=self.view();self.assertIsNone(view['choice']);self.assertEqual(view['choice_state'],'settings_changed')
        response=self.change(op);self.assertIsNone(response['choice']);self.assertNotIn('poultry_rice',json.dumps(response))
    def test_owner_isolation_and_no_recipe_from_another_account(self):
        op=self.op('poultry_rice');self.change(op)
        self.assertIsNone(self.view('456')['choice'])
        self.assertEqual(self.change(op,'456')['choice']['id'],'poultry_rice')
        self.assertEqual(self.view()['choice_revision'],1)
    def test_rest_and_hints_off_allow_explicit_tool(self):
        self.prefs({'paused':True,'hints':False,'notifications':False})
        self.assertTrue(self.view()['available']);self.assertTrue(self.change(self.op())['applied'])
    def test_food_off_config_disabled_stale_membership_and_expired_access(self):
        self.prefs({'sources':{'gym':True,'food':False,'supply':True}})
        self.assertEqual(self.view()['unavailable_reason'],'food_connection_disabled')
        self.prefs({'sources':{'gym':True,'food':True,'supply':True}})
        self.store.enabled_sources=('gym',);self.assertFalse(self.view()['available']);self.store.enabled_sources=('food',)
        self.fresh(self.now-timedelta(seconds=121));self.assertFalse(self.view()['available']);self.fresh()
        with self.store.connection() as db:db.execute("UPDATE memberships SET active=0 WHERE user_id='123'")
        self.assertEqual(self.view()['unavailable_reason'],'food_access_required')
        with self.store.connection() as db:
            db.execute("UPDATE memberships SET active=1 WHERE user_id='123'")
            db.execute("UPDATE entities SET payload='{}' WHERE user_id='123'")
        self.assertEqual(self.view()['unavailable_reason'],'food_access_required')
    def test_current_trial_works_without_gym_supply_or_paid_access(self):
        with self.store.connection() as db:db.execute('UPDATE entities SET payload=? WHERE user_id=?',(json.dumps({'native_trial_until':(self.now+timedelta(days=1)).isoformat()}),'123'))
        self.assertTrue(self.view()['available'])
    def test_missing_and_corrupt_restrictions_fail_closed(self):
        for body in ('invalid','{}','{"sources":[]}','{"diet":"any","sources":{"gym":true,"food":true,"supply":true},"excluded_food_groups":["unknown"]}'):
            with self.store.connection() as db:db.execute('UPDATE connection_preferences SET body=? WHERE user_id=?',(body,'123'))
            view=self.view();self.assertFalse(view['available']);self.assertEqual(view['ideas'],[])
    def test_catalog_has_complete_known_tags_and_exclusions_are_respected(self):
        all_groups={group for _,_,parts in IDEAS for part in parts for group in COMPONENTS[part][1]}
        self.assertEqual(all_groups,set(connections.FOOD_GROUPS))
        for group in connections.FOOD_GROUPS:
            for item in ideas({'diet':'any','excluded_food_groups':[group]},100):self.assertNotIn(group,item['food_groups'])
        result=ideas({'diet':'vegan','excluded_food_groups':['nuts','soy','gluten','sesame']})
        self.assertGreater(len(result),0);self.assertLessEqual(len(result),3)
        self.assertFalse(set(result[0]['food_groups'])&set(connections.FOOD_GROUPS))
    def test_unknown_or_excluded_idea_is_not_applied(self):
        self.prefs({'diet':'vegan'})
        for idea in ('poultry_rice','missing'):
            with self.assertRaisesRegex(meals.ChoiceConflict,'idea_unavailable'):self.change(self.op(idea))
        self.assertIsNone(self.view()['choice'])
    def test_moscow_day_and_expired_receipt_never_resurrect_yesterday(self):
        first=self.now.replace(hour=20,minute=59,second=0);self.fresh(first)
        op=self.op(state=self.view(now=first));self.change(op,now=first)
        later=first+timedelta(minutes=2);self.fresh(later)
        view=self.view(now=later);self.assertEqual(view['choice_state'],'different_day');self.assertIsNone(view['choice'])
        self.assertFalse(self.change(op,now=later)['current_matches'])
        later=first+timedelta(days=2);self.fresh(later)
        with self.assertRaisesRegex(meals.ChoiceConflict,'choice_changed'):self.change(op,now=later)
    def test_receipt_limit_and_cleanup_are_bounded(self):
        with self.store.connection() as db:
            db.executemany('INSERT INTO next_meal_receipts VALUES(?,?,?,0,?,?)',[('123',str(i),'h',self.view()['day'],self.now.timestamp()+100) for i in range(64)])
        with self.assertRaisesRegex(meals.ChoiceConflict,'too_many_choices'):self.change(self.op())
        self.assertIsNone(self.view()['choice'])
    def test_restart_keeps_receipt_and_no_extra_version(self):
        op=self.op();self.change(op);self.store=Store(self.store.path);self.store.next_meal_gate=self.gate
        self.assertTrue(self.change(op)['duplicate']);self.assertEqual(self.view()['choice_revision'],1)
    def test_reset_epoch_invalidates_cached_operations_and_stale_export(self):
        op=self.op();self.change(op)
        self.assertEqual(self.view(epoch=1)['unavailable_reason'],'reset_sync_pending')
        with self.store.connection() as db:
            meals.reconcile_resets(db,{'entities':[{'entity_id':'profile:123','user_id':'123','payload':{'data_reset_revision':1}}]})
            db.execute('UPDATE entities SET payload=? WHERE user_id=?',(json.dumps({'paid_until':(self.now+timedelta(days=1)).isoformat(),'data_reset_revision':1}),'123'))
        self.assertIsNone(self.view(epoch=1)['choice']);self.assertTrue(self.view(epoch=1)['available'])
        with self.assertRaises(meals.ChoiceConflict):self.change(op,epoch=1)
        self.assertEqual(connections.preferences(self.store,'123')['revision'],1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM next_meal_receipts').fetchone()[0],0)
            meals.reconcile_resets(db,{'entities':[{'entity_id':'profile:123','user_id':'123','payload':{'data_reset_revision':0}}]})
            db.execute("UPDATE entities SET payload='{}' WHERE user_id='123'")
        self.assertEqual(self.view(epoch=1)['unavailable_reason'],'reset_sync_pending')
    def test_explicit_identity_delete_cleans_new_owner_metadata_only(self):
        self.change(self.op())
        with self.store.connection() as db:
            db.execute("DELETE FROM identities WHERE user_id='123'")
            for table in ('next_meal_choices','next_meal_receipts','next_meal_owner_resets','connection_preference_versions','connection_preferences'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table} WHERE user_id=?',('123',)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT revision FROM connection_preferences WHERE user_id='456'").fetchone()[0],1)
    def test_missing_readiness_gate_does_not_activate_tool_or_mutate_choice(self):
        op=self.op();self.gate.unlink();self.assertEqual(self.view()['unavailable_reason'],'feature_not_ready')
        with self.assertRaisesRegex(meals.ChoiceConflict,'feature_not_ready'):self.change(op)
        self.assertEqual(self.view()['choice_revision'],0)
