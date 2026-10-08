import json,os,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from contextlib import closing
from shared.native_subscription import prepare_metadata

class LegacyPaidProof(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'));self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'owner.db';self.now=datetime.now(timezone.utc)
    def test_food_real_legacy_plan_id_is_credited_but_payg_and_ambiguous_gift_are_not(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE users(telegram_id INTEGER,premium_until TEXT);CREATE TABLE payments(id INTEGER,user_id INTEGER,telegram_charge_id TEXT,provider_charge_id TEXT,ts REAL,payment_succeeded_at TEXT,payload TEXT,currency TEXT,amount_stars INTEGER,amount_rub INTEGER);CREATE TABLE payment_orders(id TEXT,plan_id TEXT,days INTEGER,kind TEXT,status TEXT);')
            for uid,extra in ((123,0),(456,3)):
                db.execute('INSERT INTO users VALUES(?,?)',(uid,(self.now+timedelta(days=180+extra)).isoformat()))
                db.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,uid,None,'paid-proof-'+str(uid),self.now.timestamp(),self.now.isoformat(),json.dumps({'kind':'subscription','plan_id':'m6'}),'RUB',None,1790))
            db.execute('INSERT INTO payments VALUES(9,123,NULL,?, ?,?, ?,?,NULL,100)',('topup-proof',self.now.timestamp(),self.now.isoformat(),json.dumps({'kind':'payg_topup','plan_id':'m1'}),'RUB'))
        prepare_metadata(self.path,'food',{'RUB':39900,'XTR':266})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT user_id,amount FROM progressor_native_paid_grants').fetchall(),[('123',179000)])
    def test_gym_verified_old_provider_metadata_plan_matches_subscription_and_excludes_test(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE users(id INTEGER,tg_id INTEGER);CREATE TABLE payments(id INTEGER,user_id INTEGER,provider TEXT,external_id TEXT,status TEXT,finalized_at TEXT,amount INTEGER,currency TEXT,payload_json TEXT);CREATE TABLE subscriptions(user_id INTEGER,plan TEXT,started_at TEXT,expires_at TEXT);')
            for uid,test in ((1,False),(2,True)):
                db.execute('INSERT INTO users VALUES(?,?)',(uid,uid+100))
                db.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?)',(uid,uid,'yookassa','paid-proof-'+str(uid),'succeeded',self.now.isoformat(),10000,'RUB',json.dumps({'test':test,'metadata':{'kind':'subscription','plan_id':'1m','user_id':str(uid)}})))
                db.execute('INSERT INTO subscriptions VALUES(?,?,?,?)',(uid,'1m',self.now.isoformat(),(self.now+timedelta(days=30)).isoformat()))
        prepare_metadata(self.path,'gym',{'RUB':10000,'XTR':80})
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT user_id,amount FROM progressor_native_paid_grants').fetchall(),[('101',10000)])
