import copy, json, sys, tempfile, importlib.util, types
from pathlib import Path
from unittest.mock import patch
ROOT=Path.cwd()
sys.path.insert(0,str(ROOT/'extensions/workbench'))
from quant_workbench.model import validate_package
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository
from quant_workbench.research import review_result
from quant_workbench.cn_market import load_profile, validate
base=json.loads((ROOT/'extensions/workbench/examples/generic-result.json').read_text())
out={}
p=copy.deepcopy(base);p['series']=p['series'][:1];p['series'][0].update(availability='unsupported',points=[])
try:validate_package(p);out['empty_series']='accepted'
except Exception as e:out['empty_series']=type(e).__name__
p=copy.deepcopy(base);p['series']=p['series'][:1];p['series'][0].update(axis='time',points=[{'x':'2026-01-01T01:00:00+01:00','value':1},{'x':'2026-01-01T00:30:00+00:00','value':2}])
try:validate_package(p);out['chronological_offsets']='accepted'
except Exception as e:out['chronological_offsets']=str(e)
p=copy.deepcopy(base);p['series'][0]['points'][-1]={'x':p['series'][0]['points'][-1]['x'],'value':None,'reason':'missing_in_source'}
out['missing_last_equity_reported_as_ending']=review_result(p)['facts']['ending_equity']
with tempfile.TemporaryDirectory() as tmp:
 s=WorkbenchService(LocalResultRepository(tmp));p=copy.deepcopy(base);p['evidence']={'cn_scenario':{'fingerprint':'same-scenario'}};p['run']['dataset']={'id':'A','version':'v1'}
 p['series']=p['series'][:1];p['series'][0].pop('currency',None)
 a=s.import_package('a','a','generic',p)['run_id'];p['run']['dataset']['id']='B';p['series'][0]['points'][1]['value']=None;p['series'][0]['points'][1]['reason']='missing_in_source'
 b=s.import_package('b','b','generic',p)['run_id'];out['different_datasets_missing_currency_and_point']=s.compare([a,b],'platform.equity')
bundle=load_profile(ROOT/'configs/cn/profile.json');bundle['rules']['fees']['stamp_sel']='0.99'
try:validate(bundle);out['unknown_nested_fee']='accepted'
except Exception as e:out['unknown_nested_fee']=str(e)
# Test the offline exporter against isolated fabricated records; no real logs or RD runtime.
import pandas as pd
spec=importlib.util.spec_from_file_location('qwb_export',ROOT/'scripts/export_rdagent_research.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp).resolve();session=root/'log/2026-01-01_00-00-00-000000';objects={}
 effective=load_profile(ROOT/'configs/cn/profile.json')
 effective['account']['assumptions'].append('audit-placeholder-secret')
 (root/'.env').write_text('API_KEY=audit-placeholder-secret\n')
 for i in (0,1):
  ws=root/f'workspace{i}';ws.mkdir()
  if i==0:
   pd.DataFrame({'account':[100,110]},index=pd.to_datetime(['2021-01-01','2021-01-02'])).to_parquet(ws/'ret.parquet')
   (ws/'effective.json').write_text(json.dumps(effective))
  p=session/f'{i}/runner result/pid/2026-01-01_00-00-0{i}-000000.pkl';p.parent.mkdir(parents=True);p.write_bytes(b'fabricated')
  objects[str(p)]=types.SimpleNamespace(result=pd.Series({'IC':.1+i/10}),sub_tasks=[types.SimpleNamespace(factor_name=f'factor{i}')],sub_workspace_list=[],experiment_workspace=types.SimpleNamespace(workspace_path=str(ws)))
 fake=types.ModuleType('rdagent.core.serialization');fake.load=lambda f:objects[f.name]
 with patch.dict(sys.modules,{'rdagent':types.ModuleType('rdagent'),'rdagent.core':types.ModuleType('rdagent.core'),'rdagent.core.serialization':fake}):m.export(root,root/'out',root/'db',False)
 snapshot=json.loads(next((root/'out').glob('*.json')).read_text());service=WorkbenchService(LocalResultRepository(root/'db'));package=service.get_revision(snapshot['platform_run_id'])['result']
 out['multi_iteration_export']={'factor':snapshot['factors'][0]['factor_name'],'ic':snapshot['metrics']['IC'],'equity':snapshot['review']['facts']['ending_equity'],'warnings':snapshot['warnings']}
 out['synthetic_source_exported_as_real']={'source_synthetic':effective['research']['synthetic'],'exported_synthetic':package['run']['synthetic']}
 out['scrub_timing']={'snapshot_contains_placeholder': 'audit-placeholder-secret' in json.dumps(snapshot),'published_package_contains_placeholder':'audit-placeholder-secret' in json.dumps(package)}
print(json.dumps(out,ensure_ascii=False,indent=2))
