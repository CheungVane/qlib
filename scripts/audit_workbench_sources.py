"""Read-only comparison against trusted, signed local RD-Agent and Qlib reports.
Run from RD-Agent checkout with its Python; never called by HTTP.
"""
from pathlib import Path
import sys,json,math,sqlite3,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'extensions/workbench'))
from quant_workbench.storage import LocalResultRepository
from rdagent.core.serialization import load
import pandas as pd
from mlflow.tracking import MlflowClient
repo=LocalResultRepository(ROOT/'.data/workbench')
# MLflow initializes/migrates SQLite even for reads. Only ever give it a disposable copy.
audit_temp=tempfile.TemporaryDirectory(prefix='source-audit-',dir=ROOT/'.data')
copy=Path(audit_temp.name)/'tracking.db'
with sqlite3.connect('file:'+str(ROOT/'.data/qlib_mlruns_mlflow3_12.db')+'?mode=ro',uri=True) as source_db:
 with sqlite3.connect(copy) as copy_db:source_db.backup(copy_db)
client=MlflowClient(tracking_uri='sqlite:///'+str(copy))
output=[]
for run in repo.list_runs(100)['items']:
 package=repo.get_revision(run['run_id'])['result'];e=package.get('evidence',{})
 if e.get('fixture'):
  output.append({'run_id':run['run_id'],'kind':'handwritten_fixture','checked_values':0});continue
 report=None;metrics={};source=None
 if e.get('mlflow_run_id'):
  source='portfolio_analysis/report_normal_1day.pkl'
  report=pd.read_pickle(client.download_artifacts(e['mlflow_run_id'],source))
  metrics=client.get_run(e['mlflow_run_id']).data.metrics
 else:
  session=ROOT.parent/'RD-Agent/log'/run['external_id']
  for p in sorted(session.rglob('*.pkl'),key=lambda p:p.stem):
   tag=p.parent.parent.name
   if tag not in ('runner result','Quantitative Backtesting Chart'):continue
   with p.open('rb') as f:obj=load(f)
   if tag=='Quantitative Backtesting Chart':report=obj;source='signed log/Quantitative Backtesting Chart'
   else:
    report=pd.read_parquet(obj.experiment_workspace.workspace_path/'ret.parquet')
    metrics=obj.result.to_dict();source='runner result -> ret.parquet / qlib_res.csv'
 counts=0;errors=[]
 for s in package['series']:
  mid=s['metric_id'];expected=None
  if mid=='platform.equity':expected=report['account'].tolist()
  elif mid.startswith('native.qlib.mlflow.'):
   name=mid.removeprefix('native.qlib.mlflow.')
   # Only compare stored last-point scalar here; training history checked separately by importer tests.
   expected=[metrics.get(name)] if s['axis']=='scalar' else None
  elif mid.startswith('native.rdagent.'):expected=[metrics.get(mid.removeprefix('native.rdagent.'))]
  elif mid.startswith('native.qlib.'):
   field=mid.removeprefix('native.qlib.')
   if field in report:expected=report[field].tolist()
  if expected is None:continue
  actual=[x['value'] for x in s['points']]
  if len(actual)!=len(expected):errors.append(mid+':length');continue
  for a,b in zip(actual,expected):
   b=None if b is None or not math.isfinite(float(b)) else float(b)
   if not (a is None and b is None) and (a is None or b is None or not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)):errors.append(mid+':value');break
   counts+=1
 output.append({'run_id':run['run_id'],'revision_id':run['revision_id'],'source':source,'kind':'recorded_engine_output_on_synthetic_data','checked_values':counts,'mismatches':errors})
(ROOT/'.data/workbench-source-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
print(json.dumps(output,ensure_ascii=False))
