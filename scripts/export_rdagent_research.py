"""Export trusted local RD-Agent history to bounded neutral JSON and platform results.
Run with the RD-Agent Python environment, from its checkout. Never called by HTTP.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'extensions/workbench'))


def export(root, output, platform, synthetic, session_names=None):
    from rdagent.core.serialization import load
    from quant_workbench.storage import LocalResultRepository
    from quant_workbench.application import WorkbenchService
    from quant_workbench.research import review_result
    service = WorkbenchService(LocalResultRepository(platform))
    output.mkdir(parents=True, exist_ok=True)
    secrets=[]
    env=root/'.env'
    if env.is_file():
        for line in env.read_text().splitlines():
            k,sep,v=line.partition('=')
            if sep and any(x in k.upper() for x in ('KEY','TOKEN','SECRET','PASSWORD')):
                v=v.strip().strip('\"\'')
                if len(v)>5: secrets.append(v)
    def clean(value, size=12000):
        s=str(value)
        for secret in secrets:s=s.replace(secret,'[REDACTED]')
        s=re.sub(r'\x1b\[[0-9;]*m','',s)
        s=re.sub(r'sk-[A-Za-z0-9_-]{8,}', '[REDACTED]',s)
        s=re.sub(r'(?i)(bearer\s+)[\w.\-]+',r'\1[REDACTED]',s)
        s=re.sub(r'(?i)((?:api[_-]?key|password|token|secret)\s*[=:]\s*)[^\s,;]+',r'\1[REDACTED]',s)
        s=s.replace(str(root),'[RD-Agent]').replace(str(Path.home()),'[HOME]')
        return s[:size]+('\n[内容截断]' if len(s)>size else '')
    def fields(o, names):return {k:clean(getattr(o,k)) for k in names if getattr(o,k,None) is not None}
    def num(x):
        try: v=float(x);return v if math.isfinite(v) else None
        except (TypeError,ValueError):return None
    def safe(p):return p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root) and p.stat().st_size<20_000_000
    def instant(stem):return datetime.strptime(stem,'%Y-%m-%d_%H-%M-%S-%f').replace(tzinfo=timezone.utc).isoformat()
    count=0
    for session in sorted((root/'log').iterdir()):
        if not session.is_dir() or session.is_symlink():continue
        if session_names is not None and session.name not in session_names:continue
        try: started=instant(session.name)
        except ValueError:continue
        identity=hashlib.sha256(('rdagent:'+session.name).encode()).hexdigest()[:24]
        events=[];factors=[];metrics={};report=None;runner_report=None;effective=None;quality=None;warnings=[];feedback=None
        paths=sorted(session.rglob('*.pkl'),key=lambda p:p.stem)
        for p in paths:
            tag=p.parent.parent.name
            allowed={'time_info','hypothesis generation','runner result','feedback','evolving feedback','Qlib_execute_log','Quantitative Backtesting Chart'}
            if tag not in allowed or not safe(p):continue
            try:
                with p.open('rb') as f: obj=load(f)
                at=instant(p.stem)
                stage='/'.join(p.relative_to(session).parts[:-2])
                content=None
                if tag=='time_info':content={k:clean(v) for k,v in obj.items() if k in ('start_time','end_time')}
                elif tag=='hypothesis generation':content=fields(obj,('hypothesis','reason','concise_observation','concise_justification'))
                elif tag=='feedback':
                    content=fields(obj,('decision','reason','observations','hypothesis_evaluation','new_hypothesis','acceptable','exception'))
                    feedback=content
                elif tag=='evolving feedback':content={'feedback':clean(obj)}
                elif tag=='Qlib_execute_log':
                    content={'log':clean(obj,24000)}
                    for match in re.findall(r'CN_QUALITY (\{[^\n]+\})',str(obj)):
                        try:quality=json.loads(match)
                        except ValueError:pass
                elif tag=='Quantitative Backtesting Chart':
                    if hasattr(obj,'columns') and 'account' in obj:report=obj
                    content={'report':'回测权益、收益、成本与换手已记录','rows':len(obj)}
                elif tag=='runner result':
                    factors=[]
                    if obj.result is not None: metrics={clean(k,300):num(v) for k,v in obj.result.items()}
                    for i,t in enumerate(obj.sub_tasks):
                        factor=fields(t,('factor_name','description','factor_formulation','variables'))
                        ws=obj.sub_workspace_list[i] if i<len(obj.sub_workspace_list) else None
                        code=Path(ws.workspace_path)/'factor.py' if ws else None
                        if code and safe(code):factor['code']=clean(code.read_text(),18000)
                        factors.append(factor)
                    workspace=Path(obj.experiment_workspace.workspace_path)
                    report_file=workspace/'ret.parquet'
                    if safe(report_file):
                        import pandas as pd
                        runner_report=pd.read_parquet(report_file)
                    for name in ('effective.json','cn_quality.json'):
                        f=workspace/name
                        if safe(f):
                            data=json.loads(f.read_text())
                            if name=='effective.json':effective=data
                            else:quality=data
                    content={'result':'研究实验结果已记录','factor_count':len(factors),'metric_count':len(metrics)}
                if content is not None:events.append({'at':at,'stage':clean(stage,200),'kind':tag,'content':content})
            except Exception as exc:
                warnings.append('部分产物无法解析：'+tag+' ('+type(exc).__name__+')')
        if runner_report is not None: report=runner_report
        # Keep incomplete sessions too. Do not infer terminal state from old timestamps.
        updated=max([e['at'] for e in events],default=started)
        title=('因子研究 · '+(' / '.join(f.get('factor_name','因子') for f in factors[:3]))) if factors else ('基线回测' if report is not None else '研究准备 / 过程不完整')
        title+=' · '+started[:16].replace('T',' ')
        data={'schema_version':1,'id':identity,'session':session.name,'title':title,'updated_at':updated,
              'observed_at':datetime.now(timezone.utc).isoformat(),'status':'result_available' if report is not None else 'incomplete',
              'factor_count':len(factors),'metrics':metrics,'factors':factors,'feedback':feedback,
              'events':events[:300],'warnings':list(dict.fromkeys(warnings)), 'synthetic':synthetic,
              'quality':quality,'platform_run_id':None,'scenario_fingerprint':effective.get('fingerprint') if effective else None}
        if len(events)>300:data['warnings'].append('过程仅保留前300条事件')
        if not events:data['warnings'].append('现存产物只有配置/调试信息，无可展示的研究阶段；未推断成功或失败')
        if report is not None:
            dates=[x.date().isoformat() for x in report.index]
            calendar=effective['calendar']['id'] if effective else 'rdagent.calendar.unknown'
            entries=[]
            def series(mid,definition,unit,values):
                entries.append({'metric_id':mid,'definition_id':definition,'axis':'trading_date','calendar_id':calendar,
                 'unit':unit,'currency':'CNY' if unit=='CNY' else None,'availability':'available','points':[
                 {'x':d,'value':num(v),**({'reason':'missing_in_source'} if num(v) is None else {})} for d,v in zip(dates,values)]})
            equity=[num(v) for v in report['account']]
            if not equity or any(v is None or v<=0 for v in equity):
                data['warnings'].append('权益报告无效，未发布结果')
            else:
                high=equity[0];dd=[]
                for v in equity:high=max(high,v);dd.append(v/high-1)
                series('platform.equity','platform.equity.account.v1','CNY',equity)
                series('platform.drawdown','platform.drawdown.observed_equity.v1','ratio',dd)
                for field in ('return','bench','total_cost','cost','turnover','total_turnover'):
                    if field in report:series('native.qlib.'+field,'native.qlib.report.'+field+'.v1','CNY' if field.startswith('total_') else 'ratio',report[field])
                for k,v in metrics.items():
                    entries.append({'metric_id':'native.rdagent.'+k,'definition_id':'native.rdagent.'+k+'.unspecified',
                                    'axis':'scalar','unit':'unknown','availability':'available','points':[{'x':None,'value':v,**({'reason':'missing_in_source'} if v is None else {})}]})
                evidence={'research_id':identity,'provenance':'partial','research_quality':quality,
                          'source':'RD-Agent signed local history; result availability does not establish process exit status'}
                if effective:
                    evidence['cn_scenario']={'fingerprint':effective['fingerprint'],'mode':effective['research']['mode'],
                        'rules_as_of':effective['rules']['as_of'],'calendar_id':calendar,'commission_both':effective['account']['commission_both'],
                        'minimum_commission':effective['account']['minimum_commission'],'fees':effective['rules']['fees'],
                        'execution':effective['research']['execution'],'account_assumptions':effective['account']['assumptions']}
                package={'schema_version':1,'run':{'title':title,'kind':'research','status':'unknown','created_at':started,
                    'started_at':started,'ended_at':None,'engine':{'id':'rdagent-qlib','version':None},
                    'dataset':{'id':'cn-current-synthetic' if effective else 'rdagent-source-unknown','version':None},
                    'synthetic':synthetic,'stages':[]},'series':entries,'evidence':evidence}
                receipt=service.import_package('rdagent-local',session.name,'rdagent_history_v1',package)
                data['platform_run_id']=receipt['run_id'];data['revision_id']=receipt['revision_id'];data['review']=review_result(package)
        # Scrub every exported string including nested feedback and exceptions.
        def scrub(x):
            if isinstance(x,str):return clean(x,30000)
            if isinstance(x,dict):return {clean(k,300):scrub(v) for k,v in x.items()}
            if isinstance(x,list):return [scrub(v) for v in x]
            return x
        data=scrub(data)
        target=output/(identity+'.json');tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2));os.replace(tmp,target)
        count+=1
    return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trust-local-artifacts',action='store_true',required=True)
    kind=parser.add_mutually_exclusive_group(required=True)
    kind.add_argument('--synthetic',action='store_true');kind.add_argument('--real',action='store_true')
    parser.add_argument('--session', action='append', help='Export only these session folder names; repeat for multiple sessions')
    args=parser.parse_args()
    root=Path.cwd().resolve()
    if not (root/'rdagent').is_dir():parser.error('run from the RD-Agent checkout using its Python environment')
    count=export(root,PROJECT/'.data/workbench/research',PROJECT/'.data/workbench',args.synthetic,args.session)
    print(json.dumps({'exported_sessions':count}))

if __name__=='__main__':main()
