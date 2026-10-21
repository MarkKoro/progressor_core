"""Owner document policy on synthetic copies and actual Core read boundaries."""
import asyncio
import gc
import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_integration import fixture,USER,OTHER,KEY,TOKENS
from progressor_core.adapters import snapshot,read_only
from progressor_core.app import Config,create_app
from progressor_core.auth import sign_assertion
from progressor_core.connections import preferences,save_preferences,weight_choices,weekly_overview,owner_sync
from progressor_core.context import build_context
from progressor_core.daily_overview import daily_overview,connection_health
from progressor_core.ai_context import build_ai_context
from progressor_core.connection_changes import recent
from progressor_core.meal_anchors import events as meal_events
from progressor_core.owner_policy import enforced,parse_supply_metadata,supply_state
from progressor_core.store import Store
from shared.progressor_client import publish_source_snapshot,canonical,control_token

# Self-contained owner-protocol fixture. These arbitrary test document versions
# are not the Supply predicate or production policy. Native/export parity is
# tested in Supply tests/test_owner_consent_export.py against its real owner.
OFFER,PRIVACY='fixture-offer-v1','fixture-privacy-v1'

class ContractFixture:
    @staticmethod
    def metadata_writer(offer,privacy):
        import hashlib,uuid
        fingerprint=hashlib.sha256(json.dumps([offer,privacy]).encode()).hexdigest()
        def write(db):
            db.executescript("""DROP TABLE IF EXISTS progressor_owner_policy;
                DROP TABLE IF EXISTS progressor_owner_consent;
                CREATE TABLE progressor_owner_policy(schema_version INTEGER,source TEXT,generation TEXT,
                    generated_at_utc TEXT,policy_fingerprint TEXT,required_offer_version TEXT,required_privacy_version TEXT);
                CREATE TABLE progressor_owner_consent(native_user_id INTEGER,user_subject TEXT,
                    legal_current INTEGER,reason TEXT,policy_fingerprint TEXT);""")
            db.execute('INSERT INTO progressor_owner_policy VALUES(1,?,?,?,?,?,?)',
                ('supply',uuid.uuid4().hex,datetime.now(timezone.utc).isoformat(),fingerprint,offer,privacy))
            for row in db.execute('SELECT id,tg_user_id,consent_given,consent_offer_version,consent_privacy_version FROM users').fetchall():
                accepted=row[2]==1;has_offer=row[3]==offer;has_privacy=row[4]==privacy
                current=accepted and has_offer and has_privacy
                reason='not_accepted' if not accepted else 'current' if current else 'both_changed' if not has_offer and not has_privacy else 'offer_changed' if not has_offer else 'privacy_changed'
                db.execute('INSERT INTO progressor_owner_consent VALUES(?,?,?,?,?)',(row[0],str(row[1]),int(current),reason,fingerprint))
            db.commit()
        return write

legal=ContractFixture


class OwnerPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.root=Path(self.tmp.name);self.paths=fixture(self.root);self.uid=str(USER)
        self.now=datetime.now(timezone.utc);stamp=self.now.isoformat()
        self.gate=self.root/'owner-consent-v1-ready';self.gate.write_text('ready\n')
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:
            db.executescript('''ALTER TABLE users ADD COLUMN consent_offer_version TEXT;
                ALTER TABLE users ADD COLUMN consent_privacy_version TEXT;
                CREATE TABLE user_health_profile(user_id INTEGER PRIMARY KEY,weight_kg REAL,height_cm REAL,
                    created_at_utc TEXT,updated_at_utc TEXT,sex_at_birth TEXT,birth_year INTEGER,diet_type TEXT,
                    training_sessions_per_week INTEGER,training_minutes_per_week INTEGER);''')
            db.execute('UPDATE users SET consent_offer_version=?,consent_privacy_version=?',(OFFER,PRIVACY))
            db.execute('INSERT INTO user_health_profile VALUES(55,79,180,?,?,?,1990,?,3,180)',(stamp,stamp,'female','any'))
            db.execute('UPDATE supplement_day_state SET day=?,created_at=?',(self.now.date().isoformat(),stamp))
            db.execute('INSERT INTO lab_reports VALUES(1,55,?,?,?,?)',(self.now.date().isoformat(),'manual',stamp,stamp))
        # Food's journal day belongs to the same saved instant in its native
        # Europe/Moscow source timezone, including UTC/Moscow date boundaries.
        meal_recorded=self.now-timedelta(minutes=2)
        meal_day=meal_recorded.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()
        with closing(sqlite3.connect(self.paths['food'])) as db,db:
            db.execute('INSERT INTO meals VALUES(99,?,?,500,30,10,60,?,0)',(USER,meal_day,meal_recorded.isoformat()))
        self.metadata()
        self.store=Store(self.root/'core.db');self.store.owner_policy_gate=self.gate
        self.sync()

    def tearDown(self):gc.collect();self.tmp.cleanup()

    def metadata(self,writer=None):
        with closing(sqlite3.connect(self.paths['supply'])) as db:
            (writer or legal.metadata_writer(OFFER,PRIVACY))(db)

    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))

    def change(self,sql,values=(),*,publish=True):
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:db.execute(sql,values)
        if publish:self.metadata()
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))

    def pref(self,**value):return save_preferences(self.store,self.uid,value,preferences(self.store,self.uid)['revision'])
    def context(self,target='food'):return build_context(self.store,self.uid,now=datetime.now(timezone.utc),target=target)
    def health(self):return {r['source']:r['status'] for r in connection_health(self.store,self.uid)['items']}

    def assert_supply_absent(self):
        for target in ('food','gym','supply'):
            value=self.context(target)
            self.assertIsNone(value['supply']);self.assertNotIn('supply',value['memberships'])
            self.assertNotIn('supply',value['sources'])
            self.assertFalse(any(v['source']=='supply' for v in value['profile']['provenance'].values()))
            self.assertFalse(any(b['source']=='supply' for h in value['hints'] for b in h.get('basis',[])))
        self.assertNotIn('supply',[i['source'] for i in daily_overview(self.store,self.uid)['sections']])
        self.assertIsNone(weekly_overview(self.store,self.uid)['supply'])
        weights=weight_choices(self.store,self.uid)
        self.assertNotIn('supply',[w['source'] for w in weights['items']]);self.assertNotIn('supply',weights['targets'])
        self.assertFalse(any(i['source']=='supply' for i in recent(self.store,self.uid)['items']))
        for target in ('food','gym','supply'):
            value=build_ai_context(self.store,self.uid,target)
            self.assertFalse(value and 'supply' in value['data'])
        self.assertEqual(meal_events(self.store,[self.uid])['items'],[])

    def test_current_metadata_authorizes_same_64bit_subject_without_financial_change(self):
        value=self.context()
        self.assertEqual(value['supply']['active_supplement_count'],1)
        self.assertEqual(value['supply']['lab_report_count'],1)
        self.assertEqual(value['profile']['values']['weight_kg'],79)
        self.assertEqual(self.health()['supply'],'ready')
        self.assertEqual(value['access']['accessible_domains'],['gym','food','supply'])
        self.assertTrue(meal_events(self.store,[self.uid])['items'])
        other=build_context(self.store,str(OTHER),target='gym')
        self.assertIsNone(other['supply']);self.assertNotIn('weight_kg',other['profile']['values'])

    def test_document_mismatch_closes_all_personal_projections_not_only_labs(self):
        self.change("UPDATE users SET consent_privacy_version='old'")
        self.assertEqual(self.health()['supply'],'consent_required')
        self.assert_supply_absent()
        # Core keeps native paid entitlements and records; consent is not a
        # payment cancellation, deletion, new grant or native account mutation.
        self.assertTrue(self.context()['access']['domains']['supply'])
        self.assertTrue(any(e['source']=='supply' for e in self.store.data(self.uid)[0]))

    def test_false_native_flag_closes_supplements_and_intakes_too(self):
        self.change('UPDATE users SET consent_given=0')
        self.assert_supply_absent()

    def test_legacy_export_is_unknown_after_gate_and_shadow_before_gate(self):
        self.change('DROP TABLE progressor_owner_policy',publish=False)
        self.assertEqual(self.health()['supply'],'policy_unavailable');self.assert_supply_absent()
        self.gate.unlink()
        self.assertEqual(self.context()['supply']['active_supplement_count'],1)
        self.assertEqual(self.health()['supply'],'ready')
        self.gate.write_text('ready\n');self.assert_supply_absent()

    def test_malformed_missing_wrong_subject_and_unsupported_metadata_fail_closed(self):
        statements=[("UPDATE progressor_owner_policy SET schema_version=2",()),
            ("DELETE FROM progressor_owner_consent",()),
            ("UPDATE progressor_owner_consent SET user_subject=?",(str(OTHER),)),
            ("UPDATE progressor_owner_consent SET policy_fingerprint=?",('f'*64,)),
            ("UPDATE progressor_owner_consent SET reason='not_accepted'",()),
            ("UPDATE progressor_owner_policy SET generated_at_utc=?",((self.now-timedelta(seconds=121)).isoformat(),)),
            ("UPDATE progressor_owner_policy SET generation='bad'",()),
            ("INSERT INTO progressor_owner_policy SELECT * FROM progressor_owner_policy",())]
        for sql,args in statements:
            with self.subTest(sql=sql):
                self.metadata();self.change(sql,args,publish=False)
                self.assertEqual(self.health()['supply'],'policy_unavailable');self.assert_supply_absent()

    def test_banned_deleted_and_missing_owner_do_not_share_another_native_id(self):
        for sql in ('UPDATE users SET is_banned=1',"UPDATE users SET is_banned=0,deleted_at_utc='2026-10-20T00:00:00Z'",'DELETE FROM users'):
            with self.subTest(sql=sql):
                self.change(sql);self.assert_supply_absent()

    def test_generation_only_export_does_not_increment_user_revision_or_event_count(self):
        with self.store.connection() as db:
            before=db.execute('SELECT count(*) FROM events').fetchone()[0]
            proof=db.execute("SELECT revision FROM entities WHERE source='supply' AND entity_id='profile:55'").fetchone()[0]
            epoch=tuple(db.execute('SELECT semantic_key,opened_at,changed_at FROM owner_policy_visibility WHERE user_id=?',(self.uid,)).fetchone())
        self.metadata();self.sync()
        with self.store.connection() as db:
            self.assertEqual(before,db.execute('SELECT count(*) FROM events').fetchone()[0])
            self.assertEqual(proof,db.execute("SELECT revision FROM entities WHERE source='supply' AND entity_id='profile:55'").fetchone()[0])
            self.assertEqual(epoch,tuple(db.execute('SELECT semantic_key,opened_at,changed_at FROM owner_policy_visibility WHERE user_id=?',(self.uid,)).fetchone()))

    def test_reopen_hides_old_changes_and_does_not_invent_a_weight_change(self):
        self.pref(weight_notifications=True)
        self.change('UPDATE user_health_profile SET weight_kg=78,updated_at_utc=?',(datetime.now(timezone.utc).isoformat(),))
        self.assertTrue(any(i['kind']=='weight' for i in recent(self.store,self.uid)['items']))
        self.change("UPDATE users SET consent_privacy_version='old'")
        self.assert_supply_absent()
        self.change('UPDATE user_health_profile SET weight_kg=77,updated_at_utc=?',(datetime.now(timezone.utc).isoformat(),))
        self.change('UPDATE users SET consent_privacy_version=?',(PRIVACY,))
        self.assertEqual(self.context()['profile']['values']['weight_kg'],77)
        self.assertFalse(any(i['source']=='supply' for i in recent(self.store,self.uid)['items']))
        self.assertFalse(any(h['key']=='change_weight.v1' for h in self.context()['hints']))
        self.change('UPDATE user_health_profile SET weight_kg=76,updated_at_utc=?',(datetime.now(timezone.utc).isoformat(),))
        self.assertTrue(any(i['kind']=='weight' and i['details']['after']==76 for i in recent(self.store,self.uid)['items']))

    def test_new_policy_fingerprint_opens_new_visibility_epoch_without_catchup(self):
        self.change('UPDATE user_health_profile SET weight_kg=78,updated_at_utc=?',(datetime.now(timezone.utc).isoformat(),))
        self.assertTrue(recent(self.store,self.uid)['items'])
        self.change('UPDATE users SET consent_offer_version=?',('fixture-offer-v2',),publish=False)
        self.metadata(legal.metadata_writer('fixture-offer-v2',PRIVACY));self.sync()
        self.assertEqual(self.context()['profile']['values']['weight_kg'],78)
        self.assertFalse(any(i['source']=='supply' for i in recent(self.store,self.uid)['items']))

    def test_rest_hides_context_and_summary_but_keeps_explicit_own_weight_choices(self):
        self.pref(paused=True)
        self.assertIsNone(self.context()['supply']);self.assertEqual(daily_overview(self.store,self.uid)['sections'],[])
        self.assertIsNone(weekly_overview(self.store,self.uid)['supply'])
        self.assertIsNone(build_ai_context(self.store,self.uid,'gym'))
        self.assertTrue(any(i['source']=='supply' for i in weight_choices(self.store,self.uid)['items']))
        self.assertEqual(meal_events(self.store,[self.uid])['items'],[])
        self.change("UPDATE users SET consent_privacy_version='old'")
        self.assertFalse(any(i['source']=='supply' for i in weight_choices(self.store,self.uid)['items']))

    def test_source_toggle_disabled_config_expiry_and_stale_remain_independent(self):
        self.pref(sources={'gym':True,'food':True,'supply':False});self.assert_supply_absent()
        self.pref(sources={'gym':True,'food':True,'supply':True})
        self.store.enabled_sources=('gym','food');self.assert_supply_absent()
        self.store.enabled_sources=('gym','food','supply')
        self.change("UPDATE users SET premium_until_utc='2000-01-01T00:00:00Z'");self.assert_supply_absent()
        self.change("UPDATE users SET premium_until_utc='2030-01-01T00:00:00Z'")
        self.store.failed('supply','fixture_failure')
        self.assertIsNone(weekly_overview(self.store,self.uid)['supply'])
        self.assertFalse(any(i['source']=='supply' for i in weight_choices(self.store,self.uid)['items']))
        self.assertIsNone(self.context()['supply']['reported_profile'])

    def test_pending_owner_commands_are_withheld_after_legal_close(self):
        from progressor_core.contracts import canonical as encode
        with self.store.connection() as db:
            db.execute("INSERT INTO connection_commands VALUES(?,?,?,?,?,?,'pending',NULL)",
                ('fixture-command',self.uid,'supply',encode({'kind':'confirmed_weight','weight_kg':80}),time.time(),time.time()+3600))
        self.assertEqual(len(owner_sync(self.store,'supply',[self.uid],[])['commands']),1)
        self.change("UPDATE users SET consent_offer_version='old'")
        self.assertEqual(owner_sync(self.store,'supply',[self.uid],[])['commands'],[])
        self.change('UPDATE users SET consent_offer_version=?',(OFFER,))
        # A reopened source cannot deliver a previously confirmed command from
        # the earlier visibility epoch, even if its ordinary expiry is later.
        self.assertEqual(owner_sync(self.store,'supply',[self.uid],[])['commands'],[])

    def test_gate_access_error_and_dangling_gate_fail_closed(self):
        with patch.object(Path,'lstat',side_effect=PermissionError('fixture denial')):self.assertTrue(enforced(self.store))
        with patch.object(Path,'lstat',return_value=object()):self.assertTrue(enforced(self.store))
        self.gate.unlink();self.assertFalse(enforced(self.store))

    def test_signed_public_private_paths_share_policy_and_cannot_override_subject(self):
        config=Config(str(self.root/'api-core.db'),KEY,self.paths,TOKENS,background=False)
        with TestClient(create_app(config)) as client:
            store=client.app.state.engine.store;store.owner_policy_gate=self.gate;client.app.state.engine.poll()
            own={'X-Progressor-Auth':sign_assertion({'id':USER},int(time.time()),'core',KEY)}
            other={'X-Progressor-Auth':sign_assertion({'id':OTHER},int(time.time()),'core',KEY)}
            path='/api/v1/me/context?target=food'
            self.assertEqual(client.get(path).status_code,401)
            self.assertEqual(client.get(path,headers=own).json()['supply']['active_supplement_count'],1)
            self.assertIsNone(client.get(path+'&user_id='+self.uid,headers=other).json()['supply'])
            self.change("UPDATE users SET consent_privacy_version='old'");client.app.state.engine.poll()
            self.assertIsNone(client.get(path,headers=own).json()['supply'])
            for path,body in [('/internal/v1/profile',{'user_id':self.uid}),('/internal/v1/ai-context',{'user_id':self.uid}),
                    ('/internal/v1/connections/weekly',{'user_id':self.uid}),('/internal/v1/connections/meal-events',{'people':[self.uid]})]:
                raw=canonical(body).encode();source='supply' if path.endswith('meal-events') else 'gym'
                response=client.post(path,content=raw,headers={'Content-Type':'application/json','X-Progressor-Control':control_token(source,path,raw,KEY)})
                self.assertEqual(response.status_code,200,response.text)
                value=response.json()
                if path.endswith('/profile'):self.assertFalse(any(p['source']=='supply' for p in value['provenance'].values()))
                elif path.endswith('ai-context'):self.assertFalse(value and 'supply' in value.get('data',{}))
                elif path.endswith('/weekly'):self.assertIsNone(value['supply'])
                else:self.assertEqual(value['items'],[])


if __name__=='__main__':unittest.main()
