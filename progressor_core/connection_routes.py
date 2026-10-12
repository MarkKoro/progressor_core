"""Own-account settings; trusted source control never widens trainer AI scope."""
import json
from fastapi import HTTPException, Request
from .contracts import subject
from . import connections as links
from shared.progressor_client import verify_control

def install(app,engine,claims):
    async def private(request):
        if request.client and request.client.host not in ('127.0.0.1','::1','testclient'):raise HTTPException(403,'Local control only')
        raw=await request.body()
        try:
            source=verify_control(request.headers.get('X-Progressor-Control',''),request.url.path,raw,engine(request).config.signing_key)
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('body')
            return source,body
        except Exception:raise HTTPException(401,'Control rejected')

    def read(store,uid):
        from .training_rhythm import proposal,active
        return {'preferences':{**links.preferences(store,uid),'rhythm':active(store,uid),'synced_at':__import__('time').time()},'weight':links.weight_choices(store,uid),
                'coach':links.coach_permissions(store,uid),'food_groups':links.FOOD_GROUPS,'help':links.FAQ,
                'rhythm':{'proposal':proposal(store,uid),'active':active(store,uid)}}

    def action(store,uid,body):
        kind=body.get('action')
        if kind=='preferences':return {'preferences':links.save_preferences(store,uid,body['patch'],body['revision'])}
        if kind=='weight':return links.reconcile_weight(store,uid,body['event_id'],body['fingerprint'],body['operation_id'])
        if kind=='coach':return links.save_coach_permission(store,uid,body['coach_id'],body['macros'],body['top_dishes'],body['days'])
        if kind=='rhythm':
            from .training_rhythm import confirm
            return confirm(store,uid,body['fingerprint'],body['base_goal_key'],body['extra'])
        if kind=='rhythm_off':
            from .training_rhythm import disable
            return disable(store,uid)
        raise ValueError('invalid_action')

    @app.get('/api/v1/me/connections')
    def settings(request:Request):return read(engine(request).store,claims(request)['sub'])

    @app.post('/api/v1/me/connections')
    async def update(request:Request):
        uid=claims(request)['sub']
        try:return action(engine(request).store,uid,await request.json())
        except (ValueError,KeyError,TypeError):raise HTTPException(409,'Данные изменились или действие недоступно. Обновите экран.')

    @app.get('/api/v1/me/connections/weight/{operation_id}')
    def weight_status(operation_id:str,request:Request):
        return links.weight_operation(engine(request).store,claims(request)['sub'],operation_id)

    @app.get('/api/v1/me/connections/weekly')
    def weekly(request:Request):return links.weekly_overview(engine(request).store,claims(request)['sub'])

    @app.get('/api/v1/me/connections/changes')
    def changes(request:Request):
        from .connection_changes import recent
        return recent(engine(request).store,claims(request)['sub'])

    @app.get('/api/v1/me/connections/weekly-plan')
    def weekly_plan(request:Request):
        from .weekly_plan import review
        return review(engine(request).store,claims(request)['sub'])

    @app.get('/api/v1/me/connections/foods')
    def food_registry(request:Request):
        claims(request)
        from shared.food_sources import REGISTRY
        return {'items':[{'code':code,'name':v['name']} for code,v in REGISTRY.items()]}

    @app.get('/api/v1/me/connections/foods/{code}')
    def food_sources(code:str,request:Request):
        from shared.food_sources import examples
        try:return examples(code,links.preferences(engine(request).store,claims(request)['sub']))
        except ValueError:raise HTTPException(404,'Источник не зарегистрирован')

    @app.get('/api/v1/me/connections/coach/{trainee_id}')
    def coach_view(trainee_id:str,request:Request,day:str|None=None):
        try:return links.coach_nutrition(engine(request).store,claims(request)['sub'],trainee_id,day)
        except PermissionError as error:raise HTTPException(403,str(error))
        except (ValueError,TypeError):raise HTTPException(422,'Invalid date or identity')

    @app.post('/internal/v1/connections/sync')
    async def sync(request:Request):
        source,body=await private(request)
        try:return links.owner_sync(engine(request).store,source,body['people'],body.get('acks',[]))
        except (ValueError,KeyError,TypeError):raise HTTPException(409,'Source sync rejected')

    @app.post('/internal/v1/connections/account')
    async def account(request:Request):
        _,body=await private(request)
        try:
            uid=subject(body['user_id'])
            if body.get('action'):return action(engine(request).store,uid,body)
            return read(engine(request).store,uid)
        except (ValueError,KeyError,TypeError):raise HTTPException(409,'Account action rejected')

    @app.post('/internal/v1/connections/weekly')
    async def private_weekly(request:Request):
        _,body=await private(request)
        try:return links.weekly_overview(engine(request).store,subject(body['user_id']))
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/connections/changes')
    async def private_changes(request:Request):
        _,body=await private(request)
        from .connection_changes import recent
        try:return recent(engine(request).store,subject(body['user_id']))
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/connections/weekly-plan')
    async def private_weekly_plan(request:Request):
        _,body=await private(request)
        from .weekly_plan import review
        try:return review(engine(request).store,subject(body['user_id']))
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/connections/coach')
    async def private_coach(request:Request):
        source,body=await private(request)
        if source!='gym':raise HTTPException(403,'Gym coach only')
        try:return links.coach_nutrition(engine(request).store,subject(body['coach_id']),subject(body['trainee_id']),body.get('day'))
        except PermissionError as error:raise HTTPException(403,str(error))
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid identity')

    @app.post('/internal/v1/connections/meal-events')
    async def private_meals(request:Request):
        source,body=await private(request)
        if source!='supply':raise HTTPException(403,'Supply reminders only')
        from .meal_anchors import events
        try:return events(engine(request).store,body['people'])
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid identities')
