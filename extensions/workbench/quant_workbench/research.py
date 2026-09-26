"""Engine neutral research snapshots and evidence-based review summaries."""
from __future__ import annotations
import json
import re
from pathlib import Path


def review_result(package):
    entries = {x['metric_id']: x for x in package['series']}
    def values(key):
        return [p['value'] for p in entries.get(key, {}).get('points', []) if p['value'] is not None]
    eq, dd, cost = values('platform.equity'), values('platform.drawdown'), values('native.qlib.total_cost')
    evidence = package.get('evidence', {})
    quality = evidence.get('research_quality')
    gaps = []
    if package['run']['synthetic']: gaps.append('使用模拟数据，不能据此判断真实市场有效性')
    if not package['run']['dataset'].get('version'): gaps.append('数据内容版本未记录，无法进行严格排名')
    if not evidence.get('cn_scenario'): gaps.append('费用与执行情景证据不完整')
    if not quality: gaps.append('未记录研究质量检查')
    elif quality.get('status') != 'passed_checks': gaps.append('研究质量检查未通过')
    if not eq: gaps.append('没有权益报告')
    facts = {'ending_equity': eq[-1] if eq else None,
             'first_observed_equity': eq[0] if eq else None,
             'observed_equity_change': eq[-1]/eq[0]-1 if eq and eq[0] else None,
             'max_observed_drawdown': min(dd) if dd else None,
             'total_cost': cost[-1] if cost else None}
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
            if not data: continue
            row={k:data.get(k) for k in ('id','title','session','updated_at','observed_at','status','factor_count','metrics','platform_run_id','warnings','synthetic')}
            row['facts']=data.get('review',{}).get('facts',{})
            if query.casefold() in json.dumps(row,ensure_ascii=False).casefold(): items.append(row)
        items.sort(key=lambda x:(x['updated_at'],x['id']),reverse=True)
        return {'items':items[offset:offset+limit],'total':len(items),'next_offset':offset+limit if offset+limit<len(items) else None}
