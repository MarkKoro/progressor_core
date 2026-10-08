"""Payment transports and independent website sign-in; no provider return URL fulfillment."""
import hashlib
import math
import re
import secrets
import time
import uuid
from pathlib import Path
import httpx
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse
from .auth import sign_assertion,verify_assertion
from .billing import receipt,utc
from .contracts import SOURCES,subject
from .ai_context import build_ai_context
from shared.progressor_client import verify_control

BOT_NAMES={'gym':'progresor_bot','food':'EjkaClejka_bot','supply':'supplly_bot'}

async def yookassa(cfg,method,path,**kwargs):
    if not cfg.yookassa_shop or not cfg.yookassa_key: raise ValueError('rub_payments_disabled')
    async with httpx.AsyncClient(timeout=12,trust_env=False) as client:
        response=await client.request(method,'https://api.yookassa.ru/v3/'+path,auth=(cfg.yookassa_shop,cfg.yookassa_key),**kwargs)
        response.raise_for_status(); return response.json()

def checked_payment(order,payment):
    amount=payment.get('amount') or {}; meta=payment.get('metadata') or {}
    from decimal import Decimal
    if amount.get('currency')!='RUB' or Decimal(str(amount.get('value','0')))*100!=order['amount'] or meta.get('progressor_order')!=order['id'] or str(meta.get('progressor_user'))!=order['user_id'] or not payment.get('id'): raise ValueError('provider_payment_mismatch')
    if payment.get('status')=='succeeded' and payment.get('paid') is not True: raise ValueError('provider_not_paid')

async def reconcile_rub(engine,payment_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',payment_id): raise ValueError('invalid_payment_id')
    payment=await yookassa(engine.config,'GET','payments/'+payment_id)
    order=engine.billing.order((payment.get('metadata') or {}).get('progressor_order',''))
    if order['currency']!='RUB' or order['provider_id']!=payment_id: raise ValueError('unknown_provider_payment')
    checked_payment(order,payment)
    if payment['status']=='succeeded':
        engine.billing.settle(receipt(order,'paid',payment_id),order['source'],verified_rub=True)
        refunded=payment.get('refunded_amount')
        if refunded:
            from decimal import Decimal
            returned=Decimal(str(refunded.get('value','0')))*100
            if refunded.get('currency')!='RUB' or not returned.is_finite() or returned<0 or returned>order['amount']: raise ValueError('invalid_refunded_amount')
            if returned==order['amount']: engine.billing.settle(receipt(order,'refunded',payment_id),order['source'],verified_rub=True)
    elif payment['status']=='canceled':
        with engine.store.connection() as db: db.execute("UPDATE bundle_orders SET status='canceled' WHERE id=? AND status='pending'",(order['id'],))
    return payment['status']

async def reconcile_refund(engine,refund_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,128}',refund_id): raise ValueError('invalid_refund_id')
    refund=await yookassa(engine.config,'GET','refunds/'+refund_id)
    payment_id=refund['payment_id']
    await reconcile_rub(engine,payment_id)
    with engine.store.connection() as db:
        row=db.execute('SELECT * FROM bundle_orders WHERE provider_id=?',(payment_id,)).fetchone()
    if not row: raise ValueError('unknown_refund_payment')
    order=dict(row)
    from decimal import Decimal
    amount=refund.get('amount') or {}
    value=Decimal(str(amount.get('value','0')))*100
    if amount.get('currency')!='RUB' or value!=int(value) or not 0<value<=order['amount']: raise ValueError('invalid_refund_amount')
    with engine.store.connection() as db:
        db.execute('INSERT INTO bundle_refunds VALUES(?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status',(refund_id,payment_id,int(value),refund['status']))
        total=db.execute("SELECT COALESCE(sum(amount),0) FROM bundle_refunds WHERE payment_id=? AND status='succeeded'",(payment_id,)).fetchone()[0]
    if total>=order['amount']: engine.billing.settle(receipt(order,'refunded',payment_id),order['source'],verified_rub=True)

async def reconcile_pending(engine):
    with engine.store.connection() as db:
        ids=[r[0] for r in db.execute("SELECT o.provider_id FROM bundle_orders o LEFT JOIN bundle_provider_checks c ON c.payment_id=o.provider_id WHERE o.currency='RUB' AND o.status IN ('pending','paid') AND o.provider_id IS NOT NULL AND (COALESCE(c.checked_at,0)<? OR o.status='pending') ORDER BY COALESCE(c.checked_at,0) LIMIT 10",(time.time()-300,))]
        for identifier in ids: db.execute('INSERT INTO bundle_provider_checks VALUES(?,?) ON CONFLICT(payment_id) DO UPDATE SET checked_at=excluded.checked_at',(identifier,time.time()))
    for payment_id in ids:
        try: await reconcile_rub(engine,payment_id)
        except Exception:
            import logging
            logging.getLogger('progressor').warning('rub_reconcile_unavailable')

async def invoice(engine,order):
    import json
    if order['status']!='pending' or order['currency']!='XTR':raise ValueError('order_not_pending_stars')
    if order.get('pricing_json') and utc(json.loads(order['pricing_json'])['quote_valid_until'])<=utc():raise ValueError('checkout_expired')
    token=engine.config.bot_tokens.get(order['source'])
    if not token: raise ValueError('bot_not_configured')
    async with httpx.AsyncClient(timeout=8,trust_env=False) as client:
        response=await client.post('https://api.telegram.org/bot'+token+'/createInvoiceLink',json={'title':'Progressor · 3 продукта','description':f"Тренировки, питание и БАДы · {order['days']} дней. Сохраняются лимиты каждого продукта. Без автопродления.",'payload':'progressor:'+order['source']+':'+order['id'],'provider_token':'','currency':'XTR','prices':[{'label':'Общая подписка','amount':order['amount']}]})
        response.raise_for_status(); body=response.json()
    if not body.get('ok') or not str(body.get('result','')).startswith('https://t.me/'): raise ValueError('invoice_creation_failed')
    return body['result']

async def create_rub(engine,order,email):
    import json
    if not isinstance(email,str) or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,30}',email): raise ValueError('invalid_receipt_email')
    if order['status']!='pending': raise ValueError('order_not_pending')
    if time.time()-utc(order['created_at']).timestamp()>=23*3600: raise ValueError('uncertain_payment_requires_support')
    if order['provider_id']:
        payment=await yookassa(engine.config,'GET','payments/'+order['provider_id'])
        checked_payment(order,payment)
        return payment.get('confirmation',{}).get('confirmation_url')
    value=f"{order['amount']/100:.2f}"
    body={'amount':{'value':value,'currency':'RUB'},'capture':True,'confirmation':{'type':'redirect','return_url':engine.config.origin+'/progressor/subscribe?order='+order['id']},'description':f"Progressor: 3 продукта, {order['days']} дней",'metadata':{'progressor_order':order['id'],'progressor_user':order['user_id']},'receipt':{'customer':{'email':email},'items':[{'description':f"Общая подписка Progressor ({order['days']} дней)",'quantity':'1.00','amount':{'value':value,'currency':'RUB'},'vat_code':engine.config.yookassa_vat,'payment_mode':'full_payment','payment_subject':'service'}]}}
    from .contracts import canonical
    import json
    with engine.store.connection() as db:
        existing=db.execute('SELECT payload FROM bundle_provider_requests WHERE order_id=?',(order['id'],)).fetchone()
        contact=db.execute('SELECT email FROM bundle_provider_contacts WHERE order_id=?',(order['id'],)).fetchone()
    if existing:
        body=json.loads(existing['payload'])
        original_email=contact['email'] if contact else ((body.get('receipt') or {}).get('customer') or {}).get('email')
        if original_email!=email:raise ValueError('immutable_receipt_email')
    else:
        if order.get('pricing_json') and utc(json.loads(order['pricing_json'])['quote_valid_until'])<=utc():raise ValueError('checkout_expired')
        # Match the selected existing merchant's receipt mode before the first provider POST.
        # This GET creates no payment; an uncertain/disabled shop never starts a charge.
        merchant=await yookassa(engine.config,'GET','me')
        if merchant.get('status')!='enabled' or merchant.get('test') is not False or str(merchant.get('account_id'))!=engine.config.yookassa_shop:
            raise ValueError('merchant_not_ready')
        enabled=(merchant.get('fiscalization') or {}).get('enabled',merchant.get('fiscalization_enabled',False))
        if type(enabled) is not bool:raise ValueError('invalid_merchant_receipt_mode')
        if enabled:body['receipt']['internet']=True
        else:body.pop('receipt')
    with engine.store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT status FROM bundle_orders WHERE id=?',(order['id'],)).fetchone()
        if not current or current['status']!='pending':raise ValueError('order_not_pending')
        old=db.execute('SELECT payload FROM bundle_provider_requests WHERE order_id=?',(order['id'],)).fetchone()
        if old:
            stored=json.loads(old['payload'])
            contact=db.execute('SELECT email FROM bundle_provider_contacts WHERE order_id=?',(order['id'],)).fetchone()
            original_email=contact['email'] if contact else ((stored.get('receipt') or {}).get('customer') or {}).get('email')
            if original_email!=email: raise ValueError('immutable_receipt_email')
            body=stored
        else: db.execute('INSERT INTO bundle_provider_requests VALUES(?,?)',(order['id'],canonical(body)))
        db.execute('INSERT OR IGNORE INTO bundle_provider_contacts VALUES(?,?)',(order['id'],email))
    payment=await yookassa(engine.config,'POST','payments',json=body,headers={'Idempotence-Key':order['id']})
    checked_payment(order,payment)
    with engine.store.connection() as db: db.execute('UPDATE bundle_orders SET provider_id=? WHERE id=? AND provider_id IS NULL',(payment['id'],order['id']))
    return payment.get('confirmation',{}).get('confirmation_url')

def install_routes(app,engine,claims):
    def available(request):
        if set(engine(request).config.enabled_domains)!=set(SOURCES): raise HTTPException(503,'Bundle rollout is not complete')
    async def private(request):
        if request.client and request.client.host not in ('127.0.0.1','::1','testclient'): raise HTTPException(403,'Local control only')
        raw=await request.body()
        if len(raw)>32768: raise HTTPException(413,'Body too large')
        try:
            import json
            source=verify_control(request.headers.get('X-Progressor-Control',''),request.url.path,raw,engine(request).config.signing_key)
            body=json.loads(raw)
            if not isinstance(body,dict): raise ValueError('invalid_body')
            return source,body
        except Exception: raise HTTPException(401,'Control rejected')

    def web_claims(request):
        token=request.headers.get('X-Progressor-Web','')
        try:
            user=verify_assertion(token,'core',engine(request).config.signing_key)
            with engine(request).store.connection() as db:
                row=db.execute('SELECT user_id,expires_at FROM website_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not row or row['user_id']!=user['sub'] or row['expires_at']<=time.time(): raise ValueError('invalid_website_session')
            return user
        except Exception: raise HTTPException(401,'Website sign-in required')

    @app.post('/internal/v1/ai-context')
    async def ai(request:Request):
        source,body=await private(request)
        if set(engine(request).config.enabled_domains)!=set(SOURCES): return None
        try: return build_ai_context(engine(request).store,subject(body['user_id']),source)
        except (KeyError,ValueError,TypeError): raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/profile')
    async def profile_context(request:Request):
        source,body=await private(request)
        from .context import build_context
        try:
            data=build_context(engine(request).store,subject(body['user_id']),target=source,enabled_sources=engine(request).config.enabled_domains)
            return data['profile']
        except (KeyError,ValueError,TypeError): raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/food-notifications')
    async def food_notifications(request:Request):
        source,body=await private(request)
        if source!='food': raise HTTPException(403,'Food sender only')
        from .notifications import candidate
        try:
            people=body['people']
            if not isinstance(people,list) or len(people)>50: raise ValueError('batch')
            result=[]
            for prefs in people:
                uid=subject(prefs['user_id'])
                if type(prefs.get('enabled_at')) not in (int,float) or not math.isfinite(prefs['enabled_at']): raise ValueError('time')
                for field in ('workout_enabled','nutrient_enabled'):
                    if type(prefs.get(field)) is not bool: raise ValueError('preference')
                value=candidate(engine(request).store,uid,prefs,enabled_sources=engine(request).config.enabled_domains)
                if value: result.append({'user_id':uid,**value})
            return {'items':result}
        except (KeyError,ValueError,TypeError): raise HTTPException(422,'Invalid preferences')

    @app.post('/internal/v1/grants')
    async def grants(request:Request):
        source,body=await private(request)
        return engine(request).billing.grants(str(body.get('after','')),source)

    @app.post('/internal/v1/subscription-notices/claim')
    async def claim_notices(request:Request):
        import asyncio
        source,body=await private(request)
        try:return await asyncio.to_thread(engine(request).subscription_notices.claim,source,str(body.get('after','')))
        except (KeyError,ValueError,TypeError):raise HTTPException(422,'Invalid notification request')

    @app.post('/internal/v1/subscription-notices/ack')
    async def ack_notice(request:Request):
        import asyncio
        source,body=await private(request)
        try:return await asyncio.to_thread(engine(request).subscription_notices.acknowledge,source,body['event_key'],body['status'],body.get('retry_after',0))
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Notification acknowledgement rejected')

    @app.post('/internal/v1/bundle/quote')
    async def quote(request:Request):
        available(request)
        source,body=await private(request)
        try: return engine(request).billing.quote(body['user_id'],source,body['plan'],'XTR',body['order_id'],body['terms'])
        except (KeyError,ValueError,TypeError): raise HTTPException(409,'Quote rejected')

    @app.post('/internal/v1/bundle/catalog')
    async def private_catalog(request:Request):
        _,body=await private(request)
        if 'user_id' not in body:return engine(request).billing.catalog()
        try:return engine(request).billing.personal_catalog(body['user_id'])
        except (KeyError,ValueError,TypeError):raise HTTPException(503,'Personal pricing temporarily unavailable')

    @app.post('/internal/v1/bundle/cancel')
    async def cancel_order(request:Request):
        _,body=await private(request)
        try:return engine(request).billing.cancel(body['user_id'],body['order_id'])
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Payment already processing')

    @app.post('/internal/v1/bot-context')
    async def bot_context(request:Request):
        source,body=await private(request)
        from .context import build_context
        try:
            data=build_context(engine(request).store,subject(body['user_id']),target=source,enabled_sources=engine(request).config.enabled_domains)
            return {k:data.get(k) for k in ('inline_hint','access','activity','nutrition','profile')}
        except (KeyError,ValueError,TypeError):raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/bundle/precheckout')
    async def precheckout(request:Request):
        available(request)
        source,body=await private(request)
        try: return engine(request).billing.precheckout(body,source)
        except (KeyError,ValueError,TypeError): raise HTTPException(409,'Checkout rejected')

    @app.post('/internal/v1/bundle/precheckout-rejected')
    async def precheckout_rejected(request:Request):
        available(request);source,body=await private(request)
        try:return engine(request).billing.precheckout_rejected(subject(body['user_id']),body['order_id'],body['checkout_id'],source)
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Checkout rejection mismatch')

    @app.post('/internal/v1/bundle/invoice-link')
    async def bot_invoice_link(request:Request):
        available(request);source,body=await private(request)
        try:
            order=engine(request).billing.order(body['order_id'],subject(body['user_id']))
            if order['source']!=source or order['currency']!='XTR' or order['status']!='pending':raise ValueError('invoice_owner_mismatch')
            if order.get('pricing_json'):
                import json
                if utc(json.loads(order['pricing_json'])['quote_valid_until'])<=utc():raise ValueError('checkout_expired')
            return {'order_id':order['id'],'invoice_url':await invoice(engine(request),order)}
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Invoice rejected')
        except httpx.HTTPError:raise HTTPException(503,'Invoice temporarily unavailable')

    @app.post('/internal/v1/bundle/receipt')
    async def paid(request:Request):
        source,body=await private(request)
        try: return engine(request).billing.settle(body,source)
        except (KeyError,ValueError,TypeError): raise HTTPException(409,'Receipt rejected')

    @app.get('/api/v1/bundle/catalog')
    def catalog(request:Request): return {**engine(request).billing.catalog(),'rub_available':bool(engine(request).config.yookassa_shop and engine(request).config.yookassa_key)}

    @app.get('/api/v1/me/bundle/catalog')
    def personal_catalog(request:Request):
        user=claims(request)
        try:return engine(request).billing.personal_catalog(user['sub'])
        except (KeyError,ValueError,TypeError):raise HTTPException(503,'Personal pricing temporarily unavailable')

    @app.post('/api/v1/me/bundle/cancel')
    async def cancel_personal(request:Request):
        user=claims(request);body=await request.json()
        try:return engine(request).billing.cancel(user['sub'],body['order_id'])
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Payment already processing')

    @app.post('/api/v1/me/bundle/invoice')
    async def buy_stars(request:Request):
        available(request)
        user=claims(request)
        try:
            body=await request.json()
            order=engine(request).billing.quote(user['sub'],body['source'],body['plan'],'XTR',body['order_id'],body['terms'])
            if order['status']!='pending': raise ValueError('order_not_pending')
            return {'order_id':order['id'],'invoice_url':await invoice(engine(request),order)}
        except (KeyError,ValueError,TypeError): raise HTTPException(409,'Invoice rejected')
        except httpx.HTTPError: raise HTTPException(503,'Payment temporarily unavailable')

    @app.get('/api/v1/me/bundle/orders/{order_id}')
    def status(request:Request,order_id:str):
        try: order=engine(request).billing.order(order_id,claims(request)['sub'])
        except ValueError: raise HTTPException(404,'Order not found')
        return {'id':order['id'],'status':order['status']}

    @app.get('/subscribe')
    def website(): return FileResponse(Path(__file__).resolve().parents[1]/'shared'/'subscribe.html')

    @app.post('/api/v1/website/login')
    def login(request:Request):
        challenge=uuid.uuid4().hex; secret=secrets.token_urlsafe(32)
        with engine(request).store.connection() as db:
            db.execute('DELETE FROM website_logins WHERE created_at<?',(time.time()-600,))
            db.execute('DELETE FROM website_sessions WHERE expires_at<?',(time.time(),))
            db.execute('INSERT INTO website_logins VALUES(?,?,?,NULL,0)',(challenge,hashlib.sha256(secret.encode()).hexdigest(),time.time()))
        return {'challenge':challenge,'poll_secret':secret,'bots':{s:'https://t.me/'+name+'?start=pglogin_'+challenge for s,name in BOT_NAMES.items()}}

    @app.post('/internal/v1/website/approve')
    async def approve(request:Request):
        _,body=await private(request)
        try:
            uid=subject(body['user_id'])
            with engine(request).store.connection() as db:
                changed=db.execute('UPDATE website_logins SET user_id=? WHERE id=? AND created_at>? AND consumed=0 AND (user_id IS NULL OR user_id=?)',(uid,body['challenge'],time.time()-300,uid))
                if changed.rowcount!=1: raise ValueError('expired_challenge')
        except (KeyError,TypeError,ValueError): raise HTTPException(409,'Login expired')
        return {'ok':True}

    @app.post('/api/v1/website/poll')
    async def poll(request:Request):
        body=await request.json(); token=None
        with engine(request).store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM website_logins WHERE id=?',(str(body.get('challenge','')),)).fetchone()
            if not row or row['created_at']<time.time()-300 or row['consumed'] or not secrets.compare_digest(row['poll_hash'],hashlib.sha256(str(body.get('poll_secret','')).encode()).hexdigest()): raise HTTPException(401,'Login expired')
            if row['user_id']:
                stamp=int(time.time()); token=sign_assertion({'id':int(row['user_id'])},stamp,'core',engine(request).config.signing_key,ttl=900)
                db.execute('UPDATE website_logins SET consumed=1 WHERE id=?',(row['id'],))
                db.execute('INSERT INTO website_sessions VALUES(?,?,?) ON CONFLICT(token_hash) DO UPDATE SET expires_at=excluded.expires_at',(hashlib.sha256(token.encode()).hexdigest(),row['user_id'],stamp+900))
        return {'approved':bool(token),'token':token}

    @app.post('/api/v1/website/checkout')
    async def website_checkout(request:Request):
        available(request)
        user=web_claims(request)
        try:
            body=await request.json(); source=body.get('source','food')
            order=engine(request).billing.quote(user['sub'],source,body['plan'],'RUB',body['order_id'],body['terms'])
            url=await create_rub(engine(request),order,body['email'])
            if not str(url or '').startswith('https://'): raise ValueError('invalid_confirmation')
            return {'order_id':order['id'],'confirmation_url':url}
        except (KeyError,ValueError,TypeError): raise HTTPException(409,'Checkout rejected')
        except httpx.HTTPError: raise HTTPException(503,'Payment temporarily unavailable; retry the same order')

    @app.post('/api/v1/website/catalog')
    def website_catalog(request:Request):
        user=web_claims(request)
        try:return {**engine(request).billing.personal_catalog(user['sub']),'rub_available':bool(engine(request).config.yookassa_shop and engine(request).config.yookassa_key)}
        except (KeyError,ValueError,TypeError):raise HTTPException(503,'Personal pricing temporarily unavailable')

    @app.post('/api/v1/website/cancel')
    async def website_cancel(request:Request):
        user=web_claims(request);body=await request.json()
        try:return engine(request).billing.cancel(user['sub'],body['order_id'])
        except (KeyError,ValueError,TypeError):raise HTTPException(409,'Payment already processing')

    @app.post('/api/v1/website/status')
    async def website_status(request:Request):
        user=web_claims(request); body=await request.json()
        try:
            order=engine(request).billing.order(body['order_id'],user['sub'])
            if order['currency']=='RUB' and order['provider_id'] and order['status']=='pending':
                await reconcile_rub(engine(request),order['provider_id']); order=engine(request).billing.order(order['id'],user['sub'])
            return {'id':order['id'],'status':order['status']}
        except ValueError: raise HTTPException(404,'Order not found')

    @app.post('/api/v1/bundle/yookassa/webhook')
    async def webhook(request:Request):
        # Notifications are hints only: authenticated provider GET verifies every field.
        if int(request.headers.get('content-length','0') or '0')>32768: raise HTTPException(413,'Body too large')
        try:
            body=await request.json(); identifier=body['object']['id']
            if body.get('event')=='refund.succeeded': await reconcile_refund(engine(request),identifier)
            elif body.get('event') in ('payment.succeeded','payment.canceled'): await reconcile_rub(engine(request),identifier)
        except ValueError: raise HTTPException(400,'Unknown payment')
        except (KeyError,TypeError): raise HTTPException(400,'Invalid notification')
        except httpx.HTTPError: raise HTTPException(503,'Retry notification')
        return {'ok':True}
