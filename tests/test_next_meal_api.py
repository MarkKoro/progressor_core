"""Real signed local control boundary; public assertions never grant it."""
import os,json,tempfile,time,unittest,sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from test_integration import fixture,USER,OTHER,KEY,TOKENS
from progressor_core.app import Config,create_app
from progressor_core.auth import sign_assertion
from progressor_core.connections import save_preferences
from shared.progressor_client import canonical,control_token


class NextMealAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));root=Path(self.tmp.name)
        self.config=Config(str(root/'core.db'),KEY,fixture(root),TOKENS,background=False)
        self.client=TestClient(create_app(self.config));self.client.__enter__()
        self.engine=self.client.app.state.engine;self.engine.poll()
        gate=root/'next-meal-v1-ready';gate.write_text('ready');self.engine.store.next_meal_gate=gate
        save_preferences(self.engine.store,str(USER),{'diet':'any'},0)
    def tearDown(self):
        self.client.__exit__(None,None,None)
        import gc;gc.collect();self.tmp.cleanup()
    def request(self,body=None,source='food',signature=True):
        path='/internal/v1/connections/next-meal';raw=canonical(body or {'user_id':str(USER),'data_reset_revision':0}).encode()
        headers={'X-Progressor-Control':control_token(source,path,raw,KEY)} if signature else {}
        return self.client.post(path,content=raw,headers=headers)
    def test_native_food_only_signed_control_and_exact_shape(self):
        self.assertEqual(self.request(signature=False).status_code,401)
        self.assertEqual(self.request(source='gym').status_code,403)
        self.assertEqual(self.request(source='supply').status_code,403)
        for body in ({'user_id':str(USER)}, {'user_id':str(USER),'data_reset_revision':False},{'user_id':str(USER),'data_reset_revision':0,'extra':1}):
            self.assertEqual(self.request(body).status_code,409)
        result=self.request();self.assertEqual(result.status_code,200);self.assertTrue(result.json()['available'])
    def test_public_assertion_cannot_call_control_route(self):
        result=self.client.post('/internal/v1/connections/next-meal',json={'user_id':str(USER),'data_reset_revision':0},headers={'X-Progressor-Auth':sign_assertion({'id':USER},int(time.time()),'core',KEY)})
        self.assertEqual(result.status_code,401)
    def test_owner_is_local_verified_subject_and_other_membership_is_absent(self):
        result=self.request({'user_id':str(OTHER),'data_reset_revision':0}).json()
        self.assertEqual(result['owner_subject'],str(OTHER));self.assertFalse(result['available']);self.assertEqual(result['ideas'],[])
    def test_real_adapter_reset_closes_choice_without_erasing_other_settings(self):
        state=self.request().json()
        operation={k:state[k] for k in ('day','choice_revision','preferences_revision','catalog_version','data_reset_revision')}|{'operation_id':'x'*24,'action':'choose','idea_id':state['ideas'][0]['id']}
        body={'user_id':str(USER),'data_reset_revision':0,'operation':operation}
        self.assertEqual(self.request(body).status_code,200)
        with sqlite3.connect(self.config.source_paths['food']) as db:
            db.execute('CREATE TABLE progressor_food_resets(user_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL)')
            db.execute('INSERT INTO progressor_food_resets VALUES(?,1)',(USER,))
        self.assertFalse(self.request({'user_id':str(USER),'data_reset_revision':1}).json()['available'])
        self.engine.poll()
        state=self.request({'user_id':str(USER),'data_reset_revision':1}).json()
        self.assertTrue(state['available']);self.assertIsNone(state['choice']);self.assertEqual(state['data_reset_revision'],1)
        self.assertEqual(self.request({**body,'data_reset_revision':1}).status_code,409)
        from progressor_core.connections import preferences
        self.assertEqual(preferences(self.engine.store,str(USER))['revision'],1)
