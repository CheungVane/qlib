# 验证口径：purged 交叉验证、样本权重、deflated Sharpe 与过拟合概率

状态：生效。版本：1。生效日期：2026-09-26。
关联需求：U20（验证口径）；上游要求 ID：METRIC、GOV-DERIVED、GOV-CLAIMS、COMPARE01、FACTOR_ANALYSIS §4。
验收：IMPLEMENTATION 阶段 M2 的 A31（验证口径）与 A32（过拟合与多重检验）。本文不改变结果语义专题（[结果合同](RESULT_CONTRACT.md)）与来源专题（[来源审计](PROVENANCE_AUDIT.md)）。

## 1. 为什么需要

因子层已经给出 IC、t 值与 BH-FDR，但仍不足以防三类错误：

1. **标签重叠泄漏**：持有期 h 的标签在时间上互相覆盖，普通 K 折会让训练集看到测试期附近的标签（AFML 第 7 章）。
2. **样本非独立**：重叠标签让有效样本数远小于观测数，显著性被高估（AFML 第 4 章）。
3. **多重检验与选择偏差**：试了 N 个配置后挑最好的那个，其 Sharpe 本身带有选择偏差（Bailey & López de Prado 的 deflated Sharpe 与 CSCV/PBO）。

本规范要求平台把这三件事**算出来并显示**，不要求平台自己训练模型；它约束的是"我们如何评价一个已有结果"。

## 2. 口径

| 指标 | 公式/算法 | 输出 |
| --- | --- | --- |
| `purged_folds` | 按时间切 `n_splits` 个测试折；训练集剔除与测试窗口标签区间重叠的样本（purge），并再剔除测试折之后 `embargo` 个样本 | 每折训练/测试索引区间、被剔除样本数与占比 |
| `uniqueness_weights` | 对每个样本 i，令 c_t 为 t 时刻同时存在的标签数，其平均唯一性 `ū_i = mean(1/c_t)`（AFML 4.1） | 每个样本权重、权重和与有效样本数 `Σw` |
| `probabilistic_sharpe` | 用偏度/峰度修正 SR 的标准误（Bailey & López de Prado 2012） | `psr`（SR>基准的概率）与输入统计量 |
| `deflated_sharpe` | 以试验次数 N 估计"纯噪声下的期望最大 SR"，用其作基准算 PSR ⇒ DSR | `dsr`、`expected_max_sr`、输入统计量 |
| `pbo` | CSCV：把 T×N 收益矩阵按时间切成 S 个等长块，穷举半数组合为 IS、其余为 OOS；取 IS 最优配置在 OOS 的分位 | `pbo`（OOS 表现低于中位的概率）、使用的组合数与 S |

约束：

- 收益矩阵必须按同一日历、同一币种对齐；缺失不补 0，含缺口的配置在说明后剔除。
- 试验次数 N 必须来自实际配置数或显式声明，禁止用"看起来更小的 N"美化 DSR。
- 全部输出标记为**工作台计算**：附公式、参数、样本区间、参与配置数与限制。
- 样本不足（例如折数×块数超过可用观测）时返回 `not_available` 与原因，不返回近似值。
- 最小样本按估计量分别定义，不共用阈值：PSR/DSR 需要 ≥10 个观测（偏度/峰度修正的方差估计），PBO 需要 ≥2 个配置且观测数 ≥ 两个时间块；风险指标族需要 ≥20 个观测（尾部分位与年化对短样本更敏感，见 [结果合同](RESULT_CONTRACT.md)）。容差集中在 `numeric.py`（比较表 1e-9 相对差、零离散度 1e-12），不得在别处另立阈值。

## 3. 平台接入

- `GET /v1/validation?run_id=...&horizon=h&embargo=e&splits=k`（读取接口，不启动训练）：对一个或多个运行给出 DSR、PBO、purged 折与唯一性权重摘要；配置少于 2 个时 PBO 返回 `not_available`。
- CLI `qwb validate <run_id>...` 与 HTTP 共用同一服务与口径。
- 比较页在口径检查之后增加"验证卡"：显示 PBO、DSR、purged 折与有效样本数；`pbo` 偏高或 DSR 偏低时用中性提示语说明"可能是选择偏差"，不得写成结论。
- 结果中同时给出"未接入"清单：真正的样本外跟踪（实盘/前瞻模拟）不在本规范内。

## 4. 验收映射

| 验收 | 条件 | 证据位置 |
| --- | --- | --- |
| A31 | purged 折与 embargo 结果可复算；被剔除样本数与占比披露；跨折无标签重叠 | 回归测试（已知跨度夹具） |
| A32 | PSR/DSR/PBO 按公式计算；小样本与单配置返回 `not_available`；输出带公式、试验次数与限制 | 回归测试（已知答案 + 边界） |

完成状态与实测证据记录在 [IMPLEMENTATION.md](IMPLEMENTATION.md)。
