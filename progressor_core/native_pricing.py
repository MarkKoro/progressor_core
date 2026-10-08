"""Trusted pricing inputs from fresh, owner-published private snapshots only."""
import json
import time
from pathlib import Path
from .adapters import read_only
from .contracts import SOURCES,subject
from .pricing import instant
from datetime import datetime,timezone

class NativePricing:
    def __init__(self,paths,max_age=90):
        self.paths=paths;self.max_age=max_age

    def __call__(self,user_id):
        user_id=subject(user_id);result={};now=datetime.now(timezone.utc)
        for source in SOURCES:
            path=Path(self.paths[source])
            if time.time()-path.stat().st_mtime>self.max_age:raise ValueError('native_pricing_unavailable')
            with read_only(path) as db:
                tariff=db.execute('SELECT body,updated_at FROM progressor_native_tariffs WHERE source=?',(source,)).fetchone()
                if not tariff or not -10<=time.time()-tariff['updated_at']<=self.max_age:raise ValueError('native_pricing_unavailable')
                if source=='food':
                    row=db.execute('SELECT premium_until FROM users WHERE telegram_id=? AND is_premium=1',(user_id,)).fetchone()
                elif source=='supply':
                    row=db.execute('SELECT premium_until_utc FROM users WHERE tg_user_id=?',(user_id,)).fetchone()
                else:
                    row=db.execute("SELECT MAX(s.expires_at) FROM subscriptions s JOIN users u ON u.id=s.user_id WHERE u.tg_id=? AND s.status='active'",(user_id,)).fetchone()
                native_end=instant(row[0]) if row and row[0] else now
                intervals=[]
                for grant in db.execute("SELECT grant_id,starts_at,expires_at FROM progressor_native_paid_grants WHERE user_id=? AND status='active' AND expires_at>? ORDER BY starts_at LIMIT 101",(user_id,now.isoformat())):
                    start=instant(grant['starts_at']);end=min(native_end,instant(grant['expires_at']))
                    if end>max(start,now):intervals.append({'grant_id':grant['grant_id'],'starts_at':start.isoformat(),'expires_at':end.isoformat()})
                result[source]={'monthly_prices':json.loads(tariff['body']),'paid_intervals':intervals}
        return result
