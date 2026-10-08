import asyncio
import concurrent.futures
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from progressor_core.app import Engine,Config,create_app
from progressor_core.billing import receipt
from progressor_core.access import entitlements
from progressor_core.ai_context import build_ai_context
from shared.progressor_client import control_token,verify_control,ensure_schema,apply_grants,bundle_until,record_receipt
from test_integration import fixture,KEY,TOKENS,USER,OTHER,NOW,launch

class Bundle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.temp.name)
        self.paths=fixture(self.root); self.config=Config(str(self.root/'core.db'),KEY,self.paths,TOKENS,background=False)
        self.engine=Engine(self.config);self.engine.poll();self.billing=self.engine.billing
    def tearDown(self):
        import gc
        gc.collect();self.temp.cleanup()
    def order(self,source='food',currency='XTR',user=USER): return self.billing.quote(str(user),source,'m1',currency,str(uuid.uuid4()),'progressor.bundle.v1')
    def test_quote_immutable_on_price_change(self):
        o=self.order()
        with patch.dict(os.environ,PROGRESSOR_PRICE_M1_XTR='999'):
            retry=self.billing.quote(o['user_id'],o['source'],o['plan'],o['currency'],o['id'],'progressor.bundle.v1')
        self.assertEqual(retry['amount'],450)
        with self.assertRaises(ValueError):self.billing.quote(str(OTHER),'food','m1','XTR',o['id'],'progressor.bundle.v1')
    def test_owner_amount_currency_source_and_payload(self):
        o=self.order();body=receipt(o,'paid','charge')
        for key,value in [('user_id',str(OTHER)),('amount',449),('currency','RUB'),('source','gym'),('payload','other')]:
            with self.assertRaises(ValueError):self.billing.settle({**body,key:value},'food')
        self.assertFalse(entitlements(self.engine.store,str(USER))['bundle_active'])
    def test_precheckout_never_grants_and_second_checkout_rejected(self):
        o=self.order();body={**receipt(o,'paid','x'),'checkout_id':'q1'}
        self.assertTrue(self.billing.precheckout(body,'food')['ok']);self.billing.precheckout(body,'food')
        with self.assertRaises(ValueError):self.billing.precheckout({**body,'checkout_id':'q2'},'food')
        self.assertFalse(entitlements(self.engine.store,str(USER))['bundle_active'])
    def test_concurrent_duplicate_payment_extends_once(self):
        o=self.order();body=receipt(o,'paid','charge')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:self.billing.settle(body,'food'),range(6)))
        self.assertEqual(sum(r['status']=='paid' for r in results),1)
        end=datetime.fromisoformat(entitlements(self.engine.store,str(USER))['bundle_until'])
        self.assertAlmostEqual((end-datetime.now(timezone.utc)).total_seconds(),30*86400,delta=5)
    def test_two_products_purchase_extend_shared_period(self):
        a=self.order();b=self.order('gym');self.billing.settle(receipt(a,'paid','a'),'food');self.billing.settle(receipt(b,'paid','b'),'gym')
        end=datetime.fromisoformat(entitlements(self.engine.store,str(USER))['bundle_until'])
        self.assertAlmostEqual((end-datetime.now(timezone.utc)).total_seconds(),60*86400,delta=5)
    def test_refund_does_not_destroy_other_bundle_or_native_periods(self):
        a=self.order();b=self.order('gym');self.billing.settle(receipt(a,'paid','a'),'food');self.billing.settle(receipt(b,'paid','b'),'gym')
        self.billing.settle(receipt(a,'refunded','a'),'food');access=entitlements(self.engine.store,str(USER))
        end=datetime.fromisoformat(access['bundle_until']);self.assertAlmostEqual((end-datetime.now(timezone.utc)).total_seconds(),30*86400,delta=5)
        self.billing.settle(receipt(b,'refunded','b'),'gym');access=entitlements(self.engine.store,str(USER))
        self.assertFalse(access['bundle_active']);self.assertTrue(all(access['domains'].values()))
    def test_refund_before_delayed_success_cannot_resurrect(self):
        o=self.order();self.billing.settle(receipt(o,'refunded','x'),'food');self.billing.settle(receipt(o,'paid','x'),'food')
        self.assertEqual(self.billing.order(o['id'])['status'],'refunded');self.assertFalse(entitlements(self.engine.store,str(USER))['bundle_active'])
    def test_distinct_charge_cannot_reuse_paid_order(self):
        o=self.order();self.billing.settle(receipt(o,'paid','x'),'food')
        with self.assertRaises(ValueError):self.billing.settle(receipt(o,'paid','y'),'food')
    def test_rub_requires_provider_verification(self):
        o=self.order(currency='RUB')
        with self.assertRaises(ValueError):self.billing.settle(receipt(o,'paid','rub'),'food')
    def test_owner_outbox_replays_after_core_outage(self):
        o=self.order();record_receipt(self.paths['food'],receipt(o,'paid','offline'))
        self.engine.poll();self.engine.poll();self.assertTrue(entitlements(self.engine.store,str(USER))['bundle_active'])
        with self.engine.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM bundle_receipts').fetchone()[0],1)
    def test_cache_survives_outage_and_revokes_only_bundle(self):
        path=str(self.root/'cache.db');ensure_schema(path);o=self.order();self.billing.settle(receipt(o,'paid','x'),'food')
        apply_grants(path,self.billing.grants()['items'])
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):self.assertIsNotNone(bundle_until(path,USER))
        self.billing.settle(receipt(o,'refunded','x'),'food');apply_grants(path,self.billing.grants()['items'])
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):self.assertIsNone(bundle_until(path,USER))
    def test_cache_out_of_order_cannot_restore_old_grant(self):
        path=str(self.root/'cache.db');ensure_schema(path);future=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
        apply_grants(path,[{'user_id':str(USER),'expires_at':'1970-01-01T00:00:00+00:00','revision':2}]);apply_grants(path,[{'user_id':str(USER),'expires_at':future,'revision':1}])
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):self.assertIsNone(bundle_until(path,USER))
    def test_control_signature_body_path_time_source_binding(self):
        token=control_token('gym','/internal/v1/ai-context',b'{}',KEY,1000)
        self.assertEqual(verify_control(token,'/internal/v1/ai-context',b'{}',KEY,1050),'gym')
        for path,body,now in [('/wrong',b'{}',1050),('/internal/v1/ai-context',b'changed',1050),('/internal/v1/ai-context',b'{}',1061)]:
            with self.assertRaises(ValueError):verify_control(token,path,body,KEY,now)
    def test_private_requires_signature_and_public_assertion_is_insufficient(self):
        with TestClient(create_app(self.config)) as client:
            session=client.post('/api/v1/sessions',json={'source':'gym','init_data':launch()}).json()
            self.assertEqual(client.post('/internal/v1/grants',json={},headers={'X-Progressor-Auth':session['assertions']['core']}).status_code,401)
            raw=json.dumps({'user_id':str(USER)},sort_keys=True,separators=(',',':')).encode();path='/internal/v1/ai-context'
            client.app.state.engine.poll()
            result=client.post(path,content=raw,headers={'X-Progressor-Control':control_token('gym',path,raw,KEY)})
            self.assertEqual(result.status_code,200);self.assertIn('food',result.json()['data'])
    def test_subscription_matrix_hides_every_unpaid_source(self):
        from progressor_core.context import build_context
        for bits in range(8):
            for source in ('gym','food','supply'):
                paid=bool(bits & 1<<('gym','food','supply').index(source));expiry='2030-01-01T00:00:00Z' if paid else '2000-01-01T00:00:00Z'
                with sqlite3.connect(self.paths[source]) as db:
                    if source=='gym':db.execute('UPDATE subscriptions SET expires_at=?',(expiry,))
                    elif source=='food':db.execute('UPDATE users SET premium_until=?',(expiry,))
                    else:db.execute('UPDATE users SET premium_until_utc=?',(expiry,))
            self.engine.poll()
            ctx=build_context(self.engine.store,str(USER),now=NOW)
            for source,key in [('gym','activity'),('food','nutrition'),('supply','supply')]:self.assertEqual(ctx[key] is not None,bool(bits & 1<<('gym','food','supply').index(source)))
    def test_ai_does_not_receive_unpaid_or_stale_source(self):
        self.engine.store.failed('food','offline');self.assertNotIn('food',build_ai_context(self.engine.store,str(USER),'gym',NOW)['data'])
        with sqlite3.connect(self.paths['food']) as db:db.execute("UPDATE users SET premium_until='2000-01-01T00:00:00Z'")
        self.engine.store.failed('food','offline')
        with self.engine.store.connection() as db:db.execute('UPDATE source_state SET retry_at=0')
        self.engine.poll();self.assertNotIn('food',build_ai_context(self.engine.store,str(USER),'gym',NOW)['data'])
    def test_website_session_cannot_use_miniapp_assertion(self):
        with TestClient(create_app(self.config)) as client:
            session=client.post('/api/v1/sessions',json={'source':'food','init_data':launch(source='food')}).json()
            self.assertEqual(client.post('/api/v1/website/checkout',json={},headers={'X-Progressor-Web':session['assertions']['core']}).status_code,401)
    def test_website_login_requires_explicit_bot_confirmation_and_one_time_secret(self):
        with TestClient(create_app(self.config)) as client:
            login=client.post('/api/v1/website/login').json();poll={'challenge':login['challenge'],'poll_secret':login['poll_secret']}
            self.assertFalse(client.post('/api/v1/website/poll',json=poll).json()['approved'])
            self.assertEqual(client.post('/api/v1/website/poll',json={**poll,'poll_secret':'wrong'}).status_code,401)
            body=json.dumps({'challenge':login['challenge'],'user_id':str(USER)},sort_keys=True,separators=(',',':')).encode();path='/internal/v1/website/approve'
            self.assertEqual(client.post(path,content=body,headers={'X-Progressor-Control':control_token('food',path,body,KEY)}).status_code,200)
            token=client.post('/api/v1/website/poll',json=poll).json()['token'];self.assertTrue(token)
            self.assertEqual(client.post('/api/v1/website/poll',json=poll).status_code,401)
    def test_yookassa_status_verified_before_fulfillment(self):
        from progressor_core.payments import reconcile_rub
        o=self.order(currency='RUB')
        with self.engine.store.connection() as db:db.execute('UPDATE bundle_orders SET provider_id=? WHERE id=?',('provider-id',o['id']))
        payment={'id':'provider-id','status':'succeeded','paid':True,'amount':{'value':'599.00','currency':'RUB'},'metadata':{'progressor_order':o['id'],'progressor_user':str(USER)}}
        with patch('progressor_core.payments.yookassa',AsyncMock(return_value={**payment,'paid':False})):
            with self.assertRaises(ValueError):asyncio.run(reconcile_rub(self.engine,'provider-id'))
        with patch('progressor_core.payments.yookassa',AsyncMock(return_value=payment)):asyncio.run(reconcile_rub(self.engine,'provider-id'))
        self.assertTrue(entitlements(self.engine.store,str(USER))['bundle_active'])
    def test_height_weight_respect_source_payment_consent_and_subject(self):
        with sqlite3.connect(self.paths['supply']) as db:
            db.executescript('CREATE TABLE user_health_profile(user_id INTEGER,sex_at_birth TEXT,birth_year INTEGER,height_cm REAL,weight_kg REAL,diet_type TEXT,training_sessions_per_week INTEGER,training_minutes_per_week INTEGER,updated_at_utc TEXT,created_at_utc TEXT);')
            db.execute("INSERT INTO user_health_profile VALUES(55,'m',1990,183,84,'mixed',3,180,'2026-10-07T10:00:00Z','2026-10-07T10:00:00Z')")
        self.engine.poll();ctx=build_ai_context(self.engine.store,str(USER),'gym',NOW)
        self.assertEqual(ctx['data']['supply']['reported_profile']['height_cm'],183);self.assertEqual(ctx['data']['supply']['reported_profile']['weight_kg'],84)
        self.assertNotIn('supply',build_ai_context(self.engine.store,str(OTHER),'gym',NOW)['data'] if build_ai_context(self.engine.store,str(OTHER),'gym',NOW) else {})
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE users SET consent_given=0')
        self.engine.poll();self.assertIsNone(build_ai_context(self.engine.store,str(USER),'gym',NOW)['data']['supply']['reported_profile'])
        with sqlite3.connect(self.paths['supply']) as db:db.execute("UPDATE users SET consent_given=1,premium_until_utc='2000-01-01T00:00:00Z'")
        self.engine.poll();self.assertNotIn('supply',build_ai_context(self.engine.store,str(USER),'gym',NOW)['data'])
    def test_yookassa_retry_preserves_request_and_idempotency_key(self):
        from progressor_core.payments import create_rub
        o=self.order(currency='RUB');seen=[]
        async def ambiguous(cfg,method,path,**kwargs):
            if method=='GET' and path=='me':return {'account_id':cfg.yookassa_shop,'status':'enabled','test':False,'fiscalization':{'enabled':False}}
            seen.append(kwargs);raise TimeoutError('provider_outcome_unknown')
        with patch('progressor_core.payments.yookassa',ambiguous):
            for _ in range(2):
                with self.assertRaises(TimeoutError):asyncio.run(create_rub(self.engine,o,'test@example.org'))
        self.assertEqual(seen[0],seen[1]);self.assertEqual(seen[0]['headers']['Idempotence-Key'],o['id'])
        with self.assertRaises(ValueError):asyncio.run(create_rub(self.engine,o,'changed@example.org'))
    def test_yookassa_creation_matches_selected_merchant_receipt_mode(self):
        from progressor_core.payments import create_rub
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                o=self.order(currency='RUB');sent=[]
                async def provider(cfg,method,path,**kwargs):
                    if path=='me':return {'account_id':cfg.yookassa_shop,'status':'enabled','test':False,'fiscalization':{'enabled':enabled}}
                    sent.append(kwargs['json'])
                    return {'id':'provider-'+o['id'],'status':'pending','amount':{'value':'599.00','currency':'RUB'},'metadata':kwargs['json']['metadata'],'confirmation':{'confirmation_url':'https://yoomoney.ru/checkout'}}
                with patch('progressor_core.payments.yookassa',provider):asyncio.run(create_rub(self.engine,o,'test@example.org'))
                self.assertEqual('receipt' in sent[0],enabled)
                if enabled:self.assertTrue(sent[0]['receipt']['internet'])
                with self.engine.store.connection() as db:self.assertEqual(db.execute('SELECT email FROM bundle_provider_contacts WHERE order_id=?',(o['id'],)).fetchone()[0],'test@example.org')
    def test_yookassa_disabled_merchant_never_creates_payment(self):
        from progressor_core.payments import create_rub
        o=self.order(currency='RUB');provider=AsyncMock(return_value={'account_id':self.engine.config.yookassa_shop,'status':'disabled','test':False})
        with patch('progressor_core.payments.yookassa',provider):
            with self.assertRaisesRegex(ValueError,'merchant_not_ready'):asyncio.run(create_rub(self.engine,o,'test@example.org'))
        self.assertEqual(provider.await_count,1);self.assertEqual(provider.await_args.args[1:3],('GET','me'))
    def test_yookassa_demo_merchant_never_creates_live_order(self):
        from progressor_core.payments import create_rub
        o=self.order(currency='RUB');provider=AsyncMock(return_value={'account_id':self.engine.config.yookassa_shop,'status':'enabled','test':True})
        with patch('progressor_core.payments.yookassa',provider):
            with self.assertRaisesRegex(ValueError,'merchant_not_ready'):asyncio.run(create_rub(self.engine,o,'test@example.org'))
        self.assertEqual(provider.await_count,1)
    def test_yookassa_legacy_saved_request_is_replayed_without_changes(self):
        from progressor_core.payments import create_rub
        o=self.order(currency='RUB')
        legacy={'amount':{'value':'599.00','currency':'RUB'},'metadata':{'progressor_order':o['id'],'progressor_user':str(USER)},'receipt':{'customer':{'email':'test@example.org'}}}
        with self.engine.store.connection() as db:db.execute('INSERT INTO bundle_provider_requests VALUES(?,?)',(o['id'],json.dumps(legacy)))
        provider=AsyncMock(return_value={'id':'legacy-provider','status':'pending','amount':legacy['amount'],'metadata':legacy['metadata'],'confirmation':{'confirmation_url':'https://yoomoney.ru/checkout'}})
        with patch('progressor_core.payments.yookassa',provider):asyncio.run(create_rub(self.engine,o,'test@example.org'))
        self.assertEqual(provider.await_count,1);self.assertEqual(provider.await_args.args[1:3],('POST','payments'))
        self.assertEqual(provider.await_args.kwargs['json'],legacy)
    def test_verified_partial_refund_retains_access_full_refund_revokes(self):
        from progressor_core.payments import reconcile_rub
        o=self.order(currency='RUB')
        with self.engine.store.connection() as db:db.execute('UPDATE bundle_orders SET provider_id=? WHERE id=?',('refund-payment',o['id']))
        payment={'id':'refund-payment','status':'succeeded','paid':True,'amount':{'value':'599.00','currency':'RUB'},'metadata':{'progressor_order':o['id'],'progressor_user':str(USER)}}
        with patch('progressor_core.payments.yookassa',AsyncMock(return_value={**payment,'refunded_amount':{'value':'100.00','currency':'RUB'}})):asyncio.run(reconcile_rub(self.engine,'refund-payment'))
        self.assertTrue(entitlements(self.engine.store,str(USER))['bundle_active'])
        with patch('progressor_core.payments.yookassa',AsyncMock(return_value={**payment,'refunded_amount':{'value':'599.00','currency':'RUB'}})):asyncio.run(reconcile_rub(self.engine,'refund-payment'))
        self.assertFalse(entitlements(self.engine.store,str(USER))['bundle_active'])

if __name__=='__main__':unittest.main()
