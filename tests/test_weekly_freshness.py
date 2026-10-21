"""Weekly aggregates require fresh, currently permitted source projections."""
import gc
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from test_integration import fixture, USER, OTHER, NOW, KEY, TOKENS
from progressor_core.adapters import snapshot
from progressor_core.app import Config, create_app
from progressor_core.auth import sign_assertion
from progressor_core.connections import preferences, save_preferences, weekly_overview
from progressor_core.context import build_context
from progressor_core.store import Store
from shared.progressor_client import canonical, control_token


class WeeklyFreshness(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.root=Path(self.tmp.name);self.paths=fixture(self.root)
        self.store=Store(self.root/'core.db');self.uid=str(USER)
        self.sync()

    def tearDown(self):
        gc.collect();self.tmp.cleanup()

    def sync(self):
        for source,path in self.paths.items():self.store.reconcile(source,snapshot(source,path))

    def weekly(self):return weekly_overview(self.store,self.uid,NOW)

    def pref(self,**patch):
        return save_preferences(self.store,self.uid,patch,preferences(self.store,self.uid)['revision'])

    def event(self,name,*,owner=USER,status='taken',day=None,deleted=False):
        entity_id='intake:weekly-freshness:'+name
        payload={'entity_id':entity_id,'revision':2 if deleted else 1}
        if deleted:payload['deleted']=True
        else:payload.update(status=status,source_local_date=day or NOW.date().isoformat(),timezone='UTC')
        self.store.accept({'event_id':'weekly-freshness:'+name+(':deleted' if deleted else ''),
            'event_type':'entity.deleted' if deleted else 'supplement.taken','source':'supply',
            'schema_version':1,'user_id':str(owner),'occurred_at':NOW.isoformat(),
            'correlation_id':'synthetic-weekly','payload':payload})

    def stored_rows(self):
        with self.store.connection() as db:
            return [tuple(r) for r in db.execute("SELECT entity_id,revision,deleted,payload FROM entities WHERE user_id=? AND source='supply' ORDER BY entity_id",(self.uid,))]

    def test_fresh_aggregate_exceeds_recent_90_and_keeps_owner_status_window_and_tombstones(self):
        for i in range(130):self.event(str(i))
        self.event('other-owner',owner=OTHER)
        self.event('skipped',status='skipped')
        self.event('old',day=(NOW-timedelta(days=8)).date().isoformat())
        self.event('deleted');self.event('deleted',deleted=True)
        self.assertEqual(len(build_context(self.store,self.uid,NOW)['supply']['recent_intakes']),90)
        value=self.weekly()
        self.assertEqual(value['supply'],{'active_supplements':1,'recorded_intakes':131})
        self.assertEqual(value['sources']['supply']['status'],'ok')

    def test_failed_source_is_unknown_instead_of_zero_or_previous_sql_total(self):
        original=self.stored_rows();self.store.failed('supply','synthetic_read_failure')
        value=self.weekly()
        self.assertIsNone(value['supply'])
        self.assertEqual(value['sources']['supply']['status'],'degraded')
        self.assertEqual(self.stored_rows(),original)

    def test_success_older_than_freshness_cutoff_is_unknown(self):
        with self.store.connection() as db:
            db.execute("UPDATE source_state SET status='ok',last_success=? WHERE source='supply'",(time.time()-121,))
        value=self.weekly();self.assertIsNone(value['supply'])
        self.assertEqual(value['sources']['supply']['status'],'degraded')

    def test_missing_success_timestamp_is_unknown(self):
        with self.store.connection() as db:db.execute("UPDATE source_state SET last_success=NULL WHERE source='supply'")
        value=self.weekly();self.assertIsNone(value['supply'])
        self.assertEqual(value['sources']['supply']['status'],'degraded')

    def test_successful_reconcile_restores_full_aggregate_without_data_loss(self):
        self.store.failed('supply','synthetic_read_failure')
        self.assertIsNone(self.weekly()['supply'])
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
        self.assertEqual(self.weekly()['supply'],{'active_supplements':1,'recorded_intakes':1})

    def test_source_optout_and_reenable_apply_to_next_read_without_deleting_rows(self):
        original=self.stored_rows()
        self.pref(sources={'gym':True,'food':True,'supply':False})
        self.assertIsNone(self.weekly()['supply'])
        self.assertNotIn('supply',self.weekly()['sources'])
        self.assertEqual(self.stored_rows(),original)
        self.pref(sources={'gym':True,'food':True,'supply':True})
        self.assertEqual(self.weekly()['supply']['recorded_intakes'],1)

    def test_config_disabled_source_is_not_aggregated(self):
        self.store.enabled_sources=('gym','food')
        self.assertIsNone(self.weekly()['supply'])

    def test_expired_access_remains_absent_and_saved_history_is_preserved(self):
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:
            db.execute("UPDATE users SET premium_until_utc='2000-01-01T00:00:00Z'")
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
        original=self.stored_rows();self.assertIsNone(self.weekly()['supply'])
        self.assertEqual(self.stored_rows(),original)

    def test_rest_is_absent_and_resume_keeps_aggregate(self):
        original=self.stored_rows();self.pref(paused=True)
        self.assertIsNone(self.weekly()['supply']);self.assertEqual(self.stored_rows(),original)
        self.pref(paused=False);self.assertEqual(self.weekly()['supply']['recorded_intakes'],1)

    def test_fresh_empty_history_is_known_zero_and_deleted_records_do_not_count(self):
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:
            db.execute('DELETE FROM user_supplements');db.execute('DELETE FROM supplement_day_state')
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
        value=self.weekly()
        self.assertEqual(value['supply'],{'active_supplements':0,'recorded_intakes':0})
        self.assertEqual(value['sources']['supply']['status'],'ok')
        with self.store.connection() as db:
            self.assertGreater(db.execute("SELECT count(*) FROM entities WHERE user_id=? AND source='supply' AND deleted=1",(self.uid,)).fetchone()[0],0)

    def test_missing_membership_is_absent_not_empty_fresh_history(self):
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:db.execute('DELETE FROM users')
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
        self.assertIsNone(self.weekly()['supply'])

    def test_existing_narrow_consent_semantics_are_not_replaced_by_this_freshness_fix(self):
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:db.execute('UPDATE users SET consent_given=0')
        self.store.reconcile('supply',snapshot('supply',self.paths['supply']))
        self.assertEqual(self.weekly()['supply'],{'active_supplements':1,'recorded_intakes':1})

    def test_public_and_private_routes_preserve_subject_and_stale_result(self):
        current=datetime.now(timezone.utc)
        with closing(sqlite3.connect(self.paths['supply'])) as db,db:
            db.execute('UPDATE supplement_day_state SET day=?,created_at=?',(current.date().isoformat(),current.isoformat()))
        config=Config(str(self.root/'api-core.db'),KEY,self.paths,TOKENS,background=False)
        with TestClient(create_app(config)) as client:
            engine=client.app.state.engine;engine.poll()
            path='/api/v1/me/connections/weekly'
            own={'X-Progressor-Auth':sign_assertion({'id':USER},int(time.time()),'core',KEY)}
            other={'X-Progressor-Auth':sign_assertion({'id':OTHER},int(time.time()),'core',KEY)}
            self.assertEqual(client.get(path).status_code,401)
            self.assertEqual(client.get(path,headers=own).json()['supply']['recorded_intakes'],1)
            self.assertIsNone(client.get(path+'?user_id='+self.uid,headers=other).json()['supply'])
            engine.store.failed('supply','synthetic_read_failure')
            public=client.get(path,headers=own)
            self.assertEqual(public.status_code,200);self.assertIsNone(public.json()['supply'])
            self.assertEqual(public.json()['sources']['supply']['status'],'degraded')
            private_path='/internal/v1/connections/weekly';raw=canonical({'user_id':self.uid}).encode()
            private=client.post(private_path,content=raw,headers={'X-Progressor-Control':control_token('gym',private_path,raw,KEY),'Content-Type':'application/json'})
            self.assertEqual(private.status_code,200);self.assertIsNone(private.json()['supply'])
            self.assertEqual(private.json()['sources']['supply']['status'],'degraded')


if __name__=='__main__':unittest.main()
