"""Regression gates for the 2026-09-26 review (R01--R12)."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from quant_workbench.model import validate_package, ContractError
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository
from quant_workbench.metrics import equity_drawdown
from quant_workbench.research import review_result, ResearchSnapshots
from quant_workbench.source_safety import SourceConflict, data_nature
from quant_workbench.cn_market import load_profile, scenario_fingerprint, validate
from quant_workbench.adapters.mlflow_readonly import isolated_mlflow_client

ROOT=Path(__file__).resolve().parents[3]
FIXTURE=ROOT/'extensions/workbench/examples/generic-result.json'


def package():
    p=json.loads(FIXTURE.read_text())
    p['evidence']={'comparison':{'execution_id':'scenario1','initial_equity':1000000,
        'cashflow_policy':'none','price_basis':'adjusted','benchmark_id':'benchmark1'}}
    p['run']['dataset']={'id':'dataset1','version':'content1'}
    p['series']=p['series'][:1]
    p['series'][0]['currency']='CNY'
    return p


class QueryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=LocalResultRepository(self.tmp.name);self.s=WorkbenchService(self.repo)

    def publish(self,p,identity):
        return self.s.import_package('test',identity,'generic_v1',p)['run_id']

    def test_R09_all_empty_states_and_scalar(self):
        for axis in ('scalar','step','trading_date','time'):
            for status in ('empty','unsupported','not_recorded','error'):
                p=package();p['series'][0].update(axis=axis,step_kind='iteration',availability=status,points=[])
                with self.subTest(axis=axis,status=status): validate_package(p)
        p=package();p['series'][0].update(points=[])
        with self.assertRaises(ContractError):validate_package(p)

    def test_R11_instants_normalized_ordered_and_deduplicated(self):
        p=package();p['series'][0].update(axis='time',points=[{'x':'2026-01-01T01:00:00+01:00','value':1},
                                                                       {'x':'2026-01-01T00:30:00Z','value':2}])
        v=validate_package(p)
        self.assertEqual(v['series'][0]['points'][0]['x'],'2026-01-01T00:00:00.000000+00:00')
        p['series'][0]['points'].reverse()
        with self.assertRaises(ContractError): validate_package(p)
        p['series'][0]['points']=[{'x':'2026-01-01T01:00:00+01:00','value':1},{'x':'2026-01-01T00:00:00Z','value':2}]
        with self.assertRaises(ContractError): validate_package(p)
        # Simulate legacy stored offset text without modifying immutable objects.
        a=self.publish(package(),'a');b=self.publish(package(),'b')
        with self.repo._connect() as conn:
            conn.execute('UPDATE runs SET created_at=? WHERE run_id=?',('2026-01-01T01:00:00+01:00',a))
            conn.execute('UPDATE runs SET created_at=? WHERE run_id=?',('2026-01-01T00:30:00Z',b))
        first=self.s.list_runs(1);self.assertEqual(first['items'][0]['run_id'],b)
        self.assertEqual(self.s.list_runs(1,first['next_cursor'])['items'][0]['run_id'],a)

    def test_R05_positive_equity_and_independent_negative_dimensions(self):
        p=package();a=self.publish(p,'a');b=self.publish(p,'b')
        self.assertTrue(self.s.compare([a,b],'platform.equity')['ranking_allowed'])
        mutations=[lambda q:q['run']['dataset'].update(id='other'),
                   lambda q:q['run']['dataset'].update(version=None),
                   lambda q:q['series'][0].update(currency=None),
                   lambda q:q['series'][0]['points'][1].update(value=None,reason='missing'),
                   lambda q:q['series'][0]['points'].pop(1),
                   lambda q:q['evidence']['comparison'].update(initial_equity=None),
                   lambda q:q['evidence']['comparison'].update(benchmark_id='other'),
                   lambda q:q['evidence'].update(fixture=True)]
        for i,mutate in enumerate(mutations):
            q=copy.deepcopy(p);mutate(q);c=self.publish(q,str(i))
            with self.subTest(i=i): self.assertFalse(self.s.compare([a,c],'platform.equity')['ranking_allowed'])

    def test_R05_generic_training_has_no_CN_dependency(self):
        p=package();p['series'][0].update(metric_id='loss',axis='step',step_kind='epoch',unit='ratio',
            definition_id='mse.v1',currency=None,points=[{'x':0,'value':2},{'x':1,'value':1}])
        p['evidence']={'comparison':{'evaluation_id':'mse-test-split1'}}
        a=self.publish(p,'a');b=self.publish(p,'b')
        assessment=self.s.compare([a,b],'loss')
        # U18: training metrics are compared side by side only; ranking is reserved for backtest rows.
        self.assertFalse(assessment['ranking_allowed'])
        self.assertIn('group_only_side_by_side:training',assessment['reasons'])
        self.assertEqual(assessment['status'],'partial')
        self.assertTrue(assessment['overlay_allowed'])
        p['series'][0]['step_kind']='iteration';c=self.publish(p,'c')
        self.assertFalse(self.s.compare([a,c],'loss')['overlay_allowed'])

    def test_R06_long_series_summary_API_CLI_full_revision(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        p=package();p['series'][0]['points']=[{'x':str(date(2000,1,1)+timedelta(days=i)),'value':1000000+i} for i in range(2002)]
        p['series'][0]['points'][-1]['value']=500000
        rid=self.publish(p,'long');rev=self.s.get_run(rid)['revision_id']
        page=self.s.get_series(rid,'platform.equity',rev)
        self.assertEqual(len(page['series']['points']),2000)
        self.assertEqual(page['summary']['last'],500000)
        self.assertEqual(page['next_offset'],2000)
        tail=self.s.get_series(rid,'platform.equity',rev,offset=2000)
        self.assertEqual(tail['summary'],page['summary'])
        expected=self.s.review(rid,rev)
        self.assertEqual(expected['facts']['ending_equity'],500000)
        self.assertLess(expected['facts']['max_observed_drawdown'],-.5)
        cli=json.loads(subprocess.check_output([sys.executable,'-m','quant_workbench.cli','--root',self.tmp.name,'review',rid,'--revision-id',rev]))
        http=TestClient(create_app(self.s)).get(f'/v1/runs/{rid}/review?revision_id={rev}').json()
        self.assertEqual(expected,cli);self.assertEqual(expected,http)

    def test_R10_missing_endpoints_and_full_vs_observed_drawdown(self):
        p=package();p['series'][0]['points']=[{'x':'2021-01-01','value':90},{'x':'2021-01-02','value':95}]
        p['evidence']['comparison']['initial_equity']=100
        facts=review_result(p)['facts']
        self.assertEqual(facts['max_observed_drawdown'],0)
        self.assertAlmostEqual(facts['max_full_drawdown'],-.1)
        p['series'][0]['points'][-1].update(value=None,reason='missing_in_source')
        facts=review_result(p)['facts']
        self.assertIsNone(facts['ending_equity']);self.assertIsNone(facts['observed_equity_change'])
        self.assertIsNone(facts['max_observed_drawdown'])
        self.assertEqual(facts['last_valid_equity']['x'],'2021-01-01')
        p['series'][0]['points'][0].update(value=None,reason='missing')
        self.assertIsNone(review_result(p)['facts']['first_observed_equity'])

    def test_R12_every_closed_nested_object_rejects_unknown(self):
        from quant_workbench.cn_schema import SHAPES
        original=load_profile(ROOT/'configs/cn/profile.json')
        def objects(value,path=()):
            if isinstance(value,dict):
                yield path
                for k,v in value.items(): yield from objects(v,path+(k,))
        for path in objects(SHAPES):
            b=copy.deepcopy(original);o=b
            for key in path:o=o[key]
            o['misspelled']='unexpected'
            with self.subTest(path=path),self.assertRaises(ValueError): validate(b)
        for path,value in [(('research','model','num_threads'),True),(('research','model','learning_rate'),float('nan')),
                           (('rules','fees','rounding_unit'),'.05'),(('research','annualization','native_portfolio_days'),252)]:
            b=copy.deepcopy(original);o=b
            for key in path[:-1]:o=o[key]
            o[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(ValueError):validate(b)

    def test_R04_client_only_sees_copy_even_on_failure(self):
        source=Path(self.tmp.name)/'source.db'
        with sqlite3.connect(source) as db:db.execute('CREATE TABLE original (v INT)')
        before=source.read_bytes()
        def migrate(tracking_uri):
            with sqlite3.connect(tracking_uri.removeprefix('sqlite:///')) as db:db.execute('CREATE TABLE migrated (v INT)')
            raise RuntimeError('simulated incompatible client')
        with patch('mlflow.tracking.MlflowClient',side_effect=migrate):
            with self.assertRaises(RuntimeError):
                with isolated_mlflow_client('sqlite:///'+str(source)):pass
        self.assertEqual(source.read_bytes(),before)


class ExportRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.session=self.root/'log/2026-01-01_00-00-00-000000'
        from pandas.io.parquet import get_engine
        get_engine('pyarrow')  # Load extension registrations before sys.modules is patched.
        self.objects={}
        fake=types.ModuleType('rdagent.core.serialization');fake.load=self.load
        self.enterContext(patch.dict(sys.modules,{'rdagent':types.ModuleType('rdagent'),
            'rdagent.core':types.ModuleType('rdagent.core'),'rdagent.core.serialization':fake}))
        spec=importlib.util.spec_from_file_location('export_review',ROOT/'scripts/export_rdagent_research.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def load(self,f):
        obj=self.objects[f.name]
        if isinstance(obj,Exception): raise obj
        return obj

    def event(self,loop,tag,second,obj):
        path=self.session/f'{loop}/{tag}/pid/2026-01-01_00-00-{second:02d}-000000.pkl'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'trusted-test-placeholder');self.objects[str(path)]=obj

    def runner(self,loop,second,report=True,effective=True):
        import pandas as pd
        ws=self.root/f'workspace-{loop}-{second}';ws.mkdir()
        if report:pd.DataFrame({'account':[100.,110.]},index=pd.to_datetime(['2021-01-01','2021-01-02'])).to_parquet(ws/'ret.parquet')
        if effective:
            bundle=load_profile(ROOT/'configs/cn/profile.json')
            bundle['account']['assumptions']+=['audit-placeholder-credential']
            bundle['fingerprint']=scenario_fingerprint(bundle)
            (ws/'effective.json').write_text(json.dumps(bundle))
        obj=types.SimpleNamespace(result=pd.Series({'IC':.1+second/100}),sub_tasks=[types.SimpleNamespace(factor_name=f'factor{second}')],
            sub_workspace_list=[],experiment_workspace=types.SimpleNamespace(workspace_path=str(ws)))
        self.event(loop,'runner result',second,obj)
        return ws

    def export(self,synthetic=True):
        (self.root/'.env').write_text('API_KEY=audit-placeholder-credential\n')
        self.module.export(self.root,self.root/'out',self.root/'db',synthetic)
        store=ResearchSnapshots(self.root/'out')
        return [store.detail(p.stem) for p in (self.root/'out').glob('*.json') if store.detail(p.stem).get('status')!='session_index']

    def test_R01_separate_success_then_failure_and_interleaved_feedback(self):
        self.runner('Loop_0',1);self.runner('Loop_1',2,report=False)
        self.event('Loop_0','feedback',3,types.SimpleNamespace(decision=True))
        rows=self.export();self.assertEqual(len(rows),2)
        one=next(r for r in rows if r['factors'][0]['factor_name']=='factor1')
        two=next(r for r in rows if r['factors'][0]['factor_name']=='factor2')
        self.assertEqual(one['review']['facts']['ending_equity'],110)
        self.assertIsNone(two['platform_run_id']);self.assertIsNone(two['feedback'])
        self.assertEqual(two['status'],'incomplete')
        self.assertTrue(two['warnings'])

    def test_R01_same_loop_multiple_workspaces_and_parse_failure(self):
        self.runner('Loop_0',1);self.runner('Loop_0',2,report=False)
        self.event('Loop_0','feedback',3,types.SimpleNamespace(decision=True))
        self.event('Loop_1','runner result',4,ValueError('broken record'))
        rows=self.export();self.assertEqual(len(rows),3)
        self.assertEqual(sum(r['platform_run_id'] is not None for r in rows),1)
        self.assertTrue(all(r['feedback'] is None for r in rows))

    def test_R02_redaction_before_publication_including_HTTP(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        self.runner('Loop_0',1);rows=self.export()
        s=WorkbenchService(LocalResultRepository(self.root/'db'))
        r=rows[0];rev=s.get_revision(r['platform_run_id'])
        http=TestClient(create_app(s)).get(f"/v1/runs/{r['platform_run_id']}/revisions/{rev['revision_id']}")
        self.assertNotIn('audit-placeholder-credential',json.dumps(r)+json.dumps(rev)+http.text)
        self.assertIn('[REDACTED]',http.text)

    def test_R03_synthetic_conflict_refused_and_unknown_declared(self):
        self.runner('Loop_0',1)
        with self.assertRaises(SourceConflict):self.export(False)
        self.assertEqual(LocalResultRepository(self.root/'db').list_runs()['items'],[])
        self.assertEqual(data_nature(False)['basis'],'importer_declared')
        with self.assertRaises(SourceConflict):data_nature(False,fixture=True)

    def test_R01_bad_sidecar_prevents_partial_publish(self):
        ws=self.runner('Loop_0',1);(ws/'effective.json').write_text('{bad')
        rows=self.export();self.assertIsNone(rows[0]['platform_run_id'])


if __name__=='__main__':unittest.main()
