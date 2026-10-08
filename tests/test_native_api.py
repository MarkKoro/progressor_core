import os,tempfile,time,unittest
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from fastapi.testclient import TestClient
from test_integration import fixture,USER,OTHER,KEY,TOKENS
from progressor_core.app import Config,create_app
from progressor_core.auth import sign_assertion
from shared.progressor_client import canonical,control_token


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

    def test_offer_hide_allowed_for_free_gym_but_identity_is_signed(self):
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll();url='/api/v1/me/offers/dismiss'
            self.assertEqual(client.post(url,json={'target':'gym'},headers=self.headers(OTHER)).status_code,200)
            self.assertTrue(client.app.state.engine.store.offers_dismissed(str(OTHER),'gym'))
            self.assertFalse(client.app.state.engine.store.offers_dismissed(str(USER),'gym'))
            self.assertEqual(client.post(url,json={'target':'gym'}).status_code,401)

    def test_visible_hint_ack_requires_current_real_signed_hint(self):
        now=datetime.now(timezone.utc)
        from progressor_core.adapters import zone
        gym_date=now.astimezone(zone('Asia/Bangkok')).date().isoformat()
        with sqlite3.connect(self.config.source_paths['gym']) as db:
            db.execute('UPDATE sessions SET date=?',(gym_date,));db.execute('UPDATE day_completion_history SET completed_at=?',(now.isoformat(),))
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll();h=client.get('/api/v1/me/context?target=food',headers=self.headers()).json()['inline_hint']
            self.assertIsNotNone(h)
            url='/api/v1/me/hints/seen';body={'target':'food','delivery_key':h['delivery_key'],'user_id':str(OTHER)}
            self.assertEqual(client.post(url,json=body,headers=self.headers()).status_code,200)
            self.assertTrue(client.app.state.engine.store.hint_was_seen(str(USER),'food',h['delivery_key']))
            self.assertFalse(client.app.state.engine.store.hint_was_seen(str(OTHER),'food',h['delivery_key']))
            self.assertEqual(client.post(url,json=body,headers=self.headers(OTHER)).status_code,422)
            self.assertEqual(client.post(url,json={**body,'delivery_key':'made_up'},headers=self.headers()).status_code,422)

    def test_notification_control_is_private_food_only_and_bounded(self):
        with TestClient(create_app(self.config)) as client:
            client.app.state.engine.poll();path='/internal/v1/food-notifications';raw=canonical({'people':[]}).encode()
            self.assertEqual(client.post(path,content=raw).status_code,401)
            def request(source,body):
                data=canonical(body).encode();return client.post(path,content=data,headers={'X-Progressor-Control':control_token(source,path,data,KEY)})
            self.assertEqual(request('gym',{'people':[]}).status_code,403)
            self.assertEqual(request('food',{'people':[]}).json(),{'items':[]})
            self.assertEqual(request('food',{'people':[{}]*51}).status_code,422)
