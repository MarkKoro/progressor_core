"""Bundle ledger v1. Core owns payments; domain-owned caches provide offline access.

Only verified successful Telegram updates or an authenticated YooKassa GET grant access.
Checkout redirects, precheckout approval and unverified webhooks never grant access.
"""
import json
import os
import time
import uuid
from datetime import datetime,timedelta,timezone
from .contracts import SOURCES,canonical,subject

PLANS = {'m1':{'label':'30 дней','days':30,'RUB':59900,'XTR':450},'m3':{'label':'90 дней','days':90,'RUB':159000,'XTR':1190},'m6':{'label':'180 дней','days':180,'RUB':299000,'XTR':2250},'y1':{'label':'365 дней','days':365,'RUB':549000,'XTR':4190}}
SCHEMA = '''CREATE TABLE IF NOT EXISTS bundle_orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,plan TEXT NOT NULL,currency TEXT NOT NULL,amount INTEGER NOT NULL,days INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,checkout_id TEXT,charge_id TEXT,provider_id TEXT,paid_at TEXT,UNIQUE(source,charge_id));
CREATE TABLE IF NOT EXISTS bundle_receipts(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,source TEXT NOT NULL,kind TEXT NOT NULL,charge_id TEXT NOT NULL,body TEXT NOT NULL,received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_entitlements(user_id TEXT PRIMARY KEY,expires_at TEXT NOT NULL,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_refunds(provider_id TEXT PRIMARY KEY,payment_id TEXT NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_requests(order_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_contacts(order_id TEXT PRIMARY KEY,email TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_checks(payment_id TEXT PRIMARY KEY,checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS website_logins(id TEXT PRIMARY KEY,poll_hash TEXT NOT NULL,created_at REAL NOT NULL,user_id TEXT,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS website_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at REAL NOT NULL);
'''

def utc(value=None): return datetime.fromisoformat(value.replace('Z','+00:00')) if value else datetime.now(timezone.utc)

class Billing:
    def __init__(self,store):
        self.store=store
        with store.connection() as db: db.executescript(SCHEMA)

    def catalog(self):
        items=[]
        for plan,defaults in PLANS.items():
            row={**defaults,'id':plan}
            for currency in ('RUB','XTR'):
                value=int(os.getenv('PROGRESSOR_PRICE_'+plan.upper()+'_'+currency,str(defaults[currency])))
                if not 1<=value<=10000000: raise ValueError('invalid_bundle_price')
                row[currency]=value
            items.append(row)
        return {'schema_version':1,'plans':items,'included':list(SOURCES),'auto_renew':False,'limits':'Лимиты ИИ и возможности каждого продукта сохраняются. Отдельные подписки действуют независимо. Общая подписка продлевает общий срок; пересекающиеся сроки не суммируются с отдельными подписками.','terms_version':'progressor.bundle.v1'}

    def quote(self,user_id,source,plan,currency,order_id,terms):
        user_id=subject(user_id)
        if source not in SOURCES or currency not in ('XTR','RUB') or terms!='progressor.bundle.v1': raise ValueError('invalid_bundle_quote')
        uuid.UUID(order_id)
        price=next((p for p in self.catalog()['plans'] if p['id']==plan),None)
        if not price: raise ValueError('invalid_bundle_plan')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone()
            if old:
                if (old['user_id'],old['source'],old['plan'],old['currency'])!=(user_id,source,plan,currency): raise ValueError('quote_conflict')
                return dict(old)
            db.execute('INSERT INTO bundle_orders(id,user_id,source,plan,currency,amount,days,status,created_at) VALUES(?,?,?,?,?,?,?,\'pending\',?)',(order_id,user_id,source,plan,currency,price[currency],price['days'],utc().isoformat()))
            return dict(db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone())

    def order(self,order_id,user_id=None):
        with self.store.connection() as db: row=db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone()
        if not row or (user_id is not None and row['user_id']!=str(user_id)): raise ValueError('order_not_found')
        return dict(row)

    def validate_receipt(self,order,body,source):
        if body.get('source')!=source or order['source']!=source or str(body.get('user_id'))!=order['user_id'] or body.get('currency')!=order['currency'] or type(body.get('amount')) is not int or body['amount']!=order['amount'] or not isinstance(body.get('charge_id'),str) or not 1<=len(body['charge_id'])<=256: raise ValueError('receipt_mismatch')
        if body.get('payload')!='progressor:'+source+':'+order['id']: raise ValueError('receipt_payload_mismatch')

    def precheckout(self,body,source):
        order=self.order(body['order_id']); self.validate_receipt(order,{**body,'charge_id':'precheckout'},source)
        checkout_id=body.get('checkout_id')
        if not isinstance(checkout_id,str) or not checkout_id or len(checkout_id)>256: raise ValueError('invalid_checkout')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            order=dict(db.execute('SELECT * FROM bundle_orders WHERE id=?',(order['id'],)).fetchone())
            if order['status']!='pending' or utc()-utc(order['created_at'])>timedelta(hours=24) or order['currency']!='XTR': raise ValueError('checkout_expired')
            if order['checkout_id'] and order['checkout_id']!=checkout_id: raise ValueError('checkout_already_reserved')
            db.execute('UPDATE bundle_orders SET checkout_id=? WHERE id=?',(checkout_id,order['id']))
        return {'ok':True}

    def _rebuild(self,db,user_id):
        end=datetime(1970,1,1,tzinfo=timezone.utc)
        for row in db.execute("SELECT paid_at,days FROM bundle_orders WHERE user_id=? AND status='paid' ORDER BY paid_at,id",(user_id,)):
            end=max(end,utc(row['paid_at']))+timedelta(days=row['days'])
        expires=end.isoformat()
        old=db.execute('SELECT * FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()
        if old and old['expires_at']==expires: return
        db.execute('INSERT INTO bundle_entitlements VALUES(?,?,1) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at,revision=bundle_entitlements.revision+1',(user_id,expires))

    def settle(self,body,source,verified_rub=False):
        if body.get('kind') not in ('paid','refunded'): raise ValueError('invalid_receipt_kind')
        order=self.order(body['order_id']); self.validate_receipt(order,body,source)
        if order['currency']=='RUB' and not verified_rub: raise ValueError('unverified_rub_receipt')
        receipt_id=source+':'+body['kind']+':'+body['charge_id']
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT body FROM bundle_receipts WHERE id=?',(receipt_id,)).fetchone()
            if old:
                if old['body']!=canonical(body): raise ValueError('receipt_conflict')
                return {'status':'duplicate'}
            current=db.execute('SELECT * FROM bundle_orders WHERE id=?',(order['id'],)).fetchone()
            if current['charge_id'] and current['charge_id']!=body['charge_id']: raise ValueError('charge_conflict')
            if current['status']=='paid' and body['kind']=='paid': raise ValueError('order_already_paid')
            # A refund may precede its delayed successful-payment update. Never resurrect it.
            status='refunded' if body['kind']=='refunded' or current['status']=='refunded' else 'paid'
            paid_at=current['paid_at'] or utc().isoformat()
            db.execute('INSERT INTO bundle_receipts VALUES(?,?,?,?,?,?,?)',(receipt_id,order['id'],source,body['kind'],body['charge_id'],canonical(body),utc().isoformat()))
            db.execute('UPDATE bundle_orders SET status=?,charge_id=?,paid_at=? WHERE id=?',(status,body['charge_id'],paid_at,order['id']))
            self._rebuild(db,order['user_id'])
        return {'status':status}

    def grants(self,after=''):
        with self.store.connection() as db: rows=[dict(r) for r in db.execute('SELECT * FROM bundle_entitlements WHERE user_id>? ORDER BY user_id LIMIT 501',(after,))]
        return {'items':rows[:500],'next':rows[499]['user_id'] if len(rows)>500 else None}

    def drain_receipts(self,source,path):
        # Transitional read-only outbox. Owner records trusted Telegram updates atomically.
        from .adapters import read_only
        with read_only(path) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='progressor_payment_outbox'").fetchone(): return
            rows=[r['body'] for r in db.execute('SELECT body FROM progressor_payment_outbox ORDER BY created_at,receipt_id')]
        for raw in rows:
            try: self.settle(json.loads(raw),source)
            except (ValueError,KeyError,TypeError):
                import logging
                logging.getLogger('progressor').error('bundle_receipt_rejected source=%s',source)

def receipt(order,kind,charge_id):
    return {'source':order['source'],'order_id':order['id'],'user_id':order['user_id'],'currency':order['currency'],'amount':order['amount'],'payload':'progressor:'+order['source']+':'+order['id'],'kind':kind,'charge_id':charge_id}
