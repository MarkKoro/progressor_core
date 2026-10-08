import copy
import os
import tempfile
import time
import unittest
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from progressor_core.store import Store
from progressor_core.billing import Billing,receipt
from progressor_core.subscription_notices import SubscriptionNotices
from progressor_core.access import entitlements

class SubscriptionNoticesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.temp.name)
        self.now=datetime(2026,10,8,12,tzinfo=timezone.utc);self.uid='123'
        self.store=Store(self.root/'core.db');self.billing=Billing(self.store)
        with self.store.connection() as db:db.execute('INSERT INTO identities VALUES(?,?)',(self.uid,self.now.isoformat()))
        self.entities=[{'entity_id':'profile:'+s,'source':s,'payload':{'paid_until':(self.now+timedelta(days=d)).isoformat()}} for s,d in [('gym',20),('food',2),('supply',10)]]
        self.state={s:{'status':'ok','last_success':time.time()} for s in ('gym','food','supply')}
        self.store.data=lambda uid:(self.entities,[],self.state)
        self.meta={s:{'known':True,'count':c,'last_at':'2026-10-08T11:00:00Z','timezone':'UTC'} for s,c in [('gym',10),('food',5),('supply',1)]}
        self.notices=SubscriptionNotices(self.store,metadata=lambda uid,now:copy.deepcopy(self.meta))
    def tearDown(self):self.temp.cleanup()
    def test_input_flow_deferral_does_not_exhaust_attempts_or_switch_sender(self):
        for n in range(6):
            instant=self.now+timedelta(seconds=65*n)
            item=self.notices.claim('gym',now=instant)['items'][0]
            self.notices.acknowledge('gym',item['event_key'],'deferred',now=instant)
            self.assertEqual(self.notices.claim('food',now=instant+timedelta(seconds=61))['items'],[])
        items=self.notices.claim('gym',now=self.now+timedelta(seconds=400))['items']
        self.assertEqual(len(items),1)
        self.notices.acknowledge('gym',items[0]['event_key'],'sent',now=self.now+timedelta(seconds=400))
        self.assertEqual(self.notices.claim('gym',now=self.now+timedelta(hours=2))['items'],[])
    def bundle(self):
        o=self.billing.quote(self.uid,'food','m1','XTR',str(uuid.uuid4()),'progressor.bundle.v1')
        self.billing.settle(receipt(o,'paid','a'),'food')
        with self.store.connection() as db:
            db.execute('UPDATE bundle_orders SET paid_at=? WHERE id=?',((self.now-timedelta(days=28)).isoformat(),o['id']))
            self.billing._rebuild(db,self.uid)
    def test_individual_expiry_one_recent_frequent_sender(self):
        self.assertEqual(self.notices.claim('food',now=self.now)['items'],[])
        items=self.notices.claim('gym',now=self.now)['items'];self.assertEqual(len(items),1)
        self.assertIn('Еда',items[0]['text']);self.assertIn('Остальные',items[0]['text'])
        self.assertEqual(self.notices.claim('supply',now=self.now)['items'],[])
    def test_common_expiry_one_warning_and_native_survives(self):
        self.bundle();items=self.notices.claim('gym',now=self.now)['items'];self.assertEqual(len(items),1)
        self.assertEqual(items[0]['kind'],'bundle');self.assertIn('Тренировки',items[0]['text']);self.assertIn('БАДы',items[0]['text'])
        access=entitlements(self.store,self.uid,self.now+timedelta(days=3),self.entities)
        self.assertFalse(access['domains']['food']);self.assertTrue(access['domains']['gym']);self.assertTrue(access['domains']['supply'])
        self.assertEqual(len(self.entities),3) # expiry never purges owned history
    def test_longer_bundle_suppresses_native_expiry(self):
        self.bundle()
        with self.store.connection() as db:
            db.execute('UPDATE bundle_orders SET paid_at=? WHERE user_id=?',(self.now.isoformat(),self.uid));self.billing._rebuild(db,self.uid)
        self.assertEqual(self.notices.claim('gym',now=self.now)['items'],[])
    def test_restart_and_unknown_delivery_never_replay(self):
        item=self.notices.claim('gym',now=self.now)['items'][0]
        self.notices.acknowledge('gym',item['event_key'],'uncertain',now=self.now)
        resumed=SubscriptionNotices(self.store,metadata=lambda uid,now:self.meta)
        self.assertEqual(resumed.claim('gym',now=self.now+timedelta(hours=1))['items'],[])
    def test_lost_ack_reserved_never_changes_sender(self):
        self.notices.claim('gym',now=self.now)
        self.meta['food']['count']=100
        for source in ('gym','food','supply'):self.assertEqual(self.notices.claim(source,now=self.now+timedelta(minutes=1))['items'],[])
    def test_confirmed_forbidden_can_fallback_once(self):
        item=self.notices.claim('gym',now=self.now)['items'][0]
        self.notices.acknowledge('gym',item['event_key'],'blocked',now=self.now)
        next_items=self.notices.claim('food',now=self.now+timedelta(minutes=1))['items'];self.assertEqual(len(next_items),1)
        self.notices.acknowledge('food',item['event_key'],'sent',now=self.now)
        self.assertEqual(self.notices.claim('supply',now=self.now)['items'],[])
    def test_confirmed_retry_after_same_event_only(self):
        item=self.notices.claim('gym',now=self.now)['items'][0]
        self.notices.acknowledge('gym',item['event_key'],'retry',retry_after=120,now=self.now)
        self.assertEqual(self.notices.claim('gym',now=self.now+timedelta(seconds=60))['items'],[])
        self.assertEqual(self.notices.claim('gym',now=self.now+timedelta(seconds=122))['items'][0]['event_key'],item['event_key'])
    def test_quiet_hours_and_renewal_no_old_warning(self):
        self.assertEqual(self.notices.claim('gym',now=self.now.replace(hour=23))['items'],[])
        self.entities[1]['payload']['paid_until']=(self.now+timedelta(days=32)).isoformat()
        self.assertEqual(self.notices.claim('gym',now=self.now)['items'],[])
    def test_wrong_sender_ack_and_stale_source_rejected(self):
        item=self.notices.claim('gym',now=self.now)['items'][0]
        with self.assertRaises(ValueError):self.notices.acknowledge('food',item['event_key'],'sent',now=self.now)
        self.entities[1]['payload']['paid_until']=(self.now+timedelta(days=1)).isoformat()
        self.state['food']['last_success']=time.time()-121
        self.assertEqual(self.notices.claim('gym',now=self.now)['items'],[])
    def test_no_activity_fallback_and_same_day_native_group(self):
        for s in self.meta:self.meta[s].update(count=0,last_at='')
        self.entities[2]['payload']['paid_until']=(self.now+timedelta(days=2,hours=1)).isoformat()
        items=self.notices.claim('food',now=self.now)['items'];self.assertEqual(len(items),1)
        self.assertIn('Еда',items[0]['text']);self.assertIn('БАДы',items[0]['text'])
