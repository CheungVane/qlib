# 量化能力差距扫描（外部参考，2026-09-26）

状态：**研究输入，不是合同**。本文不新增需求，也不声称任何能力已实现；它把外部成熟做法与本项目现状并排，供用户决定后续立项。行情/数据接入按用户要求排除在本次扫描之外。

方法：GitHub `repos` 接口检索指定项目（star 与最近推送时间为 2026-09-26 的检索快照），逐一对照 [因子层规范](FACTOR_ANALYSIS.md)、[核心规范](WORKBENCH_SPEC.md) 与 [实施状态](IMPLEMENTATION.md)。只引用可核对的项目与目录结构，不复制代码。

## 1. 参考项目（检索快照）

| 项目 | star | 最近推送 | 提供的做法 |
| --- | --- | --- | --- |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 48868 | 2026-09-22 | AI 量化平台、PIT 数据、点内交叉验证接口 |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14758 | 2026-09-23 | 因子/模型自动研究流程（本项目已接入） |
| [stefan-jansen/alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded) | 657 | 2024 | 因子报告三件套：IC 分析、换手分析、分组分析 |
| [quantopian/pyfolio](https://github.com/quantopian/pyfolio) | 6425 | — | 组合与风险分析、回撤期、暴露 |
| [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | 7658 | 2026-09-26 | 绩效指标族与 tear sheet（Sharpe/Sortino/Calmar/VaR/CVaR/波动） |
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | 4932 | 2023-10 | 目录含 `cross_validation`（purged/embargo）、`sample_weights`、`labeling`、`backtest_statistics`、`feature_importance`、`bet_sizing`、`structural_breaks` |
| [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | 4516 | 2026-09-24 | 约束下的组合优化与风险预算 |
| [optuna/optuna](https://github.com/optuna/optuna) | 14848 | 2026-09-25 | 超参搜索与试验管理 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9193 | 2026-09-26 | 高速向量化回测与参数扫描 |
| [unionai-oss/pandera](https://github.com/unionai-oss/pandera) | 4467 | 2026-09-26 | 数据/特征校验规则 |
| [feast-dev/feast](https://github.com/feast-dev/feast) | 7310 | 2026-09-26 | 特征注册与在线/离线一致性 |
| [treeverse/lakeFS](https://github.com/treeverse/lakeFS) | 5542 | 2026-09-25 | 数据版本控制 |

## 2. 差距与建议优先级（除数据外）

| 编号 | 能力 | 外部依据 | 本项目现状 | 建议 |
| --- | --- | --- | --- | --- |
| Q1 | **过拟合与验证口径**：purged/embargo 交叉验证、样本权重（重叠/唯一性）、deflated Sharpe、回测过拟合概率 | mlfinlab 的 `cross_validation` / `sample_weights` / `backtest_statistics` 目录 | **已接入（U20）**：purged/embargo 折、唯一性权重、PSR/DSR、PBO（含完全相同配置的退化标注）；缺的是把这些口径应用到模型训练与参数扫描 | 第一批已完成；后续把 purged CV 接进训练与扫描流程 |
| Q2 | **风险与绩效指标族**：Sharpe/Sortino/Calmar、VaR/CVaR、回撤期、月度/年度热力图 | quantstats 与 pyfolio 的核心产出 | **已接入（U22）**：年化/波动、Sharpe/Sortino/Calmar、最大回撤、回撤期、VaR/CVaR、月度与年度矩阵；比较表尚未并排展示风险指标 | 第一批已完成；后续在比较表中并排展示并补滚动窗口口径 |
| Q3 | **因子报告结构**：行业/板块中性 IC、因子自相关与衰减曲线、分位组合多空净值、逐日 IC 分布 | alphalens 的 IC/换手/分组三块 | 已有 IC/RankIC/显著性/分位差/换手/跨 horizon IC；**缺中性化、自相关、多空净值、分布图** | **P1**：与现有因子页同页扩展即可 |
| Q4 | **组合构建**：约束优化（行业/风格中性、权重与换手上限）、风险平价/风险预算、Black-Litterman | Riskfolio-Lib | 只有 TopkDropout 一种组合规则 | **P1**：先做约束与记录口径，避免"最优权重"式的过拟合诱惑 |
| Q5 | **参数扫描与批量实验**：一次配置生成多组参数并汇入同一比较 | vectorbt | 一次一个 Attempt，无批量/扫描 | **P1**：与执行层结合（Attempt 组），注意并发与资源上限缺口 |
| Q6 | **超参搜索与试验管理**：搜索空间、剪枝、试验登记 | optuna | 无 | **P2**：建议在 Q5 之后，避免先有搜索再有口径 |
| Q7 | **归因**：Brinson 归因、因子暴露归因、成本归因 | pyfolio/quantstats（部分）、通用做法 | 无 | **P2** |
| Q8 | **数据与特征治理**：校验规则库、特征注册/血缘、数据版本控制 | pandera、feast、lakeFS | 有数据集内容摘要与来源分级；无校验规则库与特征库 | **P2**：数据接入时再立项，避免空转 |
| Q9 | **容量与拥挤**：冲击成本/ADV 容量模型、因子拥挤度 | 通用做法；本项目已在因子页标记 `not_available` | 需要持仓与成交明细才可算 | **P2**（依赖持仓数据） |

## 3. 结论

- **Q1（验证口径）与 Q2（风险绩效）已完成第一批**（U20/U22，见 [CHANGELOG](CHANGELOG.md)）；残留项是"把口径用于训练与参数扫描"与"比较表并排展示风险指标"。
- 接下来按研究效率推进：Q3（行业中性 IC、因子自相关、多空净值）→ Q4（约束组合优化）→ Q5（参数扫描）；Q6—Q9 留待数据目录与持仓数据接入后再评估。
- 以上都不改变「因子层是工作台计算、必须带公式与数据版本」的既有约束；新增指标同样要登记口径、方向与分组（见 [因子层规范](FACTOR_ANALYSIS.md) §2/§4）。
