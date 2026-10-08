"""Account/source authentication, same bot/WebApp/website quote, no real provider."""
import hashlib,json,os,sqlite3,tempfile,time,unittest,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from progressor_core.app import Config,create_app
from progressor_core.auth import sign_assertion
from progressor_core.native_pricing import NativePricing
from shared.progressor_client import canonical,control_token
from shared.native_subscription import GRANTS,TARIFFS,record_paid
from test_integration import fixture,USER,OTHER,KEY,TOKENS

class UpgradeAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.now=datetime.now(timezone.utc)
        for s in self.paths:
            with sqlite3.connect(self.paths[s]) as db:
                db.execute(GRANTS);db.execute(TARIFFS)
                db.execute('INSERT INTO progressor_native_tariffs VALUES(?,?,?)',(s,json.dumps({'RUB':{'food':39900,'gym':10000,'supply':20000}[s],'XTR':{'food':266,'gym':80,'supply':250}[s]}),time.time()))
                if s=='food':record_paid(db,'food:receipt',str(USER),self.now-timedelta(days=10),self.now+timedelta(days=20),'RUB',39900)
        self.client=TestClient(create_app(Config(str(self.root/'core.db'),KEY,self.paths,TOKENS,background=False)))
        self.client.__enter__();self.engine=self.client.app.state.engine;self.engine.poll()
        self.auth={'X-Progressor-Auth':sign_assertion({'id':USER},int(time.time()),'core',KEY)}
    def tearDown(self):self.client.__exit__(None,None,None);self.tmp.cleanup()
    def private(self,source,path,body):
        data=canonical(body).encode()
        return self.client.post(path,content=data,headers={'X-Progressor-Control':control_token(source,path,data,KEY)})
    def test_personal_prices_are_the_same_on_all_three_signed_bot_channels_and_webapp(self):
        public=self.client.get('/api/v1/me/bundle/catalog',headers=self.auth)
        self.assertEqual(public.status_code,200);catalog=public.json()
        self.assertIn('align',[p['id'] for p in catalog['plans']]);self.assertLess(next(p for p in catalog['plans'] if p['id']=='m1')['XTR'],450)
        values=lambda plans:[(p['id'],p['XTR'],p['RUB']) for p in plans]
        for source in self.paths:
            self.assertEqual(values(self.private(source,'/internal/v1/bundle/catalog',{'user_id':str(USER)}).json()['plans']),values(catalog['plans']))
        self.assertEqual(self.client.get('/api/v1/me/bundle/catalog').status_code,401)
        other={'X-Progressor-Auth':sign_assertion({'id':OTHER},int(time.time()),'core',KEY)}
        self.assertEqual(self.client.get('/api/v1/me/bundle/catalog',headers=other).json()['plans'][0]['XTR'],450)
    def test_website_requires_its_own_session_and_uses_same_credit(self):
        path='/api/v1/website/catalog'
        self.assertEqual(self.client.post(path,headers={'X-Progressor-Web':self.auth['X-Progressor-Auth']}).status_code,401)
        token=sign_assertion({'id':USER},int(time.time()),'core',KEY,ttl=900)
        with self.engine.store.connection() as db:db.execute('INSERT INTO website_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),str(USER),time.time()+600))
        website=self.client.post(path,headers={'X-Progressor-Web':token}).json()
        self.assertEqual([(p['id'],p['RUB'],p['XTR']) for p in website['plans']],[(p['id'],p['RUB'],p['XTR']) for p in self.client.get('/api/v1/me/bundle/catalog',headers=self.auth).json()['plans']])
    def test_actual_quote_id_source_and_subject_isolate_invoice_and_cancel(self):
        order=self.private('food','/internal/v1/bundle/quote',{'user_id':str(USER),'order_id':str(uuid.uuid4()),'plan':'m1','terms':'progressor.bundle.v2'}).json()
        provider=AsyncMock(return_value='https://t.me/$offline')
        with patch('progressor_core.payments.invoice',provider):
            good=self.private('food','/internal/v1/bundle/invoice-link',{'user_id':str(USER),'order_id':order['id']})
            self.assertEqual(good.status_code,200)
            self.assertEqual(self.private('gym','/internal/v1/bundle/invoice-link',{'user_id':str(USER),'order_id':order['id']}).status_code,409)
            self.assertEqual(self.private('food','/internal/v1/bundle/invoice-link',{'user_id':str(OTHER),'order_id':order['id']}).status_code,409)
            self.assertEqual(provider.await_count,1)
        other={'X-Progressor-Auth':sign_assertion({'id':OTHER},int(time.time()),'core',KEY)}
        self.assertEqual(self.client.post('/api/v1/me/bundle/cancel',json={'order_id':order['id']},headers=other).status_code,409)
        self.assertEqual(self.client.post('/api/v1/me/bundle/cancel',json={'order_id':order['id']},headers=self.auth).status_code,200)
    def test_stale_pricing_does_not_silently_charge_full_price_and_source_expiry_clips_credit(self):
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE progressor_native_tariffs SET updated_at=?',(time.time()-600,))
        self.assertEqual(self.client.get('/api/v1/me/bundle/catalog',headers=self.auth).status_code,503)
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('UPDATE progressor_native_tariffs SET updated_at=?',(time.time(),))
            db.execute("UPDATE users SET premium_until='2000-01-01T00:00:00Z'")
        inputs=NativePricing(self.paths)(str(USER));self.assertEqual(inputs['food']['paid_intervals'],[])
