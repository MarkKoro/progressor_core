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
from . import pricing
from pathlib import Path

FINANCIAL_PROTOCOL = 2

PLANS = {'m1':{'label':'30 дней','days':30,'RUB':59900,'XTR':450},'m3':{'label':'90 дней','days':90,'RUB':159000,'XTR':1190},'m6':{'label':'180 дней','days':180,'RUB':299000,'XTR':2250},'y1':{'label':'365 дней','days':365,'RUB':549000,'XTR':4190}}
SCHEMA = '''CREATE TABLE IF NOT EXISTS bundle_orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,plan TEXT NOT NULL,currency TEXT NOT NULL,amount INTEGER NOT NULL,days INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,checkout_id TEXT,charge_id TEXT,provider_id TEXT,paid_at TEXT,UNIQUE(source,charge_id));
CREATE TABLE IF NOT EXISTS bundle_receipts(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,source TEXT NOT NULL,kind TEXT NOT NULL,charge_id TEXT NOT NULL,body TEXT NOT NULL,received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_entitlements(user_id TEXT PRIMARY KEY,expires_at TEXT NOT NULL,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_component_intervals(order_id TEXT NOT NULL,user_id TEXT NOT NULL,source TEXT NOT NULL,starts_at TEXT NOT NULL,expires_at TEXT NOT NULL,PRIMARY KEY(order_id,source,starts_at));
CREATE INDEX IF NOT EXISTS bundle_intervals_user ON bundle_component_intervals(user_id,source);
CREATE TABLE IF NOT EXISTS bundle_source_grants(user_id TEXT NOT NULL,source TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(user_id,source));
CREATE TABLE IF NOT EXISTS bundle_refunds(provider_id TEXT PRIMARY KEY,payment_id TEXT NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_requests(order_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_contacts(order_id TEXT PRIMARY KEY,email TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bundle_provider_checks(payment_id TEXT PRIMARY KEY,checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS website_logins(id TEXT PRIMARY KEY,poll_hash TEXT NOT NULL,created_at REAL NOT NULL,user_id TEXT,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS website_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at REAL NOT NULL);
'''

def utc(value=None): return datetime.fromisoformat(value.replace('Z','+00:00')) if value else datetime.now(timezone.utc)

class Billing:
    def __init__(self,store,pricing_provider=None,upgrade_gate=None):
        self.store=store;self.pricing_provider=pricing_provider;self.upgrade_gate=upgrade_gate
        with store.connection() as db:
            db.executescript(SCHEMA)
            if 'pricing_json' not in {r[1] for r in db.execute('PRAGMA table_info(bundle_orders)')}:
                db.execute('ALTER TABLE bundle_orders ADD COLUMN pricing_json TEXT')
            for row in db.execute("SELECT DISTINCT user_id FROM bundle_orders o WHERE status='paid' AND pricing_json IS NULL AND NOT EXISTS(SELECT 1 FROM bundle_component_intervals i WHERE i.order_id=o.id)").fetchall():
                self._rebuild(db,row['user_id'])

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

    def personal_catalog(self,user_id):
        self._upgrades_ready()
        user_id=subject(user_id)
        if not self.pricing_provider:raise ValueError('native_pricing_unavailable')
        inputs=self.pricing_provider(user_id);catalog=self.catalog();now=utc()
        with self.store.connection() as db:
            row=db.execute('SELECT expires_at FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()
            pending=db.execute("SELECT id,source,plan,currency,amount,checkout_id,provider_id FROM bundle_orders WHERE user_id=? AND status='pending' AND pricing_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",(user_id,)).fetchone()
        scheduled=row['expires_at'] if row and utc(row['expires_at'])>now else None
        plans=[]
        for plan in ('align',*PLANS):
            variants={}
            for currency in ('RUB','XTR'):
                try:variants[currency]=pricing.calculate(inputs,catalog['plans'],plan,currency,now,scheduled)
                except ValueError:
                    if plan!='align':raise
            if variants:
                first=next(iter(variants.values()))
                plans.append({'id':plan,'label':first['label'],'days':first['days'],'RUB':variants['RUB']['amount'],'XTR':variants['XTR']['amount'],
                              'prices':{c:{**{k:v[k] for k in ('amount','base_amount','credit_amount','starts_at','expires_at','already_covered')},'components':[{k:r[k] for k in ('source','credit_amount','covered_days')} for r in v['components']]} for c,v in variants.items()}})
        return {**catalog,'schema_version':2,'terms_version':pricing.TERMS,'plans':plans,'pending_order':dict(pending) if pending else None,
                'limits':'Доплата учитывает подтверждённый оплаченный срок отдельных продуктов. Пробные и подарочные дни сохраняются, но не считаются оплатой. Лимиты ИИ каждого продукта сохраняются. Общая подписка без автопродления.'}

    def cancel(self,user_id,order_id):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            order=db.execute('SELECT * FROM bundle_orders WHERE id=? AND user_id=?',(order_id,subject(user_id))).fetchone()
            if not order:raise ValueError('order_not_found')
            if order['status']!='pending':return {'status':order['status']}
            if order['checkout_id'] or order['provider_id'] or db.execute('SELECT 1 FROM bundle_provider_requests WHERE order_id=?',(order_id,)).fetchone():raise ValueError('payment_already_processing')
            db.execute("UPDATE bundle_orders SET status='canceled' WHERE id=?",(order_id,))
        return {'status':'canceled'}

    def quote(self,user_id,source,plan,currency,order_id,terms):
        user_id=subject(user_id)
        if source not in SOURCES or currency not in ('XTR','RUB') or terms not in ('progressor.bundle.v1',pricing.TERMS): raise ValueError('invalid_bundle_quote')
        uuid.UUID(order_id)
        price=next((p for p in self.catalog()['plans'] if p['id']==plan),None)
        if not price and not (terms==pricing.TERMS and plan=='align'): raise ValueError('invalid_bundle_plan')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone()
            if old:
                if (old['user_id'],old['source'],old['plan'],old['currency'])!=(user_id,source,plan,currency): raise ValueError('quote_conflict')
                return dict(old)
            if terms=='progressor.bundle.v1' and self.upgrade_gate and Path(self.upgrade_gate).exists():
                self._upgrades_ready()
                raise ValueError('refresh_personal_bundle_terms')
            if terms==pricing.TERMS:
                self._upgrades_ready()
                if not self.pricing_provider:raise ValueError('native_pricing_unavailable')
                now=utc()
                for existing in db.execute("SELECT * FROM bundle_orders WHERE user_id=? AND status='pending' AND pricing_json IS NOT NULL",(user_id,)).fetchall():
                    frozen=json.loads(existing['pricing_json'])
                    if existing['checkout_id'] or existing['provider_id'] or utc(frozen['quote_valid_until'])>now:
                        if (existing['source'],existing['plan'],existing['currency'])==(source,plan,currency):return dict(existing)
                        raise ValueError('pending_bundle_checkout')
                    db.execute("UPDATE bundle_orders SET status='expired' WHERE id=?",(existing['id'],))
                end=db.execute('SELECT expires_at FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()
                frozen=pricing.calculate(self.pricing_provider(user_id),self.catalog()['plans'],plan,currency,now,end['expires_at'] if end else None)
                if frozen['already_covered']:raise ValueError('bundle_period_already_covered')
                db.execute("INSERT INTO bundle_orders(id,user_id,source,plan,currency,amount,days,status,created_at,pricing_json) VALUES(?,?,?,?,?,?,?,'pending',?,?)",(order_id,user_id,source,plan,currency,frozen['amount'],frozen['days'],now.isoformat(),canonical(frozen)))
                return dict(db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone())
            db.execute('INSERT INTO bundle_orders(id,user_id,source,plan,currency,amount,days,status,created_at) VALUES(?,?,?,?,?,?,?,\'pending\',?)',(order_id,user_id,source,plan,currency,price[currency],price['days'],utc().isoformat()))
            return dict(db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone())

    def _upgrades_ready(self):
        # First rollout: enable only after all four services pass promotion and
        # independent live checks. Before that, rollback has no new v2 orders.
        if self.upgrade_gate:
            path=Path(self.upgrade_gate)
            if path.is_symlink() or not path.is_file() or path.stat().st_size>256 or path.read_text().strip()!='2':
                raise ValueError('bundle_upgrade_rollout_pending')

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
            if order.get('pricing_json') and utc(json.loads(order['pricing_json'])['quote_valid_until'])<=utc():raise ValueError('checkout_expired')
            if order['checkout_id'] and order['checkout_id']!=checkout_id: raise ValueError('checkout_already_reserved')
            db.execute('UPDATE bundle_orders SET checkout_id=? WHERE id=?',(checkout_id,order['id']))
        return {'ok':True}

    def precheckout_rejected(self,user_id,order_id,checkout_id,source):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            order=db.execute('SELECT * FROM bundle_orders WHERE id=?',(order_id,)).fetchone()
            if not order or order['user_id']!=str(user_id) or order['source']!=source:raise ValueError('order_not_found')
            if order['status']=='pending' and order['checkout_id']==checkout_id and not order['provider_id'] and not order['charge_id']:
                db.execute('UPDATE bundle_orders SET checkout_id=NULL WHERE id=?',(order_id,))
        return {'ok':True}

    def _rebuild(self,db,user_id):
        end=datetime(1970,1,1,tzinfo=timezone.utc)
        db.execute('DELETE FROM bundle_component_intervals WHERE user_id=?',(user_id,))
        for row in db.execute("SELECT * FROM bundle_orders WHERE user_id=? AND status='paid' ORDER BY paid_at,id",(user_id,)):
            if row['pricing_json']:
                frozen=json.loads(row['pricing_json'])
                start=utc(frozen.get('settled_starts_at',frozen['starts_at']))
                finish=utc(frozen.get('settled_expires_at',frozen['expires_at']))
                grants=[]
                if finish>start:
                    for source in SOURCES:
                        cursor=pricing.ticks(start);hi=pricing.ticks(finish)
                        for lo,right in pricing.merged(frozen['native_inputs'][source]['paid_intervals'],cursor,hi):
                            if lo>cursor:grants.append((source,datetime.fromtimestamp(cursor/1000000,timezone.utc).isoformat(),datetime.fromtimestamp(lo/1000000,timezone.utc).isoformat()))
                            cursor=right
                        if cursor<hi:grants.append((source,datetime.fromtimestamp(cursor/1000000,timezone.utc).isoformat(),finish.isoformat()))
                end=max(end,finish)
            else:
                start=max(end,utc(row['paid_at']));end=start+timedelta(days=row['days'])
                grants=[(source,start.isoformat(),end.isoformat()) for source in SOURCES]
            for source,start_at,expires_at in grants:
                db.execute('INSERT INTO bundle_component_intervals VALUES(?,?,?,?,?)',(row['id'],user_id,source,start_at,expires_at))
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
            if status=='paid' and current['pricing_json']:
                frozen=json.loads(current['pricing_json'])
                if 'settled_starts_at' not in frozen:
                    previous=db.execute('SELECT expires_at FROM bundle_entitlements WHERE user_id=?',(order['user_id'],)).fetchone()
                    start=max(utc(paid_at),utc(frozen['starts_at']),utc(previous['expires_at']) if previous else utc(paid_at))
                    end=utc(frozen['expires_at']) if current['plan']=='align' and start<utc(frozen['expires_at']) else start+timedelta(seconds=(utc(frozen['expires_at'])-utc(frozen['starts_at'])).total_seconds())
                    frozen.update(settled_starts_at=start.isoformat(),settled_expires_at=end.isoformat())
                    db.execute('UPDATE bundle_orders SET pricing_json=? WHERE id=?',(canonical(frozen),order['id']))
            db.execute('INSERT INTO bundle_receipts VALUES(?,?,?,?,?,?,?)',(receipt_id,order['id'],source,body['kind'],body['charge_id'],canonical(body),utc().isoformat()))
            db.execute('UPDATE bundle_orders SET status=?,charge_id=?,paid_at=? WHERE id=?',(status,body['charge_id'],paid_at,order['id']))
            self._rebuild(db,order['user_id'])
        return {'status':status}

    def grants(self,after='',source=None):
        if source is not None:
            if source not in SOURCES:raise ValueError('invalid_grant_source')
            now=utc();items=[]
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                users=[r['user_id'] for r in db.execute('SELECT user_id FROM bundle_entitlements WHERE user_id>? ORDER BY user_id LIMIT 501',(after,))]
                for user_id in users[:500]:
                    rows=[dict(r) for r in db.execute('SELECT starts_at,expires_at FROM bundle_component_intervals WHERE user_id=? AND source=? ORDER BY starts_at',(user_id,source))]
                    # Merge overlapping renewals into an offline-checkable schedule.
                    merged=pricing.merged(rows,0,pricing.ticks(datetime(9999,1,1,tzinfo=timezone.utc)))
                    intervals=[{'starts_at':datetime.fromtimestamp(a/1000000,timezone.utc).isoformat(),'expires_at':datetime.fromtimestamp(b/1000000,timezone.utc).isoformat()} for a,b in merged]
                    expiry=next((r['expires_at'] for r in intervals if utc(r['starts_at'])<=now<utc(r['expires_at'])),datetime(1970,1,1,tzinfo=timezone.utc).isoformat())
                    # Existing v1 deployments gain component schedules on first sync.
                    body=canonical({'expires_at':expiry,'intervals':intervals})
                    old=db.execute('SELECT body,revision FROM bundle_source_grants WHERE user_id=? AND source=?',(user_id,source)).fetchone()
                    legacy_revision=db.execute('SELECT revision FROM bundle_entitlements WHERE user_id=?',(user_id,)).fetchone()['revision']
                    has_v2=db.execute('SELECT 1 FROM bundle_orders WHERE user_id=? AND pricing_json IS NOT NULL LIMIT 1',(user_id,)).fetchone()
                    revision=(old['revision']+(old['body']!=body) if old else legacy_revision+1) if has_v2 else legacy_revision
                    db.execute('INSERT INTO bundle_source_grants VALUES(?,?,?,?) ON CONFLICT(user_id,source) DO UPDATE SET body=excluded.body,revision=excluded.revision',(user_id,source,body,revision))
                    items.append({'user_id':user_id,'source':source,'expires_at':expiry,'intervals':intervals,'revision':revision})
            return {'items':items,'next':users[499] if len(users)>500 else None}
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
