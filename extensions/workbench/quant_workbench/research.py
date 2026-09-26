"""Engine neutral research snapshots and evidence-based review summaries."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .metrics import summarize, equity_drawdown


def review_result(package):
    entries = {x['metric_id']: x for x in package['series']}
    eq = summarize(entries.get('platform.equity'))
    cost = summarize(entries.get('native.qlib.total_cost'))
    evidence = package.get('evidence', {})
    quality = evidence.get('research_quality')
    gaps = []
    if package['run']['synthetic']: gaps.append('使用模拟数据，不能据此判断真实市场有效性')
    if not package['run']['dataset'].get('version'): gaps.append('数据内容版本未记录，无法进行严格排名')
    if not evidence.get('cn_scenario'): gaps.append('费用与执行情景证据不完整')
    if not quality: gaps.append('未记录研究质量检查')
    elif quality.get('status') != 'passed_checks': gaps.append('研究质量检查未通过')
    if not eq['point_count']: gaps.append('没有权益报告')
    if eq['missing_points']: gaps.append('权益报告存在缺测，完整区间回撤不可确定')
    context = evidence.get('comparison', {})
    initial = context.get('initial_equity')
    full = isinstance(initial, (int, float)) and not isinstance(initial, bool) and initial > 0 and context.get('cashflow_policy') == 'none'
    points = entries.get('platform.equity', {}).get('points', [])
    facts = {'ending_equity': eq['last'], 'ending_equity_reason': eq['last_reason'],
             'first_observed_equity': eq['first'],
             'observed_equity_change': eq['last']/eq['first']-1 if eq['first'] and eq['last'] is not None else None,
             'max_observed_drawdown': equity_drawdown(points),
             'max_full_drawdown': equity_drawdown(points, initial) if full else None,
             'total_return': eq['last']/initial-1 if full and eq['complete'] else None,
             'total_cost': cost['last'], 'total_cost_reason': cost['last_reason'],
             'last_valid_equity': eq['last_valid'], 'equity_coverage': eq}
    def scalar(suffix):
        matches=[x for x in package['series'] if x['axis']=='scalar' and x['metric_id'].endswith(suffix)]
        return matches[0]['points'][-1]['value'] if len(matches)==1 and matches[0]['points'] else None
    facts['ic']=scalar('.IC')
    facts['net_annual_excess']=scalar('.1day.excess_return_with_cost.annualized_return')
    findings=[]
    if facts['net_annual_excess'] is not None and facts['net_annual_excess'] < 0:
        findings.append('源报告成本后年化超额收益为负；应检查成本、换手与信号贡献，不能因IC为正就接受该候选')
    if quality and quality.get('constant_prediction_days', 0):
        findings.append('存在常数预测日，应先检查特征、训练数据与模型输出')
    actions = ['先核对数据版本、费用、日期，再比较候选研究', '用独立样本和真实数据做样本外验证']
    if quality and quality.get('status') != 'passed_checks': actions.insert(0, '先排查常数预测、有效IC覆盖和无交易问题')
    return {'origin': 'workbench_rule', 'facts': facts, 'gaps': gaps, 'next_steps': actions,
            'conclusion': '工作台规则摘要：现有证据不足以支持实盘决策', 'quality': quality,
            'findings': findings,
            'basis': '权益变化从报告首个观测点计算；初始资金缺失时不称为完整总收益。'}


class ResearchSnapshots:
    """Only bounded JSON produced by the offline export adapter is read here."""
    def __init__(self, root): self.root = Path(root)

    def detail(self, identity):
        if not re.fullmatch(r'[a-f0-9]{24}', identity): return None
        path = self.root / (identity + '.json')
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 4_000_000: return None
        try: data = json.loads(path.read_text())
        except (OSError, ValueError): return None
        if data.get('schema_version') != 1 or data.get('id') != identity: return None
        return data

    def listing(self, limit=20, offset=0, query=''):
        if not 1 <= limit <= 100 or offset < 0: raise ValueError('invalid pagination')
        items=[]
        for p in self.root.glob('*.json'):
            data=self.detail(p.stem)
            if not data or data.get("status") == "session_index": continue
            row={k:data.get(k) for k in ('id','title','session','updated_at','observed_at','status','factor_count','metrics','platform_run_id','warnings','synthetic')}
            row['facts']=data.get('review',{}).get('facts',{})
            if query.casefold() in json.dumps(row,ensure_ascii=False).casefold(): items.append(row)
        items.sort(key=lambda x:(x['updated_at'],x['id']),reverse=True)
        return {'items':items[offset:offset+limit],'total':len(items),'next_offset':offset+limit if offset+limit<len(items) else None}
