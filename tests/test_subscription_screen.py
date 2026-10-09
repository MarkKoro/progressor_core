"""Owned status, stale/trial/common combinations and authenticated display API."""
import json, os, sqlite3, tempfile, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from progressor_core.app import Config, create_app
from progressor_core.auth import sign_assertion
from progressor_core.subscriptions import subscription_view
from test_integration import fixture, USER, OTHER, KEY, TOKENS


class SubscriptionScreen(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        root=Path(self.tmp.name);self.paths=fixture(root)
        with sqlite3.connect(self.paths['food']) as db:
            db.execute('ALTER TABLE users ADD COLUMN trial_until TEXT')
            db.execute('ALTER TABLE users ADD COLUMN trial_used_count INTEGER DEFAULT 0')
        with sqlite3.connect(self.paths['supply']) as db:db.execute('ALTER TABLE users ADD COLUMN starter_trial_until_utc TEXT')
        self.client=TestClient(create_app(Config(str(root/'core.db'),KEY,self.paths,TOKENS,background=False)))
        self.client.__enter__();self.engine=self.client.app.state.engine;self.engine.poll()
        self.auth={'X-Progressor-Auth':sign_assertion({'id':USER},int(time.time()),'core',KEY)}
    def tearDown(self):self.client.__exit__(None,None,None);self.tmp.cleanup()
    def view(self):return self.client.get('/api/v1/me/subscriptions',headers=self.auth).json()
    def products(self):return {p['source']:p for p in self.view()['products']}
    def test_all_eight_native_combinations_are_clear_without_a_bundle(self):
        for mask in range(8):
            for bit,source in enumerate(('gym','food','supply')):
                end='2030-01-01T00:00:00Z' if mask&(1<<bit) else '2000-01-01T00:00:00Z'
                with sqlite3.connect(self.paths[source]) as db:
                    if source=='gym':db.execute('UPDATE subscriptions SET expires_at=?',(end,))
                    elif source=='food':db.execute('UPDATE users SET premium_until=?',(end,))
                    else:db.execute('UPDATE users SET premium_until_utc=?',(end,))
            self.engine.poll();v=self.view()
            self.assertEqual(v['premium_count'],mask.bit_count())
            self.assertFalse(v['bundle']['active'])
            for bit,p in enumerate(v['products']):self.assertEqual(p['premium_active'],bool(mask&(1<<bit)))
    def test_trials_are_visible_but_do_not_claim_paid_cross_context(self):
        for source,column in [('food','trial_until'),('supply','starter_trial_until_utc')]:
            with sqlite3.connect(self.paths[source]) as db:
                db.execute('UPDATE users SET '+('premium_until' if source=='food' else 'premium_until_utc')+"='2000-01-01T00:00:00Z'")
                db.execute('UPDATE users SET '+column+"='2030-01-01T00:00:00Z'")
        self.engine.poll();products=self.products()
        for source in ('food','supply'):
            self.assertEqual(products[source]['state'],'trial')
            self.assertFalse(products[source]['cross_context_active'])
    def test_stale_source_is_unknown_and_cannot_be_mistaken_for_no_purchase(self):
        self.engine.store.failed('food','offline')
        product=self.products()['food']
        self.assertEqual(product['state'],'unknown');self.assertIsNone(product['native_until'])
        self.assertIn('food',self.view()['unknown_products'])
    def test_bundle_stays_known_with_stale_source_but_new_native_state_is_unknown(self):
        now=datetime.now(timezone.utc);until=(now+timedelta(days=20)).isoformat()
        with self.engine.store.connection() as db:
            db.execute('INSERT INTO bundle_entitlements VALUES(?,?,1)',(str(USER),until))
            for source in self.paths:db.execute('INSERT INTO bundle_component_intervals VALUES(?,?,?,?,?)',('test',str(USER),source,now.isoformat(),until))
        self.engine.store.failed('food','offline');product=self.products()['food']
        self.assertEqual(product['kind'],'bundle');self.assertTrue(product['premium_active'])
        self.assertFalse(product['native_fresh']);self.assertFalse(product['cross_context_active'])
    def test_display_requires_owned_identity_and_does_not_disclose_health_data(self):
        self.assertEqual(self.client.get('/api/v1/me/subscriptions').status_code,401)
        data=self.client.get('/api/v1/me/subscriptions?user_id='+str(OTHER),headers=self.auth).json()
        self.assertEqual(data['premium_count'],3)
        serialized=json.dumps(data)
        for key in ('reported_profile','observations','lab_reports','meals','consent_given'):
            self.assertNotIn('"'+key+'"',serialized)
        other={'X-Progressor-Auth':sign_assertion({'id':OTHER},int(time.time()),'core',KEY)}
        self.assertEqual(self.client.get('/api/v1/me/subscriptions',headers=other).json()['premium_count'],1)
