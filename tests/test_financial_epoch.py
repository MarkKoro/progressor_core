import importlib.util,os,sqlite3,tempfile,unittest
from pathlib import Path
from progressor_core.store import Store
from progressor_core.billing import Billing,receipt
from progressor_core.pricing import TERMS
NEW='00000000-0000-4000-8000-000000000001'
OLD='00000000-0000-4000-8000-000000000002'

class FinancialEpoch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'core.sqlite3'
        inputs={s:{'monthly_prices':{'RUB':10000,'XTR':100},'paid_intervals':[]} for s in ('gym','food','supply')}
        self.billing=Billing(Store(self.db),lambda uid:inputs,self.root/'bundle-v2-ready')
    def test_initial_gate_denies_new_quotes_but_preserves_old_receipts(self):
        with self.assertRaises((ValueError,OSError)):self.billing.quote('123','food','m1','XTR',NEW,TERMS)
        old=self.billing.quote('123','food','m1','XTR',OLD,'progressor.bundle.v1')
        self.billing.settle(receipt(old,'paid','before-rollout'),'food')
        self.assertEqual(self.billing.order(OLD)['status'],'paid')
        (self.root/'bundle-v2-ready').write_text('2\n')
        with self.assertRaises(ValueError):self.billing.quote('123','food','m1','XTR','00000000-0000-4000-8000-000000000003','progressor.bundle.v1')
        self.assertEqual(self.billing.quote('123','food','m1','XTR',OLD,'progressor.bundle.v1')['id'],OLD)
        self.assertTrue(self.billing.personal_catalog('123')['plans'])
    def test_known_rejected_precheckout_only_releases_the_same_owned_pending_query(self):
        (self.root/'bundle-v2-ready').write_text('2')
        order=self.billing.quote('123','food','m1','XTR',NEW,TERMS)
        body={**receipt(order,'paid','placeholder'),'checkout_id':'q1'}
        self.billing.precheckout(body,'food')
        self.billing.precheckout_rejected('123',NEW,'q2','food')
        self.assertEqual(self.billing.order(NEW)['checkout_id'],'q1')
        with self.assertRaises(ValueError):self.billing.precheckout_rejected('999',NEW,'q1','food')
        self.billing.precheckout_rejected('123',NEW,'q1','food')
        self.assertIsNone(self.billing.order(NEW)['checkout_id'])
        self.billing.precheckout(body,'food');self.billing.settle(receipt(order,'paid','real-proof'),'food')
        self.billing.precheckout_rejected('123',NEW,'q1','food')
        self.assertEqual(self.billing.order(NEW)['status'],'paid')
    def test_updater_blocks_old_protocol_after_gate_or_v2_order(self):
        spec=importlib.util.spec_from_file_location('epoch_updater',Path(__file__).parents[1]/'deploy/update_all.py')
        mod=importlib.util.module_from_spec(spec)
        try:spec.loader.exec_module(mod)
        except ModuleNotFoundError:self.skipTest('Linux updater')
        paths={s:self.root/s for s in ('core','food','gym','supply')}
        for p in paths.values():p.mkdir()
        (paths['core']/'progressor_core').mkdir()
        mod.check_financial_epoch(paths,self.db)
        (self.root/'bundle-v2-ready').write_text('2')
        with self.assertRaises(mod.UpdateError):mod.check_financial_epoch(paths,self.db)
        (paths['core']/'progressor_core/billing.py').write_text('FINANCIAL_PROTOCOL=2')
        for s in ('food','gym','supply'):(paths[s]/'progressor_client.py').write_text('FINANCIAL_SCHEDULE=2')
        mod.check_financial_epoch(paths,self.db)
        self.billing.quote('123','food','m1','XTR',NEW,TERMS)
        (self.root/'bundle-v2-ready').unlink()
        (paths['food']/'progressor_client.py').write_text('FINANCIAL_SCHEDULE=1')
        with self.assertRaises(mod.UpdateError):mod.check_financial_epoch(paths,self.db)
