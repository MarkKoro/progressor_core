"""Legacy expiry must not poison another user's purchase/refund cache batch."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from progressor_core.billing import Billing, receipt
from progressor_core.contracts import canonical
from progressor_core.store import Store
from shared import progressor_client as client


class LegacyGrantSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.now=datetime(2030,1,1,12,tzinfo=timezone.utc)
        test=self
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return test.now if tz is None else test.now.astimezone(tz)
        def utc(value=None):return datetime.fromisoformat(value.replace('Z','+00:00')) if value else self.now
        self.addCleanup(patch.stopall)
        patch('progressor_core.billing.utc',side_effect=utc).start()
        patch('shared.progressor_client.datetime',Clock).start()
        patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1').start()
        self.store=Store(self.root/'core.sqlite3')
        self.billing=Billing(self.store)
        self.cache=self.root/'owner.sqlite3'
        client.ensure_schema(self.cache)
        self.short=self.paid('100','m1')
        self.long=self.paid('200','m3')
        self.first=self.billing.grants(source='food')['items']
        client.apply_grants(self.cache,self.first,'food')

    def paid(self,uid,plan):
        order=self.billing.quote(uid,'food',plan,'XTR',str(uuid.uuid4()),'progressor.bundle.v1')
        self.billing.settle(receipt(order,'paid',order['id']),'food')
        return order

    def test_expiry_has_new_revision_and_does_not_block_a_later_refund(self):
        self.now+=timedelta(days=31)
        self.billing.settle(receipt(self.long,'refunded',self.long['id']),'food')
        updates=self.billing.grants(source='food')['items']
        self.assertGreater(updates[0]['revision'],self.first[0]['revision'])
        client.apply_grants(self.cache,updates,'food')
        self.assertIsNone(client.bundle_until(self.cache,'100'))
        self.assertIsNone(client.bundle_until(self.cache,'200'))
        client.apply_grants(self.cache,self.first,'food')
        self.assertIsNone(client.bundle_until(self.cache,'200'),'Old paid batch must not resurrect a refund')

    def test_already_poisoned_legacy_projection_heals_without_changing_schedule(self):
        self.now+=timedelta(days=31)
        self.billing.settle(receipt(self.long,'refunded',self.long['id']),'food')
        retired=copy.deepcopy(self.first[0])
        retired['expires_at']='1970-01-01T00:00:00+00:00'
        with self.store.connection() as db:
            db.execute('UPDATE bundle_source_grants SET body=?,revision=? WHERE user_id=? AND source=?',
                       (canonical({'expires_at':retired['expires_at'],'intervals':retired['intervals']}),retired['revision'],'100','food'))
        updates=self.billing.grants(source='food')['items']
        self.assertEqual(updates[0]['revision'],retired['revision'])
        client.apply_grants(self.cache,updates,'food')
        self.assertIsNone(client.bundle_until(self.cache,'100'))
        self.assertIsNone(client.bundle_until(self.cache,'200'))

    def test_legacy_expiry_then_another_user_purchase_can_be_delivered(self):
        self.now+=timedelta(days=31)
        self.paid('300','m1')
        client.apply_grants(self.cache,self.billing.grants(source='food')['items'],'food')
        self.assertIsNotNone(client.bundle_until(self.cache,'300'))
        self.assertIsNone(client.bundle_until(self.cache,'100'))

    def test_same_revision_cannot_change_schedule_or_invent_a_new_expiry(self):
        for field,value in [('intervals',[]),('expires_at','2099-01-01T00:00:00+00:00')]:
            wrong=copy.deepcopy(self.first)
            wrong[0][field]=value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'grant_revision_conflict'):
                    client.apply_grants(self.cache,wrong,'food')
        self.assertIsNotNone(client.bundle_until(self.cache,'100'))
