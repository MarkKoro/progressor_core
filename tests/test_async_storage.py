"""A blocked SQLite writer must not stop another user's request or cancel commits."""
import asyncio
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from progressor_core.app import Config, create_app
from progressor_core.auth import sign_assertion
from progressor_core.connections import save_preferences
from shared.progressor_client import canonical, control_token


class AsyncStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'core.sqlite3'
        self.key = 'test-only-async-storage-' + 'x' * 32
        self.app = create_app(Config(str(self.path), self.key, background=False))
        self.life = self.app.router.lifespan_context(self.app)
        await self.life.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.life.__aexit__(None, None, None)
        self.temp.cleanup()

    async def exercise(self, private=False, expected_revision=0):
        started = threading.Event()
        def writing(*args, **kwargs):
            started.set()
            return save_preferences(*args, **kwargs)
        body = {'action':'preferences', 'patch':{'paused':True}, 'revision':expected_revision}
        if private:
            path = '/internal/v1/connections/account'
            body['user_id'] = '80001'
            raw = canonical(body).encode()
            headers = {'X-Progressor-Control':control_token('food', path, raw, self.key), 'Content-Type':'application/json'}
        else:
            path = '/api/v1/me/connections'
            raw = json.dumps(body).encode()
            headers = {'X-Progressor-Auth':sign_assertion({'id':80001}, int(time.time()), 'core', self.key), 'Content-Type':'application/json'}
        lock = sqlite3.connect(self.path, timeout=1)
        lock.execute('BEGIN IMMEDIATE')
        saving = None
        try:
            with patch('progressor_core.connection_routes.links.save_preferences', side_effect=writing):
                saving = asyncio.create_task(self.client.post(path, content=raw, headers=headers))
                for _ in range(100):
                    if started.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(started.is_set(), 'The route must reach its actual storage operation')
                health = await asyncio.wait_for(self.client.get('/health'), timeout=.5)
                self.assertEqual(health.status_code, 200)
                self.assertFalse(saving.done(), 'SQLite write lock must remain pending while a separate request completes')
                lock.rollback()
                result = await asyncio.wait_for(saving, timeout=2)
                self.assertEqual(result.status_code, 200 if expected_revision==0 else 409)
                current = await self.client.get('/api/v1/me/connections', headers={'X-Progressor-Auth':sign_assertion({'id':80001}, int(time.time()), 'core', self.key)})
                self.assertEqual(current.json()['preferences']['revision'], 1 if expected_revision==0 else 0)
                self.assertEqual(current.json()['preferences']['paused'], expected_revision==0)
        finally:
            lock.rollback()
            lock.close()
            if saving:
                await saving

    async def test_personal_save_does_not_block_other_requests(self):
        await self.exercise()

    async def test_native_control_save_does_not_block_other_requests(self):
        await self.exercise(private=True)

    async def test_conflict_stays_409_and_does_not_commit(self):
        await self.exercise(expected_revision=7)

    async def blocked_payment_request(self, path, body, operation):
        """Exercise the real ledger under a real competing SQLite writer."""
        started = threading.Event()
        original = getattr(self.app.state.engine.billing, operation)
        def call(*args, **kwargs):
            started.set()
            return original(*args, **kwargs)
        raw = canonical(body).encode()
        headers = {'X-Progressor-Control':control_token('food', path, raw, self.key), 'Content-Type':'application/json'}
        lock = sqlite3.connect(self.path, timeout=1)
        lock.execute('BEGIN IMMEDIATE')
        task = None
        try:
            with patch.object(self.app.state.engine.billing, operation, side_effect=call):
                task = asyncio.create_task(self.client.post(path, content=raw, headers=headers))
                for _ in range(100):
                    if started.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(started.is_set())
                self.assertEqual((await asyncio.wait_for(self.client.get('/health'), .5)).status_code, 200)
                self.assertFalse(task.done())
                lock.rollback()
                response = await asyncio.wait_for(task, 2)
                self.assertEqual(response.status_code, 200, response.text)
                return response.json()
        finally:
            lock.rollback()
            lock.close()
            if task: await task

    async def test_native_quote_waits_without_stalling_health_and_preserves_idempotency(self):
        body = dict(user_id='80001', plan='m1', order_id=str(uuid.uuid4()), terms='progressor.bundle.v1')
        order = await self.blocked_payment_request('/internal/v1/bundle/quote', body, 'quote')
        again = self.app.state.engine.billing.quote('80001', 'food', 'm1', 'XTR', body['order_id'], body['terms'])
        self.assertEqual(order['id'], again['id'])
        self.assertEqual(order['amount'], again['amount'])

    async def test_receipt_waits_without_stalling_health_and_still_settles_once(self):
        from progressor_core.billing import receipt
        billing = self.app.state.engine.billing
        order = billing.quote('80001', 'food', 'm1', 'XTR', str(uuid.uuid4()), 'progressor.bundle.v1')
        body = receipt(order, 'paid', 'isolated-charge')
        await self.blocked_payment_request('/internal/v1/bundle/receipt', body, 'settle')
        billing.settle(body, 'food')
        with self.app.state.engine.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bundle_receipts').fetchone()[0], 1)
        self.assertEqual(billing.order(order['id'])['status'], 'paid')

    async def test_cancel_waits_without_stalling_health_and_keeps_owned_order(self):
        billing = self.app.state.engine.billing
        order = billing.quote('80001', 'food', 'm1', 'XTR', str(uuid.uuid4()), 'progressor.bundle.v1')
        out = await self.blocked_payment_request('/internal/v1/bundle/cancel', dict(user_id='80001', order_id=order['id']), 'cancel')
        self.assertEqual(out['status'], 'canceled')
        self.assertEqual(billing.order(order['id'])['user_id'], '80001')
