# 验证口径：purged 交叉验证、样本权重、deflated Sharpe 与过拟合概率

状态：生效。版本：2.4（2026-09-27 T02-D 定义冻结，T02-B 后端/API/CLI 与 T02-U 界面均已实现；真实 TrialLedger 与训练协议待 T06/T07）。修订日期：2026-09-27（初始生效2026-09-26）。
关联需求：U20（验证口径）、U23（研究生命周期）；上游要求 ID：METRIC01—06、GOV-DERIVED、GOV-CLAIMS、COMPARE01、FACTOR_ANALYSIS §4。
验收：IMPLEMENTATION 阶段 M2 的 A31（算法）、A32（事后统计），以及A36（实际训练与试验范围；诊断子项归T02，其余归T06/T07）。§2A 已冻结 v2 的口径、DTO 与独立参考值，实现由 T02-B 完成；本文不改变结果语义专题（[结果合同](RESULT_CONTRACT.md)）与来源专题（[来源审计](PROVENANCE_AUDIT.md)）。

## 1. 为什么需要

因子层已经给出 IC、t 值与 BH-FDR，但仍不足以防三类错误：

1. **标签重叠泄漏**：持有期 h 的标签在时间上互相覆盖，普通 K 折会让训练集看到测试期附近的标签（AFML 第 7 章）。
2. **样本非独立**：重叠标签让有效样本数远小于观测数，显著性被高估（AFML 第 4 章）。
3. **多重检验与选择偏差**：试了 N 个配置后挑最好的那个，其 Sharpe 本身带有选择偏差（Bailey & López de Prado 的 deflated Sharpe 与 CSCV/PBO）。

本规范同时约束事后诊断和实际研究验证。平台可委托外部引擎训练，但必须取得真实执行证据才能声明采用了验证方案。仅从已发布收益序列和调用方指定h生成的折/权重属于假设性事后诊断，不证明原训练无泄漏。当前实现主要提供事后统计；完整训练验证证据链尚未接入。

## 2. 口径

| 指标 | 公式/算法 | 输出 |
| --- | --- | --- |
| `purged_folds` | 按时间切 `n_splits` 个测试折；训练集剔除与测试窗口标签区间重叠的样本（purge），并再剔除测试折之后 `embargo` 个样本 | 每折训练/测试索引区间、被剔除样本数与占比 |
| `uniqueness_weights` | 对每个样本 i，令 c_t 为 t 时刻同时存在的标签数，其平均唯一性 `ū_i = mean(1/c_t)`（AFML 4.1） | 每个样本权重与唯一性权重和 `Σw`；不能直接视为用于显著性推断的独立有效样本量 |
| `probabilistic_sharpe` | 用偏度/峰度修正 SR 的标准误（Bailey & López de Prado 2012） | `psr`（SR>基准的概率）与输入统计量 |
| `deflated_sharpe` | 以试验次数 N 估计"纯噪声下的期望最大 SR"，用其作基准算 PSR ⇒ DSR | `dsr`、`expected_max_sr`、输入统计量 |
| `pbo` | CSCV：把 T×N 收益矩阵按时间切成 S 个等长块，穷举半数组合为 IS、其余为 OOS；取 IS 最优配置在 OOS 的分位 | `pbo`（OOS 表现低于中位的概率）、使用的组合数与 S |

约束：

- 收益矩阵必须按同一日历、同一币种对齐；缺失不补 0，含缺口的配置在说明后剔除。
- DSR必须区分研究范围内原始试验数M、实际可用收益配置数和用于修正的独立试验数N。N来自完整试验记录或明确的估计/声明，披露相关性处理方法、不确定性及缺失试验；不能默认以当前勾选结果数代表全部搜索历史。声明的N必须实际进入公式，不能只写入展示元数据。范围不完整时标为探索性诊断，禁止宣称已纠正全部选择偏差。
- 全部输出标记为**工作台计算**：附公式、参数、样本区间、参与配置数与限制。
- 样本门槛分别检查：purged折的可用训练/测试样本与PBO时间块属于不同计算，不用“折数×块数”作为统一下限；不足时返回 `not_available` 与原因。具体折内空集、常数及非有限值规则须在T02-D逐项冻结。
- 最小样本按估计量分别定义，不共用阈值：PSR/DSR 需要 ≥10 个观测（偏度/峰度修正的方差估计），PBO需要≥2个配置；首版S为4—12的偶数，观测数T≥2S，并满足组合预算。等长块与T不能整除S时的处理须在T02-D冻结，不以当前近等长分块实现默认为合同通过；风险指标族需要 ≥20 个观测（尾部分位与年化对短样本更敏感，见 [结果合同](RESULT_CONTRACT.md)）。容差集中在 `numeric.py`（比较表 1e-9 相对差、零离散度 1e-12），不得在别处另立阈值。

### 实际研究验证协议（VAL01—06）

- VAL01：运行前冻结数据、标签实际区间、特征可用时点、切分、purge/embargo及预处理拟合范围，记录方案版本。训练/验证/最终测试角色明确；滚动样本外要求每次拟合只使用当时允许的数据，不将可使用双向训练样本的历史交叉验证称为前瞻训练。
- VAL02：每折保存实际训练/测试样本身份或可核验清单、模型/预处理版本、样本外预测、标签及评价产物。缺少折内重训或实际样本证据时，状态为未验证，不能以预先算出的切分代替。
- VAL03：唯一性权重是否用于拟合、是否用于统计量估计分别记录；展示权重不等于已调整PSR/DSR的不确定性。来源样本区间未知时，按h构造的重叠区间必须标明假设。
- VAL04：TrialLedger保留搜索范围、全部候选及失败/淘汰/选中原因、参数差异、测试集访问与Agent预算。最终保留测试集一旦用于调参或择优即标为已使用，不能继续宣称独立最终检验。失败试验没有收益时不得补0，但仍保留试验记录及选择偏差限制。
- VAL05：验证报告锁定输入revision、协议、分析器/公式版本和试验集合快照；分别返回独立维度：diagnostic_state=available/unavailable/error，protocol_state=unverified/verified/invalidated/not_applicable，forward_state=not_started/tracking/stopped；三者可同时存在，不是互斥晋级状态。verified只证明该协议证据核验通过，不保证alpha有效；无训练的规则策略可标not_applicable但须说明。PBO的候选集合、优化指标、费用/日历/评估口径及对齐损失须披露；同一日期并不足以证明可比较。

VAL06（试验范围与可复现诊断）：TrialLedger有稳定search_scope_id；报告锁定不可变ledger_snapshot_id与所含trial_id清单。相同有效配置/种子的执行重试归同一trial并保留所有Attempt；用于择优的种子、模型、因子或超参变化建立新trial，相关性与重复性质另记，不能自动当独立试验。试验记录在研究发起前创建，失败不能从搜索历史中删除。新增试验产生新账本快照，不改历史报告的N。

首版DSR允许显式声明N并披露依据，不要求自动估计相关性；同时披露M、可用收益配置数、SR离散度样本来源及统计约定。缺少可估计SR离散度的候选收益或N≤1时DSR返回不可用；PSR仍可独立计算。手工选择不完整集合只能输出探索性诊断，不能在未建设TrialLedger时伪造全范围修正。

验证接口读取必须接受明确run_id+revision_id集合；省略revision时在请求起点一次性解析并返回实际版本。报告锁定选择集合、对齐后区间及全部参数，复算时禁止重新解析latest。PBO采用完整共同区间，披露被排除配置及丢弃日期；不允许通过静默裁剪或仅挑优胜者形成全搜索结论。

DSR的试验信息要求参考 [Bailey与López de Prado原论文](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)。最小计算样本阈值只保证算法入口条件，不证明估计稳定或研究有效。前瞻模拟的定义见 [研究生命周期](RESEARCH_LIFECYCLE.md)。

## 2A. T02-D 定义冻结：验证 v2（2026-09-27）

状态：设计门通过，尚未实现。本节冻结 T02-B 要落地的计算口径、输入解析、DTO 与独立参考值，不改变 §2 的目标合同；与本节冲突的旧表述以本节为准并按版本记录。通过本节只代表可以开始编码：A31/A32 的诊断证据要等 T02-B 交付，A36 仍须 T06/T07 的实际训练与试验账本证据才能关闭。

### 2A.1 版本与兼容

- 请求参数 `analysis_version=1|2`，默认 1；省略时保持现行 v1 字段与数值，v2 响应带 `schema_version=2`。
- `/v1` 路径、结果包 schema_version 与本节的分析版本互相独立；v2 不改变已发布结果与历史 revision。
- CLI 与 HTTP 共用同一服务与阈值：`qwb validate ... --analysis-version 2`。
- 把 v2 参数用在 v1 上必须拒绝，不得静默忽略。UI 在 T02-U 显式请求 2；遇到 v1 响应显示“旧定义，未满足当前纠正合同”，不得混用 v1 字段。

### 2A.2 输入、版本解析与共同轴

| 参数 | 范围 | 语义 |
| --- | --- | --- |
| `run_id` | 1—20 个，必填，去重保序 | 参与分析的已记录运行 |
| `revision_id` | 可选，可重复 | 与 `run_id` 按出现顺序一一配对；两者数量不等即 400；省略表示请求发起时解析一次 |
| `analysis_version` | 1—2，默认 1 | 口径版本 |
| `horizon` | 1—60，默认 1 | 只影响标签跨度（purge/embargo 与唯一性权重），不进入 PSR/DSR/PBO |
| `splits` | 2—20，默认 5 | 只影响 purge 折 |
| `embargo` | 0—60，默认 horizon | 只影响 purge 折 |
| `blocks` | 偶数 4—12，默认 8 | CSCV 分块数 S，只影响 PBO |
| `trials` | 2—1000，可选 | 声明进入 DSR 基准的试验数 N，见 2A.6 |

版本解析：显式 `revision_id` 一律按确切版本读取；省略时在请求起点解析一次，响应返回实际版本与 `resolved_at` 并标 `resolution=latest_at_request`；复核不得重新解析 latest。未知 run 返回 404；revision 不存在或不属于该 run 返回 400，不退回 latest。

共同轴按固定顺序解析：

1. 每个配置先过 2A.3 的收益口径门禁，不通过者移入 `excluded` 并给机器原因。
2. 剩余配置的记录日期取交集作为候选轴。
3. 检查每个剩余配置在候选轴上的取值；出现 null 或非有限值即移入 `excluded`。
4. 若本轮发生排除，回到第 2 步重算（交集只会扩大）；直到不再变化。
5. 没有剩余配置返回 400 `no_usable_configurations`；候选轴观测数少于 10 返回 400 `insufficient_common_observations`。

排除必须显式：被排除配置同时出现在 `basis.trial_scope.excluded` 与 `not_available`，不静默补 0、补日期或用其他序列顶替。

### 2A.3 收益口径与同质性

- 只接受已登记定义，并与风险 v2 共用同一映射：`native.qlib.return` + `native.qlib.report.return.v1`（成本前）、`platform.equity` + `platform.equity.account.v1`（成本后，按相邻有效权益点派生）。
- 逐项校验 `definition_id`、`axis`、`calendar_id`、`unit`、`availability`、`cashflow_policy` 与取值有限性；不满足给出对应原因，不做推断。
- **禁止静默回退**：主来源存在但不可用时不得改用另一序列；缺测不补 0、不跳过。
- `cashflow_policy` 必须为 `none`；其它口径需另立定义版本。
- rf：v2 不扣减无风险利率。`SR` 就是所声明序列的均值/标准差，`SR*=0` 表示“同频收益均值高于 0”，不是“高于无风险利率”。需要 rf 口径必须已有登记为已扣减的序列，另立定义版本。
- 同质性：进入 DSR 离散度与 PBO 的配置必须共享 cost basis 与 `calendar_id`。混用返回 `mixed_return_basis`/`mixed_calendar`，对应统计不可用；单配置 PSR 仍可返回。

### 2A.4 Sharpe 与矩的估计量约定

- 频率：逐期、不年化。本版本不接受年化 SR 或 ppy 参数；年化值只作展示，不得进入任何公式。
- `SR = mean(r)/std(r, ddof=1)`；`std ≤ 1e-12` 视为零离散度，返回不可用。
- 偏度 `γ3 = mean((r-mean)^3)/std^3`、峰度 `γ4 = mean((r-mean)^4)/std^4`（**非超额**，正态=3）；矩的分母是 n，标准差用 ddof=1。这是本规范选定的估计量约定，与带小样本校正的常见默认不同，必须在定义卡披露；改用其他估计量属新定义版本。
- 自检：正态 iid 下该式退化为 `Var(SR)=(1+SR²/2)/(n-1)`。
- 非有限值与缺测一律 fail-closed，不做过滤后继续。

### 2A.5 PSR 定义卡

公式：`PSR(SR*) = Φ( (SR - SR*)·√(n-1) / √(1 - γ3·SR + (γ4-1)/4·SR²) )`，本版本 `SR* = 0`。

- 输入：确切 revision、收益定义与样本区间、n、均值、ddof=1 标准差、偏度、峰度。
- 可用条件：n≥10、标准差>0、方差项>0、矩有限。
- 不可用原因至少包含：`insufficient_observations`、`zero_dispersion`、`invalid_sharpe_variance`、`missing_or_nonfinite_observation`、`return_basis_unknown`。
- PSR 与 N、分块无关；单配置请求可以给出 PSR。

### 2A.6 DSR 定义卡（M / C / N）

- **M**：研究范围内声明的原始试验数，可未知。**C**：本次请求中可用且同质的配置数。**N**：真正进入基准公式的声明试验数。
- `SR* = σ(SR_trials)·((1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)))`；γ 为 Euler–Mascheroni 常数，`σ` 由 C 个可用配置的逐期 SR 以 ddof=1 计算。
- 可用条件：C≥2、σ>0、2≤N≤1000 且 **N≥C**。不满足返回不可用，如 `deflated_sharpe_needs_at_least_two_trials`、`declared_trials_below_usable_configurations`、`insufficient_trial_dispersion`。
- N 来源分两级：`declared_by_caller`（调用方显式声明）或 `inferred_from_request_selection`（省略时取 C）。后者只代表本次选择，**不得**当作完整搜索历史；在 TrialLedger 接入前，两种来源都标 `scope_completeness=incomplete`，DSR 一律为**探索性诊断**。
- 当 N>C 时 `σ` 仍只能由 C 个可用配置估计：`dispersion.basis=observed_subset` 并在限制中说明它不代表完整搜索的离散度，不得据此声称已校正全部选择偏差。
- **N 必须实际进入公式**：只改变 N 时 `expected_max_sharpe` 与 DSR 必须随之变化，见 2A.9 反例。
- 相关性：首版不估计有效独立试验数，`correlation_assumption=unmodeled_iid`；未建模相关性时基准是近似值，不得声称已校正相关选择偏差。
- `DSR = PSR(SR*)`；方差项仍用候选自身 SR，属论文的插件近似，须在定义卡披露。

### 2A.7 PBO 定义卡（CSCV）

- 矩阵：行是共同轴时序，列是可用且同质的配置；缺测不补。记 **K** 为重复折叠后参与 PBO 的不同配置数（与 2A.6 的 DSR 声明试验数 N 是不同量，不得混用符号）。
- 分块：S 为偶数 4—12，默认 8；要求 T≥2S。`r = T mod S ≠ 0` 时**丢弃最早的 r 条观测**，保留最近完整窗口，并把 `dropped_observations.count` 与具体日期写入报告。这是对论文严格等长块要求的显式偏离，不得静默。
- 块内表现：该块内该配置收益的逐期 Sharpe（ddof=1、不年化）。任何必需 Sharpe 不可定义即整请求 PBO 不可用 `zero_dispersion_block`。
- 枚举“S 选 S/2”个组合，半数块为 IS、其余为 OOS；IS 最优取 IS Sharpe 最大者，并列取配置序号最小者。
- OOS 秩 `r_rank = 1 + #{j≠best: score_j < score_best} + 0.5·#{j≠best: score_j = score_best}`（j 遍历 K 个配置、不含 best），`ω = r_rank/(K+1)`；`ω ≤ 0.5` 计入。
- `PBO = 计入组合数 / 组合总数`；同时返回 `combinations_total` 与 `combinations_used`，两者不等必须解释。
- 重复配置：收益向量在 1e-12 内相同者折叠为一个代表并披露；折叠后不足 2 个不同配置返回 `degenerate_configurations`，不是 PBO=1。
- 组合预算：S≤12 时组合数最多为 924（S=12），不构成限制；上限调整须同步阈值来源。

**当前实现缺陷（基线 58fdeeb3，T02-B 必须修正）**

- `deflated_sharpe` 以可用 SR 个数作为 N 代入 Φ⁻¹；调用方 `trials` 只写入 `declared_trials`，未进入公式。
- PBO 秩用「下方数 + 0.5×(含自身的并列数)」再除以 N，与 ω=r/(N+1) 不一致；N=2 时把“IS 最优同时 OOS 最优”也计入过拟合。
- PBO 用 `linspace` 近等长分块且未定义余数；零离散度被记为 ±∞/0；可用组合不足时 `continue` 静默跳过；重复配置只标记不折叠。
- `probabilistic_sharpe` 先 `values[isfinite]` 丢弃非有限值，再按剩余个数判样本量。
- `application.strategy_validation` 先要求每个 run 至少 20 个观测，与 §2 的 PSR/DSR≥10 阈值不一致；v2 改为按估计量分别检查（PSR/DSR≥10、PBO≥2S）。
- 验证链路使用 `series_view.return_series`：主来源存在但不可用时会回退到权益序列，且不校验 `definition_id`/axis/calendar/unit/cashflow_policy，弱于风险 v2 的登记映射。
- `uniqueness_weights.effective_samples` 实为 Σw，名称会被误读为独立有效样本量。

### 2A.8 v2 DTO 与错误样例

v2 在 v1 顶层键上扩展（`configs`、`pbo`、`leakage`、`not_available`、`limitations` 保留）：

| 字段 | 内容 |
| --- | --- |
| `inputs[]` | `run_id`、`revision_id`、`resolution`、`resolved_at` |
| `basis.window` | `policy=intersection_of_requested_revisions`、起止、观测数、calendar_id 集合 |
| `basis.return_basis` | `source_metric_id`、`definition_id`、`cost_basis`、`cashflow_policy`、`unit`、`frequency` |
| `basis.sharpe` | `estimator=mean_over_std_ddof1`、`ddof=1`、`moments=population_moments_over_ddof1_std`、`kurtosis=non_excess`、`frequency=per_period`、`annualisation.applied=false` |
| `basis.trial_scope` | `available_configurations`、`usable_configurations`、`excluded[]`、`declared_n`、`declared_n_source`、`dispersion{value,ddof}`、`correlation_assumption`、`scope_completeness` |
| `definitions` | 逐项公式、估计量约定、阈值与已知偏离 |
| `configs[].psr` / `configs[].dsr` | `availability`、`value`、`reason`、`inputs`（run/revision/definition/样本区间） |
| `pbo` | `availability`、`value`、`reason`、`blocks`、`observations_per_block`、`dropped_observations`、`combinations_total/used`、`collapsed_duplicates`、`criterion` |
| `leakage.uniqueness` | `weight_sum`（v1 的 `effective_samples` 更名），附“不是独立有效样本量”的限制 |

错误与不可用样例：

- 单配置：HTTP 200，PSR 可用；DSR `unavailable`（`deflated_sharpe_needs_at_least_two_trials`）；PBO `unavailable`（`pbo_needs_at_least_two_configurations`）。
- 未登记收益定义或现金流未知：该配置进入 `excluded` 并给原因；全部被排除时 400 `no_usable_configurations`。
- `trials` 小于可用配置数：400 `declared_trials_below_usable_configurations`。
- `T mod S ≠ 0`：丢弃最早 r 条并披露，仍返回 200；T<2S 时 PBO `unavailable`（`not_enough_observations_for_blocks`）。
- 混用 cost basis 或日历：DSR/PBO `unavailable`（`mixed_return_basis`/`mixed_calendar`），PSR 仍逐配置返回。

### 2A.9 独立参考值与验收样例

参考值由独立脚本按本节公式重算，不引用工作台实现：[evidence/20260927-t02d-reference.py](evidence/20260927-t02d-reference.py)。

**夹具 A（请求级：4 配置 × 20 个交易日）**：配置 k 的收益为 `r_i = d_k + 0.01·(-1)^i`（i=0…19），漂移 d 取 0.001/0.002/0.003/0.004。

| 配置 | 漂移 | 均值 | 标准差(ddof=1) | 逐期 SR | 偏度 | 峰度(非超额) | PSR(SR*=0) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | 0.001 | 0.001 | 0.0102597835 | 0.0974679434 | 0 | 0.9025 | 0.6645459833 |
| C2 | 0.002 | 0.002 | 0.0102597835 | 0.1949358869 | 0 | 0.9025 | 0.8023651500 |
| C3 | 0.003 | 0.003 | 0.0102597835 | 0.2924038303 | 0 | 0.9025 | 0.8990026123 |
| C4 | 0.004 | 0.004 | 0.0102597835 | 0.3898717738 | 0 | 0.9025 | 0.9556755846 |

试验 SR 离散度（ddof=1）= 0.1258305739，候选为 C2：

| 声明 N | expected_max_sharpe | z | DSR |
| --- | --- | --- | --- |
| 4 | 0.1323892188 | 0.2727609572 | 0.6074815132 |
| 10 | 0.1981326080 | -0.0139406418 | 0.4944386687 |
| 20 | 0.2391671724 | -0.1928890559 | 0.4235229281 |

只改变 N 的反例：N 从 4 增到 10，基准上升、DSR 下降，且三个取值都严格落在 (0,1) 内，能判定“N 是否真的进入公式”。

**夹具 B（PBO 主导：T=8、S=4、2 配置）**：A 的分块收益为 `[0.02,0.04] / [0.03,0.05] / [0.01,0.03] / [0.02,0.06]`，B 为 A 的逐值相反数。六种组合的 IS 最优恒为 A，A 的 OOS 秩恒为 2、ω=2/3，**PBO=0**。

**夹具 C（PBO 中间值：T=8、S=4、2 配置）**：

| 块 | A | B |
| --- | --- | --- |
| 1 | +0.04, +0.06 | −0.04, −0.02 |
| 2 | +0.05, +0.07 | −0.06, −0.04 |
| 3 | −0.05, −0.03 | +0.02, +0.04 |
| 4 | −0.04, −0.02 | +0.02, +0.04 |

| IS 块 | OOS 块 | A IS | B IS | A OOS | B OOS | IS 最优 | 秩 | ω | 计入 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1,2 | 3,4 | 4.260282 | −2.449490 | −2.711088 | 2.598076 | A | 1 | 1/3 | 是 |
| 1,3 | 2,4 | 0.093934 | 0.000000 | 0.281801 | −0.210042 | A | 2 | 2/3 | 否 |
| 1,4 | 2,3 | 0.210042 | 0.000000 | 0.169842 | −0.210042 | A | 2 | 2/3 | 否 |
| 2,3 | 1,4 | 0.169842 | −0.210042 | 0.210042 | 0.000000 | A | 2 | 2/3 | 否 |
| 2,4 | 1,3 | 0.281801 | −0.210042 | 0.093934 | −0.210042 | A | 2 | 2/3 | 否 |
| 3,4 | 1,2 | −2.711088 | 2.598076 | 4.260282 | −2.449490 | B | 1 | 1/3 | 是 |

`PBO = 2/6 = 0.333…`。表中 IS 列为 0.000000 是合法的零 Sharpe（该块内标准差非零），与零离散度不可用不是一回事。

**夹具 D（退化）**：两列收益向量在 1e-12 内相同时折叠为一个代表；折叠后不足 2 个不同配置即 `degenerate_configurations`，不是 PBO=1。

**其它必测项**

- 单配置请求：PSR 可用，DSR/PBO 不可用，理由见 2A.8。
- `horizon` 由 1 改为 5：PSR/DSR/PBO 数值逐位不变，只有 leakage 输出变化。
- 历史 revision：同一 run 存在 R1、R2 时，显式请求 R1 的结果锁定 R1，R2 发布后复核不漂移。
- v1 回归：省略 `analysis_version` 时字段与数值与基线 58fdeeb3 一致。

### 2A.10 交付出口

T02-B 按本节实现后端/API/CLI，并登记 A31/A32 与 A36 诊断子项证据；T02-U 更新界面并做浏览器检查。A36 父项、TrialLedger 与实际训练证据仍归 T06/T07，不在 T02 关闭。

## 3. 平台接入

**当前实现边界（2026-09-27 T02-B/T02-U 后）**：`/v1/validation` 与 CLI `validate` 增加 `analysis_version=1|2` 与可重复的成对 `revision_id`；**默认 v1 行为与字段不变**，v2 按 §2A 输出 `schema_version=2`。§2A.7 登记的缺陷在 v2 中已修正（声明N进入公式、CSCV秩ω=r/(K+1)、等长分块与余数披露、重复配置折叠、零离散度/非有限值fail-closed），v1 保留原算法与其历史数值。收益口径复用风险 v2 的登记映射，主来源不可用时不再回退。**界面已切换（T02-U）**：验证卡显式请求 v2，遇到 v1 响应显示"旧定义"而不混用，并展示N来源、Σw非独立样本量、被排除配置与探索性状态；TrialLedger 与训练证据仍归 T06/T07。

- `GET /v1/validation?run_id=...&horizon=h&embargo=e&splits=k`（读取接口，不启动训练）：对一个或多个运行给出事后 DSR、PBO、假设性purged折与唯一性权重摘要；不得凭此接口声明实际训练采用了交叉验证；配置少于 2 个时 PBO 返回 `not_available`。
- CLI `qwb validate <run_id>...` 与 HTTP 共用同一服务与口径；分析版本选择遵循RESULT_CONTRACT，版本2补本轮状态、范围与参数语义，版本1保留历史兼容。
- 比较页在口径检查之后增加"验证卡"：显示 PBO、DSR、purged折与唯一性权重和，并披露诊断/训练证据状态；`pbo` 偏高或 DSR 偏低时用中性提示语说明"可能是选择偏差"，不得写成结论。
- 结果中同时给出"未接入"清单：前瞻模拟/实盘尚未接入，其合同见RESEARCH_LIFECYCLE与TRADING_BOUNDARY；历史交叉验证不代替前瞻证据。

## 4. 验收映射

| 验收 | 条件 | 证据位置 |
| --- | --- | --- |
| A31 | purged折与embargo算法可复算；被剔除样本数与占比披露；夹具跨折无标签重叠；此项仅为算法验收 | 回归测试（已知跨度夹具） |
| A32 | PSR/DSR/PBO按各自冻结定义计算；不足各自样本门槛返回不可用。单配置可计算PSR；DSR缺候选SR离散度或N≤1不可用，PBO少于2配置不可用；输出带公式、试验次数与限制 | §2A 独立参考值（含N反例与PBO夹具）＋实现后的回归测试 |

VAL06及实际训练协议、完整试验范围另按 A36 验收，不能由 A31/A32替代。当前UI/DTO仍需补齐上述标记、版本和范围，旧“有效样本数”展示需要纠正；这属于待实现差距；本次文档复审没有修改代码或重新运行训练。完成状态与实测证据记录在 [IMPLEMENTATION.md](IMPLEMENTATION.md)。
