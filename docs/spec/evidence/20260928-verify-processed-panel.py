"""Independent offline field oracle. No production materializer or price helper reuse.

Usage: python this_file.py --data-root ~/.qlib/qlib_data --snapshot-id free_cn_20260924_processed_v1
Reads original files and annual processed CSVs; prints a sanitized summary only.
"""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import struct

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-root',type=Path,required=True)
parser.add_argument('--snapshot-id',default='free_cn_20260924_processed_v1')
args=parser.parse_args()
root=args.data_root.expanduser()
source=root/'free_cn_20260924'
processed=root/'processed'/args.snapshot_id/'panels_v2_1'
manifest=json.loads((processed/'manifest.json').read_text())
positions={d:i for i,d in enumerate((source/'calendars/day.txt').read_text().split())}
counts=Counter();max_relative=0.0
for chunk in manifest['chunks']:
    raw=(processed/chunk['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=chunk['sha256'] or len(raw)!=chunk['size_bytes']:
        raise ValueError('output digest mismatch')
    current=None;arrays={};statuses={}
    for row in csv.DictReader(io.StringIO(raw.decode())):
        if row['symbol']!=current:
            current=row['symbol']
            arrays={}
            for field in ('close','factor','volume','amount'):
                data=(source/'features'/current.lower()/f'{field}.day.bin').read_bytes()
                floats=struct.unpack('<'+'f'*(len(data)//4),data)
                arrays[field]=(int(floats[0]),floats[1:])
            with (root/'free_cn_20260924_enrichment/turnover'/f'{current}.csv').open() as handle:
                statuses={r['date']:r for r in csv.DictReader(handle)}
        index=positions[row['date']]
        def value(field):
            offset,values=arrays[field]
            return values[index-offset] if offset<=index<offset+len(values) else float('nan')
        close,factor,volume,amount=(value(f) for f in ('close','factor','volume','amount'))
        status=statuses.get(row['date'],{})
        turn=float(status['turn']) if status.get('turn') else None
        shares=100*factor*volume
        float_shares=shares/(turn/100) if turn is not None and turn>0 else float('nan')
        expected={'adjusted_close':close,'raw_close':close/factor if factor>0 else float('nan'),
                  'raw_volume_shares':shares,'amount_cny':1000*amount,'turn_percent':turn,
                  'tradestatus':float(status['tradestatus']) if status else None,
                  'is_st':float(status['isST']) if status else None,
                  'float_shares_estimate':float_shares,
                  'float_cap_estimate':float_shares*close/factor if factor>0 else float('nan')}
        for key,expected_value in expected.items():
            actual=row[key]
            if expected_value is None or not math.isfinite(expected_value):
                if actual!='':raise ValueError(f'missing was imputed: {key}')
                counts['missing_cells_verified']+=1
            else:
                if not actual or not math.isclose(float(actual),expected_value,rel_tol=1e-12,abs_tol=1e-12):
                    raise ValueError(f'field mismatch: {row["date"]}/{current}/{key}')
                delta=abs(float(actual)-expected_value)/max(abs(expected_value),1e-300)
                max_relative=max(max_relative,delta)
                counts['numeric_cells_verified']+=1
        counts['rows_verified']+=1
    counts['chunks_verified']+=1
print(json.dumps({'snapshot_id':args.snapshot_id,'input_content_digest':manifest['input_content_digest'],
                  'oracle':'original archive field bytes and original BaoStock CSV; independent arithmetic',
                  'passed':True,'counts':dict(counts),'max_relative_error':max_relative,
                  'relative_tolerance':1e-12,'absolute_tolerance':1e-12,'paths_recorded':False},indent=2))
