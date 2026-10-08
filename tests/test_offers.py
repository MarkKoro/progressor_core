import itertools,json,os,sqlite3,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from test_integration import fixture,USER,NOW
from progressor_core.store import Store
from progressor_core.adapters import snapshot
from progressor_core.context import build_context
from progressor_core.offers import bundle_preview


class NativeOffers(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'));self.root=Path(self.tmp.name)
        self.paths=fixture(self.root);self.store=Store(self.root/'core.db')
    def tearDown(self):self.tmp.cleanup()
    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))
    def paid(self,bits):
        with sqlite3.connect(self.paths['gym']) as db:db.execute('UPDATE subscriptions SET expires_at=?',('2030-01-01T00:00:00Z' if bits[0] else '2000-01-01T00:00:00Z',))
        with sqlite3.connect(self.paths['food']) as db:db.execute('UPDATE users SET is_premium=?',(bits[1],))
        with sqlite3.connect(self.paths['supply']) as db:db.execute('UPDATE users SET premium_until_utc=?',('2030-01-01T00:00:00Z' if bits[2] else None,))
        self.sync()
    def test_all_eight_combinations_each_native_entry(self):
        for bits in itertools.product((False,True),repeat=3):
            self.paid(bits)
            for i,target in enumerate(('gym','food','supply')):
                c=build_context(self.store,str(USER),NOW,target=target)
                preview=c['offer_preview']
                self.assertEqual(preview is None,all(bits))
                if preview:
                    self.assertFalse(preview['is_personal_result']);self.assertEqual(preview['kind'],'locked_example')
                    self.assertEqual(preview['action']['kind'],'bundle')
                for source,key in [('food','nutrition'),('supply','supply'),('gym','activity')]:
                    if not bits[('gym','food','supply').index(source)] or not bits[i]:self.assertIsNone(c[key])
    def test_trial_is_offer_access_only_not_cross_data_entitlement(self):
        self.paid((True,False,False))
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('ALTER TABLE users ADD COLUMN trial_until TEXT');db.execute('ALTER TABLE users ADD COLUMN trial_used_count INTEGER')
            db.execute('UPDATE users SET trial_until=?,trial_used_count=0',((NOW+timedelta(days=1)).isoformat(),))
        self.sync();c=build_context(self.store,str(USER),NOW,target='food')
        self.assertEqual(c['offer_preview']['offer_reason'],'complete_three_products')
        self.assertIn('food',c['offer_preview']['current_access_domains'])
        self.assertFalse(c['access']['domains']['food']);self.assertIsNone(c['activity'])
    def test_exhausted_trial_is_not_presented_as_active_access(self):
        self.paid((True,False,False))
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('ALTER TABLE users ADD COLUMN trial_until TEXT');db.execute('ALTER TABLE users ADD COLUMN trial_used_count INTEGER')
            db.execute('UPDATE users SET trial_until=?,trial_used_count=6',((NOW+timedelta(days=1)).isoformat(),))
        self.sync();c=build_context(self.store,str(USER),NOW,target='food')
        self.assertNotIn('food',c['offer_preview']['current_access_domains'])
    def test_gift_expiry_counts_like_native_subscription(self):
        self.paid((False,True,True))
        c=build_context(self.store,str(USER),NOW,target='food')
        self.assertEqual(c['offer_preview']['missing_domains'],['gym'])
        self.assertEqual(c['offer_preview']['offer_reason'],'complete_three_products')
    def test_bundle_or_three_native_subscriptions_have_no_locked_example(self):
        self.paid((True,True,True))
        self.assertIsNone(build_context(self.store,str(USER),NOW,target='gym')['offer_preview'])
    def test_hide_is_persistent_account_target_scoped_and_keeps_personal_hint(self):
        self.paid((True,True,False));self.store.dismiss_offers(str(USER),'food')
        c=build_context(Store(self.root/'core.db'),str(USER),NOW,target='food')
        self.assertIsNone(c['offer_preview']);self.assertIsNotNone(c['inline_hint'])
        self.assertFalse(self.store.offers_dismissed(str(USER+1),'food'))
        self.assertFalse(self.store.offers_dismissed(str(USER),'gym'))
    def test_personal_hint_dismissal_is_not_replaced_by_an_ad(self):
        self.paid((True,True,False));self.store.dismiss_hints(str(USER),'food')
        c=build_context(self.store,str(USER),NOW,target='food')
        self.assertIsNone(c['inline_hint']);self.assertIsNone(c['offer_preview'])
    def test_example_never_uses_unavailable_private_payload(self):
        preview=bundle_preview([{'source':'supply','entity_id':'lab:private','payload':{'secret':'PRIVATE HEALTH'}}],
            {'domains':{'gym':True,'food':True,'supply':False}},'food',NOW)
        self.assertNotIn('PRIVATE HEALTH',json.dumps(preview))
        self.assertIsNone(bundle_preview([],{'domains':{'gym':True,'food':False,'supply':False}},'gym',NOW,['gym']))
