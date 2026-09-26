"""Evidence classification for presentation; never changes stored historical facts."""
LABELS={'native':'引擎原始记录','derived':'工作台计算','custom':'定制检查','opinion':'Agent 生成意见',
        'rule':'工作台规则提示','fixture':'手写演示样本','measured':'工作台实测','unknown':'来源未核实',
        'unsupported':'未接入','limited':'能力受限','missing':'未记录'}


def mark(kind,source,limitations=None):
    return {'kind':kind,'label':LABELS[kind],'source':source,'limitations':limitations or []}


def classify(package,adapter_version=''):
    evidence=package.get('evidence',{})
    fixture=evidence.get('fixture') is True
    native_source=bool((adapter_version in {'qlib_mlflow_v1','qlib_mlflow_v2'} and evidence.get('mlflow_run_id')) or
                       (adapter_version=='rdagent_history_v2' and evidence.get('research_id')))
    run_mark=mark('fixture' if fixture else 'native' if native_source else 'unknown',
                 'examples/generic-result.json；手工填写，非引擎执行' if fixture else
                 '本机历史产物；版本/完整性仍受下列限制' if native_source else '没有受支持的来源映射证据',
                 ['模拟行情不代表真实市场'] if package['run'].get('synthetic') else [])
    if adapter_version == 'rdagent_history_v1':
        run_mark = mark('limited', '旧版会话导出；实验归属未复核，请查看新版分轮研究', ['禁止排名；历史revision保留，不作为当前实验结果证据'])
    rows=[]
    for entry in package['series']:
        mid=entry['metric_id']
        if fixture:p=mark('fixture','手写JSON测试数据，包括状态、收益、损失及错误计数')
        elif not native_source:p=mark('unknown',entry.get('source_ref','没有核实来源'))
        elif mid=='platform.drawdown':
            p=mark('derived','权益 / 截至该日的观测权益峰值 - 1', ['从报告首点开始；未纳入首点之前的初始资金','不是Qlib原生超额收益最大回撤'])
        elif mid=='platform.equity':p=mark('native','Qlib report.account（仅字段映射）')
        elif mid.startswith('native.qlib.mlflow.'):
            p=mark('native','MLflow记录的 '+mid.removeprefix('native.qlib.mlflow.'),['单位/指标定义未完整标准化','若仅一个step，只能说明记录了一个点，不能称为完整训练曲线'])
        elif mid.startswith('native.rdagent.'):
            p=mark('native','RD-Agent实验结果 / qlib_res.csv：'+mid.removeprefix('native.rdagent.'),['这是实验指标，不是Agent文字结论','原生年化口径保留，不默认换算为252'])
        elif mid.startswith('native.qlib.'):
            p=mark('native','Qlib report.'+mid.removeprefix('native.qlib.'),['成交和费用由本次运行的模拟执行器产生，不是券商成交记录'])
        else:p=mark('unknown',entry.get('source_ref','未登记来源'))
        if not entry.get('points') or all(x.get('value') is None for x in entry['points']):
            p={**p,'availability':'missing','limitations':p['limitations']+['源数据缺失；不得填零']}
        entry['provenance']=p
        rows.append({'field':mid,**p})
    rows.extend([
        {'field':'区间权益变化',**mark('fixture' if fixture else 'derived','报告末点 / 首点 - 1',['不等于含初始资金的完整总收益'])},
        {'field':'质量检查 / 有效IC日 / 交易日数',**mark('custom' if evidence.get('research_quality') else 'missing','自建CNQualityRecord；不是Qlib或RD-Agent原生验收',['检查覆盖/常数预测/交易活动，不能证明因子有效'])},
        {'field':'费用与交易规则',**mark('custom' if evidence.get('cn_scenario') else 'missing','共享配置 + ConfiguredCNExchange 定制执行器',['最低佣金5元、滑点、参与率为研究假设；不代表券商实际收费'])},
        {'field':'结论 / 下一步',**mark('rule','工作台固定规则模板与阈值',['不是Qlib输出、不是额外LLM分析，也不是实盘建议'])},
        {'field':'运行状态',**mark('fixture' if fixture else 'native' if evidence.get('mlflow_run_id') else 'missing','MLflow记录状态' if evidence.get('mlflow_run_id') else '没有进程退出码；有报告不等于流程成功')},
    ])
    return {'run':run_mark,'fields':rows,'data_nature':'handwritten_fixture' if fixture else 'synthetic' if package['run'].get('synthetic') else 'declared_real',
            'verification':'来源分类；不是数据真实性或策略有效性认证'}


def capabilities_audit():
    return [
        {'name':'回测权益 / 成本 / 换手 / IC',**mark('limited','已导入的Qlib报告或RD-Agent实验结果',['目前全是模拟行情运行；无券商成交核验'])},
        {'name':'通用引擎结果示例',**mark('fixture','手写JSON测试夹具',['非第二个真实引擎；状态、loss、错误计数均为示例'])},
        {'name':'研究质量 / 交易约束',**mark('custom','自建质量记录与交易适配器',['不是上游原生完整能力；仅支持当前声明的日频模拟范围'])},
        {'name':'研究过程回放',**mark('limited','离线导出的签名历史日志',['非实时流；最多300条事件，日志/代码可能截断；不是完整LLM会话'])},
        {'name':'因子有效性 / Agent评审',**mark('opinion','Agent生成假设、解释和反馈',['代码/公式可查看，不代表已证明有效或无未来信息'])},
        {'name':'训练曲线',**mark('limited','已记录step或标量',['仅单点指标时，不支持完整学习曲线与收敛诊断'])},
        {'name':'比较 / 排名',**mark('limited','工作台可比性规则',['当前数据内容版本缺失，不能严格排名；并排查看不等于控制变量实验'])},
        {'name':'API错误率 / 响应耗时',**mark('measured','当前工作台HTTP进程',['非Qlib/RD-Agent错误率；300秒窗口、重启清零、最多10000条'])},
        {'name':'任务失败率 / 实时过程监控',**mark('unsupported','持久化Attempt与心跳尚未接入')},
        {'name':'界面启动 / 停止研究',**mark('unsupported','只有外部CLI执行入口')},
        {'name':'实时行情 / 实盘 / 数据供应商目录',**mark('unsupported','尚未接入')},
        {'name':'真实PIT / 公司行动 / 行业风控',**mark('unsupported','当前模拟适配器尚未实现')},
    ]
