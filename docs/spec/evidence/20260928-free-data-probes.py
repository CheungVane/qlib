"""Review observation tool, not an acceptance test. Source data remains read-only.
Run from any directory with the workbench Python environment; pass --output explicitly.
"""
import argparse
_parser=argparse.ArgumentParser(description=__doc__)
_parser.add_argument('--output', required=True)
_args=_parser.parse_args()
import json,sys,tempfile,struct,importlib.util,subprocess,hashlib
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'extensions/workbench'))
from quant_workbench import data_directory as dd, factor_pipeline as fp, free_sources as fs
root=Path(__file__).resolve().parents[3];out={}
spec=importlib.util.spec_from_file_location('fetch_turn',root/'scripts/fetch_csi500_turnover.py');fetch=importlib.util.module_from_spec(spec);spec.loader.exec_module(fetch)
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'bars/aa').mkdir(parents=True)
 (p/'calendar.txt').write_text('2025-01-02\n2025-01-03\n2025-01-06\n')
 (p/'all.txt').write_text('AA\t2025-01-02\t2025-01-02\nAA\t2025-01-06\t2025-01-06\n')
 (p/'csi500.txt').write_text((p/'all.txt').read_text())
 for field in ['open','high','low','close','volume']:
  # Equal lengths, different dates: validation ignores the first float header.
  (p/'bars/aa'/f'{field}.day.bin').write_bytes(struct.pack('<4f',1 if field=='volume' else 0,10,10,10))
 components=[{'kind':k,'uri':u,'content_digest':'unknown-but-accepted','source_class':'fixture','coverage_start':'2025-01-02','coverage_end':'2025-01-06'} for k,u in [('calendar','calendar.txt'),('universe','all.txt'),('bar','bars')]]
 for component in components:
  path=p/component['uri']
  if path.is_file():component['content_digest']='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
 rec=dd.build_snapshot_record(snapshot_id='fixture',source={'kind':'fixture'},components=components,status='draft')
 reader=dd.FreeSnapshotReader(p,rec)
 out['shifted_bin_header_gate']=dd.validate_bars(reader,['AA'])
 mat=dd.materialize_panel(reader,output=p/'panel.csv',universe='csi500',fields=['close','volume'],start=date(2025,1,2),end=date(2025,1,6))
 out['materialization']={'rows':mat['rows'],'payload':(p/'panel.csv').read_text(),'draft_accepted':True}
 registry=p/'registry';dd.publish_snapshot(registry,rec)
 (p/'calendar.txt').write_text('2025-01-02\n2025-01-03\n2025-01-07\n')
 changed=dd.FreeSnapshotReader(p,dd.load_snapshot(registry,'fixture'))
 out['content_drift_accepted']={'record_digest_unchanged':changed.record['content_digest']==rec['content_digest'],'validate_ok':changed.validate()['ok'],'last_date':str(changed.calendar()[-1])}
 (p/'AA.csv').write_text('date,turn,tradestatus,isST\n')
 class NoQuery:
  def query_history_k_data_plus(self,*a,**kw):raise AssertionError('must not query in this probe')
 out['header_only_cache']=fetch._write_symbol(NoQuery(),'AA','sh.600000','2025-01-01','2026-12-31',p)[1]
 (p/'duplicate.csv').write_text('date,turn,tradestatus,isST\n2025-01-02,1,1,0\n2025-01-02,999,1,0\n')
 out['duplicate_cache_last_wins']=fs.load_turnover_csv(p/'duplicate.csv')
 class PartialResult:
  error_code='0';error_msg=''
  def __init__(self):self.n=0
  def next(self):
   self.n+=1
   if self.n==1:return True
   self.error_code='10001011';self.error_msg='黑名单';return False
  def get_row_data(self):return ['2025-01-02','1','1','0']
 class PartialAPI:
  def query_history_k_data_plus(self,*a,**kw):return PartialResult()
 out['midstream_error_cache']={'status':fetch._write_symbol(PartialAPI(),'BB','sh.600001','2025-01-01','2026-12-31',p)[1],'published':(p/'BB.csv').exists()}
 # Publish script exits success although bar gate fails, registry is already published.
 rec['status']='published';(p/'record.json').write_text(json.dumps(rec))
 (p/'bars/aa/close.day.bin').write_bytes(struct.pack('<4f',0,-1,10,10))
 proc=subprocess.run([sys.executable,str(root/'scripts/register_free_snapshot.py'),'--data-root',str(p),'--registry',str(p/'bad_registry'),'--record',str(p/'record.json'),'--universe','csi500','--panel-start','2025-01-02','--panel-end','2025-01-06','--output',str(p/'registration.json')],capture_output=True,text=True)
 evidence=json.loads((p/'registration.json').read_text())
 out['failed_gate_published']={'exit_code':proc.returncode,'bar_gate_ok':evidence['bar_quality_gate']['ok'],'status':dd.load_snapshot(p/'bad_registry','fixture')['status']}
# Future prices alter training labels although train feature dates do not change.
prices=[100.0]*421;future=prices.copy();future[120]=120
windows=fp.walk_forward_windows(421,folds=4,min_train=120)
for h in [5,10]:
 a=fp.forward_return(prices,h);b=fp.forward_return(future,h);train,test=windows[0]
 out[f'train_label_leak_h{h}']={'train_stop_exclusive':train.stop,'test_start':test.start,'changed_train_rows':[i for i in range(train.stop) if a[i]!=b[i]],'labels_needing_test_prices':sum(i+h>=test.start for i in range(train.stop))}
out['interior_suspension_still_allowed']=fp.label_tradability([True,False,True],2)[0]
Path(_args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
