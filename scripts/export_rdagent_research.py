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
    from quant_workbench.cn_market import rdagent_snapshot_path, snapshot_content_digest
    from quant_workbench.source_safety import Sanitizer, data_nature, verify_effective, comparison_context
    root = Path(root).resolve()
    service = WorkbenchService(LocalResultRepository(platform))
    output.mkdir(parents=True, exist_ok=True)
    sanitizer = Sanitizer(root)
    clean, scrub = sanitizer.text, sanitizer.scrub
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
        paths = sorted(session.rglob('*.pkl'), key=lambda p: (p.stem, str(p)))
        loops = {}
        for path in paths:
            if path.parent.parent.name not in {'time_info','hypothesis generation','runner result','feedback','evolving feedback','Qlib_execute_log','Quantitative Backtesting Chart'} or not safe(path):
                continue
            first = path.relative_to(session).parts[0]
            loop = first if re.fullmatch(r'(Loop_)?\d+', first) else 'unscoped'
            loops.setdefault(loop, []).append(path)
        if not loops: loops["unscoped"] = []
        records = []
        for loop, loop_paths in loops.items():
            runners = [p for p in loop_paths if p.parent.parent.name == 'runner result']
            charts = [p for p in loop_paths if p.parent.parent.name == 'Quantitative Backtesting Chart']
            common = [p for p in loop_paths if p not in runners and p not in charts]
            anchors = runners or charts
            if not anchors:
                records.append((loop + ':incomplete', common, True))
            for anchor in anchors:
                # Workspace results are authoritative; never borrow a chart or
                # another runner's sidecars when this experiment is incomplete.
                records.append((loop + ':' + str(anchor.relative_to(session)),
                                sorted(common + [anchor], key=lambda p: p.stem), len(anchors) == 1))
        children = []
        for record_key, paths, feedback_attributable in records:
            identity=hashlib.sha256(('rdagent:'+session.name+':'+record_key).encode()).hexdigest()[:24]
            events=[];factors=[];metrics={};report=None;runner_report=None;effective=None;quality=None;warnings=[];feedback=None
            runner_workspace=None
            source_refs = {}
            if not feedback_attributable:
                warnings.append('同一Loop包含多个实验；公共过程按Loop展示，未将反馈归属于当前实验')
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
                        if feedback_attributable: feedback=content
                    elif tag=='evolving feedback':content={'feedback':clean(obj)}
                    elif tag=='Qlib_execute_log':
                        content={'log':clean(obj,24000)}
                    elif tag=='Quantitative Backtesting Chart':
                        if hasattr(obj,'columns') and 'account' in obj:
                            report=obj
                            source_refs['chart'] = clean(str(p.relative_to(session)))
                            source_refs['chart_sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
                        content={'report':'回测权益、收益、成本与换手已记录','rows':len(obj)}
                    elif tag=='runner result':
                        factors=[]
                        source_refs["runner"] = clean(str(p.relative_to(session)))
                        if obj.result is not None: metrics={clean(k,300):num(v) for k,v in obj.result.items()}
                        for i,t in enumerate(obj.sub_tasks):
                            factor=fields(t,('factor_name','description','factor_formulation','variables'))
                            ws=obj.sub_workspace_list[i] if i<len(obj.sub_workspace_list) else None
                            code=Path(ws.workspace_path)/'factor.py' if ws else None
                            if code and safe(code):factor['code']=clean(code.read_text(),18000)
                            factors.append(factor)
                        workspace=Path(obj.experiment_workspace.workspace_path)
                        runner_workspace=workspace
                        report_file=workspace/'ret.parquet'
                        if safe(report_file):
                            import pandas as pd
                            runner_report=pd.read_parquet(report_file)
                            source_refs["report_sha256"] = hashlib.sha256(report_file.read_bytes()).hexdigest()
                        for name in ('effective.json','cn_quality.json'):
                            f=workspace/name
                            if safe(f):
                                data=json.loads(f.read_text())
                                if name=='effective.json':effective=data
                                else:quality=data
                        content={'result':'研究实验结果已记录','factor_count':len(factors),'metric_count':len(metrics)}
                    if content is not None:events.append({'at':at,'stage':clean(stage,200),'kind':tag,'content':content,
                                                      'source_ref':clean(str(p.relative_to(session)))})
                except Exception as exc:
                    if tag == 'runner result':
                        runner_report = None; report = None; effective = None; quality = None; metrics = {}
                    warnings.append('部分产物无法解析：'+tag+' ('+type(exc).__name__+')')
            if runner_report is not None: report=runner_report
            if effective:
                verify_effective(effective, quality)
            # Dataset content version: the container snapshot is the same logical data as the
            # local one, so the same content digest makes cross-engine comparison possible.
            dataset_version = None
            if effective:
                snapshot = rdagent_snapshot_path(effective['fingerprint'])
                if snapshot.is_dir():
                    try:
                        dataset_version = snapshot_content_digest(snapshot)['digest']
                    except OSError:
                        dataset_version = None
            nature = data_nature(synthetic, effective)
            if report is None: warnings.append('本实验未恢复权益报告；未借用其他实验结果')
            # Keep incomplete sessions too. Do not infer terminal state from old timestamps.
            updated=max([e['at'] for e in events],default=started)
            title=('因子研究 · '+(' / '.join(f.get('factor_name','因子') for f in factors[:3]))) if factors else ('基线回测' if report is not None else '研究准备 / 过程不完整')
            title+=' · '+started[:16].replace('T',' ')+' · '+record_key.split(':')[0]
            data={'schema_version':1,'export_version':2,'id':identity,'session':session.name,'experiment_key':clean(record_key),'title':title,'updated_at':updated,
                  'observed_at':datetime.now(timezone.utc).isoformat(),'status':'result_available' if report is not None else 'incomplete',
                  'factor_count':len(factors),'metrics':metrics,'factors':factors,'feedback':feedback,
                  'events':events[:300],'data_nature':nature,'warnings':list(dict.fromkeys(warnings)), 'synthetic':synthetic,
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
                    data['status']='incomplete'
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
                              'data_nature':nature,'experiment_key':clean(record_key),'source_refs':source_refs,
                              'source':'RD-Agent signed local history; result availability does not establish process exit status'}
                    if effective:
                        evidence['cn_scenario']={'fingerprint':effective['fingerprint'],'mode':effective['research']['mode'],
                            'rules_as_of':effective['rules']['as_of'],'calendar_id':calendar,'commission_both':effective['account']['commission_both'],
                            'minimum_commission':effective['account']['minimum_commission'],'fees':effective['rules']['fees'],
                            'execution':effective['research']['execution'],'account_assumptions':effective['account']['assumptions']}
                    package={'schema_version':1,'run':{'title':title,'kind':'research','status':'unknown','created_at':started,
                        'started_at':started,'ended_at':None,'engine':{'id':'rdagent-qlib','version':None},
                        'dataset':{'id':'cn-current-synthetic' if effective else 'rdagent-source-unknown','version':dataset_version},
                        'synthetic':synthetic,'stages':[]},'series':entries,'evidence':evidence}
                    if effective:
                        evidence['comparison'] = comparison_context(effective)
                    package = scrub(package)
                    receipt=service.import_package('rdagent-local',session.name+':'+record_key,'rdagent_history_v2',package)
                    data['platform_run_id']=receipt['run_id'];data['revision_id']=receipt['revision_id'];data['review']=review_result(package)
                    if runner_workspace is not None and effective and dataset_version:
                        panels = publish_factor_panels(
                            service, runner_workspace, session=session.name, record_key=record_key,
                            dataset={'id': 'cn-current-synthetic', 'version': dataset_version,
                                     'snapshot_label': effective['fingerprint'][:12]},
                            calendar_id=calendar, factors=factors, warnings=warnings)
                        if panels:
                            data['factor_panels'] = panels
            data=scrub(data)
            while len(json.dumps(data,ensure_ascii=False).encode()) > 3_900_000 and data['events']:
                data['events'].pop()
                if '快照大小受限，过程已截断' not in data['warnings']: data['warnings'].append('快照大小受限，过程已截断')
            if len(json.dumps(data,ensure_ascii=False,indent=2).encode()) > 4_000_000:
                raise ValueError('Research snapshot exceeds bounded size')
            target=output/(identity+'.json');tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2));os.replace(tmp,target)
            children.append({'id':identity,'title':data['title'],'status':data['status']})
        # Preserve the old session URL as navigation, without reusing its mixed
        # result package. Historical platform revisions remain immutable.
        identity=hashlib.sha256(('rdagent:'+session.name).encode()).hexdigest()[:24]
        index=scrub({'schema_version':1,'export_version':2,'id':identity,'session':session.name,
                     'title':'研究会话 · '+started,'status':'session_index','iterations':children,
                     'updated_at':started,'synthetic':synthetic,'platform_run_id':None})
        target=output/(identity+'.json');tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(index,ensure_ascii=False,allow_nan=False,indent=2));os.replace(tmp,target)
        count+=1
    return count


def publish_factor_panels(service, workspace, *, session, record_key, dataset, calendar_id, factors, warnings):
    """Publish each factor column of the RD-Agent factor panel as an immutable platform panel."""
    import pandas as pd
    path = Path(workspace) / 'combined_factors_df.parquet'
    if not path.is_file():
        warnings.append('未找到因子面板 combined_factors_df.parquet；因子层分析不可用')
        return []
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        warnings.append('因子面板无法读取：'+type(exc).__name__)
        return []
    if not isinstance(frame.index, pd.MultiIndex) or frame.index.nlevels < 2:
        warnings.append('因子面板索引不是 (datetime, instrument)；未发布')
        return []
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = [str(column[-1]) for column in frame.columns]
    definitions = {item.get('factor_name'): item for item in factors or []}
    dates = sorted({str(value.date()) for value in frame.index.get_level_values(0)})
    instruments = sorted({str(value) for value in frame.index.get_level_values(1)})
    rows = {day: position for position, day in enumerate(dates)}
    columns = {code: position for position, code in enumerate(instruments)}
    published = []
    for name in frame.columns:
        values = [None] * (len(dates) * len(instruments))
        for (stamp, code), value in frame[name].items():
            if value is None or not math.isfinite(float(value)):
                continue
            values[rows[str(stamp.date())] * len(instruments) + columns[str(code)]] = float(value)
        definition = definitions.get(str(name)) or {}
        payload = {'schema_version': 1, 'name': str(name), 'calendar_id': calendar_id,
                   'dates': dates, 'instruments': instruments, 'values': values,
                   'source_ref': 'combined_factors_df.parquet'}
        identity = {
            'source_instance_id': 'rdagent-local',
            'external_id': f'{session}:{record_key}:{name}',
            'name': str(name),
            'definition': {'formulation': definition.get('formulation'),
                           'description': definition.get('description'),
                           'variables': definition.get('variables')},
            'dataset': dataset,
            'calendar_id': calendar_id,
            'provenance': {'source': 'rdagent combined_factors_df.parquet',
                           'session': session, 'experiment_key': record_key,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
        }
        try:
            receipt = service.import_factor_panel(identity, payload)
        except Exception as exc:
            warnings.append(f'因子 {name} 面板未发布：{type(exc).__name__}')
            continue
        published.append({'name': str(name), 'factor_id': receipt['factor_id'],
                          'panel_id': receipt['panel_id'], 'created': receipt['created']})
    return published


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
