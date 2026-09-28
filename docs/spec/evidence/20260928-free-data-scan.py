"""Review observation tool, not an acceptance test. Source data remains read-only.
Run from any directory with the workbench Python environment; pass --output explicitly.
"""
import argparse
_parser=argparse.ArgumentParser(description=__doc__)
_parser.add_argument('--output', required=True)
_args=_parser.parse_args()
import csv,json,hashlib,math,sys,collections
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'extensions/workbench'))
import numpy as np
from quant_workbench import data_directory as dd, free_sources as fs, factors
root=Path.home()/'.qlib/qlib_data'
r=dd.FreeSnapshotReader(root,dd.load_snapshot(root/'_registry','free_cn_20260924'))
calendar=r.calendar(); rows=r.instruments('csi500'); end=date(2026,9,24)
last=set(r.universe_on(end,'csi500')); result={'review_baseline':'2d1e2985','snapshot_id':'free_cn_20260924'}
result['calendar']={'days':len(calendar),'first':str(calendar[0]),'last':str(calendar[-1]),'strictly_increasing':calendar==sorted(set(calendar))}
result['membership']=[]
for day in [date(2015,1,5),date(2025,1,2),date(2025,12,31),end]:
 active=set(r.universe_on(day,'csi500'))
 result['membership'].append({'date':str(day),'historical_members':len(active),'end_members':len(last),'missed_historical':len(active-last),'not_yet_members':len(last-active),'missed_sample':sorted(active-last)[:5]})
window=[d for d in calendar if date(2025,1,2)<=d<=end]
mapping=fs.universe_by_date(rows,window)
result['research_window']={'dates':len(window),'distinct_historical_members':len(set().union(*(set(x) for x in mapping.values()))),'selected_end_members':len(last)}
result['existing_materializations']=[]
for path in sorted(root.glob('panel-csi500-*.csv')):
 entries=list(csv.DictReader(path.open()));keys=[(x['date'],x['symbol']) for x in entries]
 invalid=sum(x['symbol'] not in set(mapping.get(x['date'],[])) for x in entries)
 result['existing_materializations'].append({'file':path.name,'rows':len(entries),'unique_keys':len(set(keys)),'duplicates':len(keys)-len(set(keys)),'outside_historical_membership':invalid,'distinct_symbols':len({x['symbol'] for x in entries})})
cache=root/'free_cn_20260924_enrichment/turnover';counts=collections.Counter(); bad=[]
for path in sorted(cache.glob('*.csv')):
 counts['files']+=1;prev=None;seen=set()
 for row in csv.DictReader(path.open()):
  counts['rows']+=1;day=row['date']
  if day in seen:counts['duplicate_dates']+=1
  if prev and day<=prev:counts['non_increasing']+=1
  seen.add(day);prev=day
  if row['tradestatus'] not in ('0','1') or row['isST'] not in ('0','1'):counts['invalid_flags']+=1
  try:
   turn=float(row['turn']) if row['turn'] else None
   if turn is None:counts['missing_turn']+=1
   elif not math.isfinite(turn) or turn<0:counts['invalid_turn']+=1
   elif turn==0:counts['zero_turn']+=1
  except ValueError:counts['invalid_turn']+=1
result['cache_structure']=dict(counts)
# Per-field offsets/lengths across all historical csi500 names; no data writes.
headers=[];missing=[]
for symbol in sorted({x['symbol'] for x in rows}):
 fields={}
 for field in fs.ARCHIVE_FIELDS:
  p=r.path('bar')/symbol.lower()/f'{field}.day.bin'
  try:
   h=fs.read_bin_head_tail(p);fields[field]=(h['start_index'],h['points'])
  except (OSError,ValueError):missing.append([symbol,field])
 if len(set(fields.values()))>1:headers.append({'symbol':symbol,'headers':fields})
result['binary_headers']={'symbols':len({x['symbol'] for x in rows}),'mismatched':len(headers),'mismatch_sample':headers[:3],'missing_fields':len(missing),'missing_sample':missing[:5]}
# Verify archive bytes vs manifest; do not contact data providers.
manifest=json.loads((root/'_downloads/2026-09-27/qlib_bin.manifest.json').read_text())
h=hashlib.sha256()
with (root/'_downloads/2026-09-27/qlib_bin.tar.gz').open('rb') as f:
 for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
result['archive_sha256_matches']=h.hexdigest()==manifest['archive_sha256'].removeprefix('sha256:')
# Dividend/adjustment changes in a single recorded real symbol.
symbol='SH600000';folder=r.path('bar')/symbol.lower();close=np.fromfile(folder/'close.day.bin',dtype='<f4');factor=np.fromfile(folder/'factor.day.bin',dtype='<f4');start=int(close[0]);c=close[1:].astype(float);f=factor[1:].astype(float)
samples=[]
for i in range(1,min(len(c),len(f))):
 day=calendar[start+i]
 if day<date(2025,1,1) or day>end or not all(math.isfinite(x) and x>0 for x in [c[i],c[i-1],f[i],f[i-1]]):continue
 if abs(f[i]/f[i-1]-1)>0.001:
  dates=[str(calendar[start+i-1]),str(day)]
  loaded=factors.load_close_series(r.path('bar').parent,dates,[symbol])['values'][:,0]
  samples.append({'symbol':symbol,'dates':dates,'factor_ratio':f[i]/f[i-1],'adjusted_close_return':c[i]/c[i-1]-1,'generic_factor_loader_return':float(loaded[1]/loaded[0]-1)})
result['double_adjustment_real_examples']=samples
result['unit_sample']={'symbol':symbol,'date':str(calendar[start+len(c)-1]),'raw_close':fs.raw_price(c[-1],f[-1]),'raw_volume_lots':fs.raw_volume_lots(fs.read_bin_head_tail(folder/'volume.day.bin')['last'],f[-1]),'amount_CNY':fs.read_bin_head_tail(folder/'amount.day.bin')['last']*1000}
Path(_args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
