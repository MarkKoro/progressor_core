import os,tempfile,time,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from test_integration import fixture,USER,OTHER,KEY,TOKENS
from progressor_core.app import Config,create_app
from progressor_core.auth import sign_assertion


class NativeAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));root=Path(self.tmp.name)
        self.config=Config(str(root/'core.sqlite3'),KEY,fixture(root),TOKENS,background=False)
    def tearDown(self):self.tmp.cleanup()
    def headers(self,user=USER,audience='core'):
        return {'X-Progressor-Auth':sign_assertion({'id':user},int(time.time()),audience,KEY)}
    def test_dismissal_is_signed_account_only_and_persists_per_target(self):
        with TestClient(create_app(self.config)) as client:
            store=client.app.state.engine.store;client.app.state.engine.poll()
            response=client.post('/api/v1/me/hints/dismiss',json={'target':'food','user_id':str(OTHER)},headers=self.headers())
            self.assertEqual(response.status_code,200)
            self.assertTrue(store.hints_dismissed(str(USER),'food'));self.assertFalse(store.hints_dismissed(str(OTHER),'food'))
            self.assertFalse(store.hints_dismissed(str(USER),'gym'))
            self.assertAlmostEqual(response.json()['dismissed_until']-time.time(),7*86400,delta=5)
    def test_missing_signature_wrong_audience_free_target_and_bad_target(self):
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll();url='/api/v1/me/hints/dismiss'
            self.assertEqual(client.post(url,json={'target':'food'}).status_code,401)
            self.assertEqual(client.post(url,json={'target':'food'},headers=self.headers(audience='gym')).status_code,401)
            self.assertEqual(client.post(url,json={'target':'food'},headers=self.headers(OTHER)).status_code,403)
            for body in ({'target':'other'},{'target':[]},{},None):
                self.assertEqual(client.post(url,json=body,headers=self.headers()).status_code,422)
            self.assertEqual(client.post(url,content='x'*300,headers=self.headers()).status_code,413)
