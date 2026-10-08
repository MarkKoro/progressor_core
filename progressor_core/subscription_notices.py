"""One financial expiry event, one existing bot sender, durable at-most-once.

Expired access never deletes content. Telegram timeouts are not read receipts
and never authorize a second sender. Only a confirmed rejection permits retry.
"""
import hashlib
import json
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .adapters import read_only
from .contracts import SOURCES
from .access import entitlements
from .pricing import instant,contiguous_end

NAMES={'food':'Еда','gym':'Тренировки','supply':'БАДы'}
SCHEMA='''CREATE TABLE IF NOT EXISTS subscription_notices(
event_key TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,ends_at TEXT NOT NULL,
source TEXT NOT NULL,status TEXT NOT NULL,text TEXT NOT NULL,created_at REAL NOT NULL,
not_before REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,blocked_sources TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS subscription_notice_days(user_id TEXT NOT NULL,day TEXT NOT NULL,event_key TEXT NOT NULL,PRIMARY KEY(user_id,day));'''

def choose(meta,excluded=(),fallback=None):
    choices=[s for s in SOURCES if meta.get(s,{}).get('known') and s not in excluded]
    if not choices:return None
    return max(choices,key=lambda s:(meta[s].get('count',0),meta[s].get('last_at',''),s==fallback,s))

class SubscriptionNotices:
    def __init__(self,store,source_paths=None,metadata=None):
        self.store=store;self.paths=source_paths or {};self.metadata=metadata or self._metadata
        with store.connection() as db:db.executescript(SCHEMA)

    def _metadata(self,user_id,now):
        result={}
        for source in SOURCES:
            try:
                path=Path(self.paths[source])
                if not -10<=time.time()-path.stat().st_mtime<=90:continue
                with read_only(path) as db:
                    if source=='food':row=db.execute('SELECT telegram_id FROM users WHERE telegram_id=?',(user_id,)).fetchone()
                    elif source=='gym':row=db.execute('SELECT tg_id FROM users WHERE tg_id=?',(user_id,)).fetchone()
                    else:row=db.execute("SELECT tg_user_id,tz_name FROM users WHERE tg_user_id=? AND COALESCE(is_banned,0)=0 AND COALESCE(deleted_at_utc,'')=''",(user_id,)).fetchone()
                    if not row:continue
                    activity=db.execute('SELECT COALESCE(sum(count),0),COALESCE(max(last_at),\'\') FROM progressor_bot_activity WHERE user_id=? AND day>=?',(user_id,(now-timedelta(days=14)).date().isoformat())).fetchone()
                    tz=row['tz_name'] if source=='supply' else 'Europe/Moscow'
                    if source=='food':
                        pref=db.execute('SELECT timezone FROM progressor_food_preferences WHERE user_id=?',(user_id,)).fetchone()
                        if pref:tz=pref['timezone']
                    result[source]={'known':True,'count':activity[0],'last_at':activity[1],'timezone':tz or 'UTC'}
            except (OSError,KeyError,ValueError):continue
            except Exception:continue # An unavailable source is never an empty diet or expired payment.
        return result

    def candidates(self,user_id,now):
        entities,_,state=self.store.data(user_id);access=entitlements(self.store,user_id,now,entities)
        effective={};intervals={s:[] for s in SOURCES}
        with self.store.connection() as db:
            for row in db.execute('SELECT source,starts_at,expires_at FROM bundle_component_intervals WHERE user_id=?',(user_id,)):
                intervals[row['source']].append(dict(row))
            payment=db.execute("SELECT source FROM bundle_orders WHERE user_id=? AND status='paid' ORDER BY paid_at DESC LIMIT 1",(user_id,)).fetchone()
        for source in SOURCES:
            native=access['native_until'][source]
            if native:intervals[source].append({'starts_at':now.isoformat(),'expires_at':native})
            effective[source]=contiguous_end(intervals[source],now)
        result=[];bundle=access.get('bundle_until')
        if bundle and now<instant(bundle)<=now+timedelta(days=3):
            remains=[NAMES[s] for s in SOURCES if effective[s] and effective[s]>instant(bundle)+timedelta(seconds=1)]
            text='Общая подписка Progressor заканчивается '+instant(bundle).strftime('%d.%m.%Y')+'.'
            text+=' Отдельный доступ продолжит действовать: '+', '.join(remains)+'.' if remains else ' Чтобы сохранить общий доступ, её можно продлить.'
            text+=' История и записи сохраняются; автосписания нет.'
            result.append({'kind':'bundle','ends_at':bundle,'text':text,'fallback':payment['source'] if payment else None})
        native_groups={}
        for source in SOURCES:
            fresh=state.get(source,{}).get('status')=='ok' and time.time()-(state.get(source,{}).get('last_success') or 0)<120
            end=access['native_until'][source]
            if not fresh or not end or not now<instant(end)<=now+timedelta(days=3):continue
            if effective[source] and effective[source]>instant(end)+timedelta(seconds=1):continue
            # The same date covered by the common warning must not generate three reminders.
            if bundle and instant(end).date()==instant(bundle).date():continue
            native_groups.setdefault(instant(end).date().isoformat(),[]).append((source,end))
        for date,rows in native_groups.items():
            end=min(instant(r[1]) for r in rows).isoformat();names=', '.join(NAMES[s] for s,_ in rows)
            result.append({'kind':'native:'+','.join(sorted(s for s,_ in rows)),'ends_at':end,'fallback':rows[0][0],
                           'text':f'Подписка на {names} заканчивается {instant(end).strftime("%d.%m.%Y")}. Остальные действующие подписки продолжают работать. История и записи сохраняются; автосписания нет.'})
        return sorted(result,key=lambda r:(r['kind']!='bundle',r['ends_at']))

    def claim(self,source,after='',now=None):
        if source not in SOURCES:raise ValueError('invalid_sender')
        now=instant(now or datetime.now(timezone.utc));items=[];cursor=''
        with self.store.connection() as db:
            users=[r[0] for r in db.execute('SELECT user_id FROM identities WHERE user_id>? ORDER BY user_id LIMIT 101',(after,))]
        for user_id in users[:100]:
            cursor=user_id;meta=self.metadata(user_id,now)
            for candidate in self.candidates(user_id,now):
                if len(items)>=20:break
                key=hashlib.sha256((user_id+'|'+candidate['kind']+'|'+candidate['ends_at']).encode()).hexdigest()
                with self.store.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute('SELECT * FROM subscription_notices WHERE event_key=?',(key,)).fetchone()
                    sender=row['source'] if row else choose(meta,fallback=candidate['fallback'])
                    if sender!=source or not meta.get(sender,{}).get('known'):continue
                    try:
                        name=meta[sender].get('timezone','UTC')
                        local=now.astimezone(timezone.utc if name=='UTC' else ZoneInfo(name))
                    except (KeyError,ValueError):continue
                    if not 8<=local.hour<22:continue
                    if row and (row['status'] not in ('queued','retry') or row['not_before']>now.timestamp() or row['attempts']>=3):continue
                    day=local.date().isoformat()
                    previous=db.execute('SELECT event_key FROM subscription_notice_days WHERE user_id=? AND day=?',(user_id,day)).fetchone()
                    if previous and (previous[0]!=key or not row or row['status']!='retry'):continue
                    if not row:
                        db.execute('INSERT INTO subscription_notices(event_key,user_id,kind,ends_at,source,status,text,created_at) VALUES(?,?,?,?,?,\'queued\',?,?)',(key,user_id,candidate['kind'],candidate['ends_at'],sender,candidate['text'],now.timestamp()))
                    db.execute("UPDATE subscription_notices SET status='reserved',attempts=attempts+1 WHERE event_key=?",(key,))
                    db.execute('INSERT OR IGNORE INTO subscription_notice_days VALUES(?,?,?)',(user_id,day,key))
                    items.append({'event_key':key,'user_id':user_id,'kind':candidate['kind'],'text':candidate['text']})
            if len(items)>=20:break
        return {'items':items[:20],'next':cursor if len(users)>100 or len(items)>=20 else None}

    def acknowledge(self,source,key,status,retry_after=0,now=None):
        now=instant(now or datetime.now(timezone.utc))
        if status not in ('sent','uncertain','retry','blocked','deferred'):raise ValueError('invalid_delivery_status')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM subscription_notices WHERE event_key=?',(key,)).fetchone()
            if not row or row['source']!=source:raise ValueError('delivery_owner_mismatch')
            if row['status']!='reserved':return {'status':row['status']}
            sender=source;not_before=0;blocked=json.loads(row['blocked_sources'])
            if status=='deferred':
                status='queued';not_before=now.timestamp()+60
                db.execute('UPDATE subscription_notices SET attempts=max(0,attempts-1) WHERE event_key=?',(key,))
                db.execute('DELETE FROM subscription_notice_days WHERE event_key=?',(key,))
            if status=='retry':
                if type(retry_after) not in (int,float) or not 0<retry_after<=86400:raise ValueError('invalid_retry')
                not_before=now.timestamp()+retry_after+1
            if status=='blocked':
                blocked.append(source);sender=choose(self.metadata(row['user_id'],now),excluded=blocked) or source
                if sender!=source:
                    status='queued';db.execute('DELETE FROM subscription_notice_days WHERE event_key=?',(key,))
            db.execute('UPDATE subscription_notices SET source=?,status=?,not_before=?,blocked_sources=? WHERE event_key=?',(sender,status,not_before,json.dumps(blocked),key))
        return {'status':status}
