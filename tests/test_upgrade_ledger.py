import concurrent.futures
import copy
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from progressor_core.store import Store
from progressor_core.billing import Billing,receipt
from progressor_core.access import entitlements
from progressor_core.pricing import TERMS
from shared.progressor_client import ensure_schema,apply_grants,bundle_until
from shared.native_subscription import record_paid,record_activity
import sqlite3

class UpgradeLedger(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.temp.name)
        self.now=datetime.now(timezone.utc)
        self.inputs={s:{'monthly_prices':{'RUB':p,'XTR':x},'paid_intervals':[]} for s,p,x in [('gym',10000,80),('food',39900,266),('supply',20000,250)]}
        self.inputs['food']['paid_intervals']=[{'grant_id':'food:paid','starts_at':(self.now-timedelta(days=10)).isoformat(),'expires_at':(self.now+timedelta(days=20)).isoformat()}]
        self.store=Store(self.root/'core.db');self.billing=Billing(self.store,lambda uid:copy.deepcopy(self.inputs))
    def tearDown(self):self.temp.cleanup()
    def quote(self,plan='m1',source='food',currency='XTR'):
        return self.billing.quote('123',source,plan,currency,str(uuid.uuid4()),TERMS)
    def test_exact_missing_intervals_and_original_refund(self):
        order=self.quote();self.assertLess(order['amount'],450)
        self.billing.settle(receipt(order,'paid','a'),'food')
        access=entitlements(self.store,'123',self.now+timedelta(hours=1),[])
        self.assertTrue(access['domains']['gym']);self.assertTrue(access['domains']['supply'])
        self.assertFalse(access['domains']['food']) # refunded native: no free 20 days
        later=entitlements(self.store,'123',self.now+timedelta(days=21),[])
        self.assertTrue(all(later['domains'].values()))
        self.billing.settle(receipt(order,'refunded','a'),'food')
        self.assertFalse(any(entitlements(self.store,'123',self.now+timedelta(days=21),[])['domains'].values()))
    def test_two_periods_and_separate_currency_weights(self):
        catalog=self.billing.personal_catalog('123');plans={p['id']:p for p in catalog['plans']}
        self.assertIn('align',plans);self.assertLess(plans['align']['XTR'],plans['m1']['XTR'])
        self.assertNotAlmostEqual(plans['m1']['prices']['RUB']['credit_amount']/59900,plans['m1']['prices']['XTR']['credit_amount']/450,places=2)
    def test_user_wide_concurrent_checkout_reservation(self):
        def attempt(source):
            try:return self.quote(source=source)['id']
            except ValueError:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(attempt,['gym','food','supply']))
        self.assertEqual(sum(r is not None for r in results),1)
    def test_same_checkout_retry_price_immutable_and_cancel(self):
        first=self.quote();self.inputs['food']['paid_intervals']=[]
        self.assertEqual(first['id'],self.quote()['id'])
        self.billing.cancel('123',first['id']);self.assertEqual(self.quote()['amount'],450)
        with self.assertRaises(ValueError):self.billing.cancel('124',first['id'])
    def test_reserved_accepted_payment_cannot_cancel_or_start_another(self):
        order=self.quote();self.billing.precheckout({**receipt(order,'paid','unused'),'checkout_id':'q'},'food')
        with self.assertRaises(ValueError):self.billing.cancel('123',order['id'])
        with self.assertRaises(ValueError):self.quote(source='gym')
    def test_expired_quote_cannot_charge_but_real_late_receipt_fulfils(self):
        order=self.quote();frozen=json.loads(order['pricing_json']);frozen['quote_valid_until']=(self.now-timedelta(minutes=1)).isoformat()
        with self.store.connection() as db:db.execute('UPDATE bundle_orders SET pricing_json=? WHERE id=?',(json.dumps(frozen),order['id']))
        with self.assertRaises(ValueError):self.billing.precheckout({**receipt(order,'paid','unused'),'checkout_id':'q'},'food')
        self.assertEqual(self.billing.settle(receipt(order,'paid','actually-paid'),'food')['status'],'paid')
        self.assertTrue(entitlements(self.store,'123')['domains']['gym'])
    def test_duplicate_refund_before_success_and_no_reusable_credit(self):
        first=self.quote();self.billing.settle(receipt(first,'refunded','a'),'food');self.billing.settle(receipt(first,'paid','a'),'food')
        self.assertFalse(entitlements(self.store,'123')['bundle_active'])
        order=self.quote();self.billing.settle(receipt(order,'paid','b'),'food')
        self.assertEqual(self.billing.settle(receipt(order,'paid','b'),'food')['status'],'duplicate')
        second=self.quote();self.assertEqual(second['amount'],450)
    def test_refund_does_not_move_later_period_or_erase_history(self):
        a=self.quote();self.billing.settle(receipt(a,'paid','a'),'food');b=self.quote();self.billing.settle(receipt(b,'paid','b'),'food')
        before=self.billing.order(b['id'])['pricing_json']
        self.billing.settle(receipt(a,'refunded','a'),'food')
        self.assertEqual(before,self.billing.order(b['id'])['pricing_json'])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM bundle_receipts').fetchone()[0],3)
    def test_offline_scheduled_cache_no_early_grant_boundary_and_refund(self):
        order=self.quote();self.billing.settle(receipt(order,'paid','a'),'food')
        path=self.root/'owner.db';ensure_schema(path)
        grants=self.billing.grants(source='food');apply_grants(path,grants['items'],'food')
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):
            self.assertIsNone(bundle_until(path,'123'))
            class Later(datetime):
                @classmethod
                def now(cls,tz=None):return self.now+timedelta(days=21)
            with patch('shared.progressor_client.datetime',Later):self.assertIsNotNone(bundle_until(path,'123'))
        self.billing.settle(receipt(order,'refunded','a'),'food');new=self.billing.grants(source='food');apply_grants(path,new['items'],'food');apply_grants(path,grants['items'],'food')
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):self.assertIsNone(bundle_until(path,'123'))
    def test_grant_source_tampering_and_revision_conflict_rejected(self):
        order=self.quote();self.billing.settle(receipt(order,'paid','a'),'food');path=self.root/'owner.db';ensure_schema(path)
        items=self.billing.grants(source='gym')['items']
        with self.assertRaises(ValueError):apply_grants(path,items,'food')
        apply_grants(path,items,'gym')
        wrong=copy.deepcopy(items);wrong[0]['intervals']=[]
        with self.assertRaises(ValueError):apply_grants(path,wrong,'gym')
    def test_exact_paid_proof_idempotent_and_activity_dedup(self):
        path=self.root/'owner.db'
        with closing(sqlite3.connect(path)) as db,db:
            args=('food:1','123',self.now,self.now+timedelta(days=30),'XTR',266)
            record_paid(db,*args);record_paid(db,*args)
            with self.assertRaises(ValueError):record_paid(db,*args[:-1],267)
            self.assertEqual(db.execute('SELECT count(*) FROM progressor_native_paid_grants').fetchone()[0],1)
        record_activity(path,'123',1,self.now);record_activity(path,'123',1,self.now);record_activity(path,'123',2,self.now)
        with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count FROM progressor_bot_activity').fetchone()[0],2)
