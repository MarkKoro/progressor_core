import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from .adapters import snapshot
from .auth import AUDIENCES, sign_assertion, telegram_user, verify_assertion
from .context import build_context
from .contracts import SOURCES, digest, now_utc
from .store import Store
from .access import entitlements
from .billing import Billing
from .native_pricing import NativePricing
from .subscription_notices import SubscriptionNotices
from .payments import install_routes, reconcile_pending
from .rate_limit import SlidingWindows, client_address

log = logging.getLogger('progressor')
if not log.handlers:
    safe_handler=logging.StreamHandler()
    safe_handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(safe_handler)
log.setLevel(logging.INFO)
log.propagate=False  # Do not enable HTTP-client logging: upstream URLs can contain bot tokens.


@dataclass
class Config:
    db_path: str
    signing_key: str
    source_paths: dict = field(default_factory=dict)
    bot_tokens: dict = field(default_factory=dict)
    ingest_keys: dict = field(default_factory=dict)
    origin: str = 'https://telegrambotsforeveryone.duckdns.org'
    poll_seconds: int = 30
    background: bool = True
    enabled_domains: tuple = SOURCES
    yookassa_shop: str = ''
    yookassa_key: str = ''
    yookassa_vat: int = 1
    require_fresh_snapshots: bool = False
    bundle_upgrade_gate: str | None = None

    @classmethod
    def environment(cls):
        enabled = tuple(s for s in os.environ.get('PROGRESSOR_ENABLED_DOMAINS', '').split(',') if s in SOURCES)
        return cls(db_path=os.environ['PROGRESSOR_DB_PATH'], signing_key=Path(os.environ['PROGRESSOR_SIGNING_KEY_FILE']).read_text().strip(), source_paths={s: os.environ['PROGRESSOR_' + s.upper() + '_DB_RO'] for s in SOURCES if os.environ.get('PROGRESSOR_' + s.upper() + '_DB_RO')}, bot_tokens={s: os.environ.get('PROGRESSOR_' + s.upper() + '_BOT_TOKEN', '') for s in SOURCES}, ingest_keys={s: os.environ.get('PROGRESSOR_' + s.upper() + '_INGEST_KEY', '') for s in SOURCES}, enabled_domains=enabled,yookassa_shop=os.getenv('PROGRESSOR_YOOKASSA_SHOP_ID',''),yookassa_key=os.getenv('PROGRESSOR_YOOKASSA_SECRET_KEY',''),yookassa_vat=int(os.getenv('PROGRESSOR_YOOKASSA_VAT_CODE','1')),require_fresh_snapshots=os.getenv('PROGRESSOR_REQUIRE_FRESH_SNAPSHOTS','0')=='1',bundle_upgrade_gate='/var/lib/progressor/bundle-v2-ready')


class Engine:
    def __init__(self, config):
        self.config = config
        if len(config.signing_key) < 32 or any(Path(config.db_path).resolve() == Path(p).resolve() for p in config.source_paths.values()):
            raise ValueError('unsafe_core_configuration')
        self.store = Store(config.db_path)
        self.store.enabled_sources=set(config.enabled_domains)
        self.billing = Billing(self.store,NativePricing(config.source_paths),config.bundle_upgrade_gate)
        self.subscription_notices=SubscriptionNotices(self.store,config.source_paths)
        self.metrics = Counter()

    def poll(self):
        with self.store.connection() as db:
            retry = {r['source']: r['retry_at'] for r in db.execute('SELECT source,retry_at FROM source_state')}
        for source in SOURCES:
            try:
                if source in self.config.source_paths: self.billing.drain_receipts(source,self.config.source_paths[source])
            except Exception:
                log.warning('bundle_outbox_unavailable source=%s',source)
            if time.time() < retry.get(source, 0):
                continue
            try:
                if source not in self.config.source_paths:
                    raise FileNotFoundError('source_not_configured')
                changed = self.store.reconcile(source, snapshot(source, self.config.source_paths[source],max_age=90 if self.config.require_fresh_snapshots else None))
                self.metrics['events_accepted'] += changed
                log.info(json.dumps({'event': 'source_snapshot', 'source': source, 'changed': changed, 'correlation_id': uuid.uuid4().hex}))
            except Exception as exc:
                reason = 'source_unavailable' if isinstance(exc, (FileNotFoundError, OSError)) else 'source_snapshot_rejected'
                self.store.failed(source, reason)
                self.metrics['source_errors_' + source] += 1
                log.warning(json.dumps({'event': 'source_degraded', 'source': source, 'reason': reason, 'error_class': type(exc).__name__, 'correlation_id': uuid.uuid4().hex}))


def create_app(config=None):
    @asynccontextmanager
    async def lifespan(app):
        resolved = config or Config.environment()
        engine = Engine(resolved)
        app.state.engine = engine
        task = None
        billing_task = None
        if resolved.background:
            async def worker():
                while True:
                    await asyncio.to_thread(engine.poll)
                    await asyncio.sleep(resolved.poll_seconds)
            task = asyncio.create_task(worker())
            async def billing_worker():
                while True:
                    try: await reconcile_pending(engine)
                    except Exception: log.warning('billing_reconcile_unavailable')
                    await asyncio.sleep(30)
            billing_task = asyncio.create_task(billing_worker())
        try:
            yield
        finally:
            if task:
                task.cancel()
                billing_task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                try: await billing_task
                except asyncio.CancelledError: pass

    app = FastAPI(title='Progressor Core', lifespan=lifespan, docs_url=None, redoc_url=None)
    rate = SlidingWindows()

    @app.middleware('http')
    async def observe(request, call_next):
        correlation_id = uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        stamp = time.monotonic()
        length=request.headers.get('content-length','0')
        if not length.isdecimal() or int(length)>32768: return JSONResponse({'detail':'Body too large'},status_code=413)
        if request.method=='POST' and len(await request.body())>32768: return JSONResponse({'detail':'Body too large'},status_code=413)
        if request.url.path.startswith('/api/v1/website/') or request.url.path=='/api/v1/bundle/yookassa/webhook':
            if not rate.allow('billing:'+client_address(request),120,now=stamp):
                return JSONResponse({'detail':'Retry later'},status_code=429,headers={'Retry-After':'60'})
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(json.dumps({'event':'request_failed','error_class':type(exc).__name__,'correlation_id':correlation_id}))
            response = JSONResponse({'detail':'Core temporarily unavailable','correlation_id':correlation_id},status_code=503)
        response.headers['X-Correlation-ID'] = correlation_id
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        engine = request.app.state.engine
        engine.metrics['requests'] += 1
        if response.status_code >= 500:
            engine.metrics['http_errors'] += 1
        log.info(json.dumps({'event': 'http_request', 'method': request.method, 'status': response.status_code, 'duration_ms': round((time.monotonic() - stamp) * 1000), 'correlation_id': correlation_id}))
        return response

    def engine(request):
        return request.app.state.engine

    def claims(request):
        try:
            return verify_assertion(request.headers.get('X-Progressor-Auth', ''), 'core', engine(request).config.signing_key)
        except Exception:
            raise HTTPException(401, 'Invalid or expired Progressor session')

    @app.get('/health')
    def health():
        return {'ok': True, 'service': 'progressor-core'}

    @app.get('/ready')
    def ready(request: Request):
        with engine(request).store.connection() as db:
            db.execute('SELECT 1 FROM schema_version').fetchone()
            statuses = {r['source']: 'ok' if r['status']=='ok' and time.time()-(r['last_success'] or 0)<120 else 'degraded' for r in db.execute('SELECT source,status,last_success FROM source_state')}
        return {'ready': True, 'integration_status': 'ok' if len(statuses) == 3 and all(s == 'ok' for s in statuses.values()) else 'degraded', 'sources': statuses}

    @app.get('/metrics')
    def metrics(request: Request):
        return PlainTextResponse(''.join('progressor_' + name + '_total ' + str(value) + '\n' for name, value in sorted(engine(request).metrics.items())))

    @app.get('/assets/navigation.v1.js')
    def navigation():
        return FileResponse(Path(__file__).resolve().parents[1] / 'shared' / 'navigation.v1.js', media_type='application/javascript')

    @app.post('/api/v1/sessions')
    async def sessions(request: Request):
        cfg = engine(request).config
        if request.headers.get('origin') and request.headers['origin'] != cfg.origin:
            raise HTTPException(403, 'Origin rejected')
        length=request.headers.get('content-length') or '0'
        if not length.isdecimal(): raise HTTPException(400,'Invalid body length')
        if int(length) > 20000:
            raise HTTPException(413, 'Launch proof too large')
        # IPs stay in memory; there are no launch/user/token values in logs.
        if not rate.allow('sessions:'+client_address(request),60):
            raise HTTPException(429, 'Retry later',headers={'Retry-After':'60'})
        try:
            raw_body = await request.body()
            if len(raw_body) > 20000:
                raise ValueError('body_too_large')
            body = json.loads(raw_body)
            source = body['source']
            if source not in SOURCES:
                raise ValueError('source')
            user, auth_date = telegram_user(body['init_data'], cfg.bot_tokens.get(source, ''))
        except Exception:
            engine(request).metrics['auth_errors'] += 1
            raise HTTPException(401, 'Invalid or expired Telegram launch')
        assertions = {aud: sign_assertion(user, auth_date, aud, cfg.signing_key) for aud in AUDIENCES}
        access=await run_in_threadpool(entitlements,engine(request).store,str(user['id']))
        return {'schema_version': 1, 'user': user, 'assertions': assertions, 'expires_at': min(int(time.time()) + 900, auth_date + 86400), 'enabled_domains': cfg.enabled_domains,'access':access}

    @app.get('/api/v1/me/context')
    def context(request: Request, day: str | None = None, target: str | None = None):
        identity = claims(request)
        if target is not None and target not in SOURCES: raise HTTPException(422,'Invalid target')
        if day:
            try:
                date.fromisoformat(day)
            except ValueError:
                raise HTTPException(422, 'Invalid date')
        return {**build_context(engine(request).store, identity['sub'], requested_day=day,target=target,enabled_sources=engine(request).config.enabled_domains), 'enabled_domains': engine(request).config.enabled_domains}

    @app.get('/api/v1/me/recommendations/history')
    def history(request: Request):
        identity = claims(request)
        if not entitlements(engine(request).store,identity['sub'])['domains']['food']: return {'items':[]}
        with engine(request).store.connection() as db:
            rows = [dict(r) for r in db.execute('SELECT id,rule,window,created_at,active,payload FROM recommendations WHERE user_id=? ORDER BY created_at DESC LIMIT 30', (identity['sub'],))]
        return {'items': [{**r, 'payload': json.loads(r['payload'])} for r in rows]}

    @app.post('/api/v1/me/hints/dismiss')
    async def dismiss_hint(request: Request):
        identity=claims(request)
        raw=await request.body()
        if len(raw)>256: raise HTTPException(413,'Body too large')
        try: target=json.loads(raw)['target']
        except (ValueError,KeyError,TypeError): raise HTTPException(422,'Invalid target')
        if target not in SOURCES or target not in engine(request).config.enabled_domains:
            raise HTTPException(422,'Invalid target')
        if not (await run_in_threadpool(entitlements,engine(request).store,identity['sub']))['domains'][target]:
            raise HTTPException(403,'Subscription required')
        return {'dismissed_until':await run_in_threadpool(engine(request).store.dismiss_hints,identity['sub'],target)}

    @app.post('/api/v1/me/offers/dismiss')
    async def dismiss_offer(request: Request):
        identity=claims(request)
        raw=await request.body()
        if len(raw)>256: raise HTTPException(413,'Body too large')
        try: target=json.loads(raw)['target']
        except (ValueError,KeyError,TypeError): raise HTTPException(422,'Invalid target')
        if target not in SOURCES or target not in engine(request).config.enabled_domains:
            raise HTTPException(422,'Invalid target')
        return {'dismissed_until':await run_in_threadpool(engine(request).store.dismiss_offers,identity['sub'],target)}

    @app.post('/api/v1/me/hints/seen')
    async def hint_seen(request: Request):
        identity=claims(request);raw=await request.body()
        if len(raw)>512: raise HTTPException(413,'Body too large')
        try:
            body=json.loads(raw);target=body['target'];key=body['delivery_key']
            if target not in SOURCES or target not in engine(request).config.enabled_domains: raise ValueError('target')
            current=await run_in_threadpool(build_context,engine(request).store,identity['sub'],target=target,enabled_sources=engine(request).config.enabled_domains)
            if not any(h.get('delivery_key')==key and target in h['targets'] for h in current['hints']): raise ValueError('hint')
        except (KeyError,TypeError,ValueError): raise HTTPException(422,'Invalid hint')
        await run_in_threadpool(engine(request).store.mark_hint_seen,identity['sub'],target,key)
        return {'seen':True}

    @app.post('/api/v1/events')
    async def events(request: Request):
        cfg = engine(request).config
        source = request.headers.get('X-Progressor-Source', '')
        secret = cfg.ingest_keys.get(source, '')
        if source not in SOURCES or not secret or not hmac.compare_digest(request.headers.get('X-Progressor-Source-Key', ''), secret):
            raise HTTPException(401, 'Producer not authorized')
        raw = await request.body()
        if len(raw) > 32768:
            raise HTTPException(413, 'Event too large')
        try:
            event = json.loads(raw)
            if event.get('source') != source:
                raise ValueError('producer_source_mismatch')
            status = await run_in_threadpool(engine(request).store.accept,event)
            engine(request).metrics['events_' + status] += 1
            return {'status': status, 'correlation_id': event['correlation_id']}
        except (ValueError, KeyError, TypeError) as exc:
            def retain_rejected_event(reason):
                with engine(request).store.connection() as db:
                    db.execute('INSERT INTO dead_letters(source,reason,payload_hash,received_at) VALUES(?,?,?,?)', (source, reason, digest(raw.hex()), now_utc()))
            await run_in_threadpool(retain_rejected_event,type(exc).__name__)
            engine(request).metrics['event_errors'] += 1
            raise HTTPException(409 if str(exc).endswith('conflict') else 422, 'Event rejected')

    install_routes(app,engine,claims)
    from .connection_routes import install as install_connections
    install_connections(app,engine,claims)
    @app.get('/assets/connections.v1.js')
    def connection_settings_asset():
        return FileResponse(Path(__file__).resolve().parents[1] / 'shared' / 'connections.v1.js',media_type='application/javascript')
    return app


app = create_app()
