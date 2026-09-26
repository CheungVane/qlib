"""Create a separate, deterministic fixture using reviewed exchange sessions."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from prepare_cn_scenario import PROJECT, dataset_path, instruments, load_profile, profile_path
from quant_workbench.cn_market import sessions, price_limits
sys.path.insert(0, str(PROJECT / 'examples/benchmarks/LightGBM'))
from make_cn_demo_data import write_field


def main():
    bundle = load_profile(profile_path())
    r = bundle['research']; target = dataset_path(bundle)
    manifest = target/'scenario.json'
    if target.exists():
        if manifest.exists() and json.loads(manifest.read_text()).get('fingerprint') == bundle['fingerprint']:
            print(target); return
        raise ValueError('Dataset path already exists with another configuration; choose a new data_path')
    days = pd.to_datetime(sessions(bundle['calendar'], *r['date_range']))
    stocks = instruments(bundle)
    rng = np.random.default_rng(r['fixture']['seed'])
    for folder in ('calendars','instruments'): (target/folder).mkdir(parents=True,exist_ok=True)
    calendar = '\n'.join(days.strftime('%Y-%m-%d'))+'\n'
    for name in ('day.txt','day_future.txt'): (target/'calendars'/name).write_text(calendar)
    first,last=days[0].date(),days[-1].date()
    def write_members(name,codes):
        (target/'instruments'/name).write_text(''.join(f'{c}\t{first}\t{last}\n' for c in codes))
    write_members(r['market']+'.txt', stocks)
    write_members('all.txt', [*stocks,r['benchmark']])
    for i,code in enumerate([*stocks,r['benchmark']]):
        benchmark=code==r['benchmark']; board=bundle['rules']['boards'][r['fixture']['board']]
        returns=rng.normal(.0002,.009 if benchmark else .018,len(days))
        close=np.empty(len(days)); lower=np.empty(len(days)); upper=np.empty(len(days)); prev=1000 if benchmark else 15+i
        for j,value in enumerate(returns):
            lo,hi=price_limits(prev,board,bundle['rules']['tick_size'])
            lower[j],upper[j]=float(lo),float(hi)
            close[j]=np.clip(round(prev*np.exp(value),2),lower[j],upper[j]);prev=close[j]
        open_=np.clip(np.round(close*np.exp(rng.normal(0,.003,len(days))),2),lower,upper)
        high=np.clip(np.round(np.maximum(open_,close)*(1+rng.uniform(.001,.01,len(days))),2),lower,upper)
        low=np.clip(np.round(np.minimum(open_,close)*(1-rng.uniform(.001,.01,len(days))),2),lower,upper)
        volume=rng.integers(100_000,1_000_000,len(days)).astype(float)
        fields=dict(open=open_,close=close,high=high,low=low,volume=volume,vwap=(open_+close+high+low)/4,
            factor=np.ones(len(days)),change=np.r_[0,close[1:]/close[:-1]-1],
            buy_blocked=(close>=upper).astype(float),sell_blocked=(close<=lower).astype(float),limit_up=upper,limit_down=lower)
        for name,values in fields.items(): write_field(target/'features'/code.lower(),name,values)
    manifest.write_text(json.dumps({'fingerprint':bundle['fingerprint'],'synthetic':True,'calendar':bundle['calendar']['id'],
        'mode':r['mode'],'rules_as_of':bundle['rules']['as_of'],'instruments':stocks,'vwap':'OHLC approximation; not trade-derived'},indent=2)+'\n')
    print(target)

if __name__=='__main__': main()
