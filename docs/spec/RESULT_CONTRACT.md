# 结果安全与查询合同（2026-09-27修订）

状态：生效。版本2.1（2026-09-27执行交接复审）；风险/因子v2后端已完成T01-R/F切片；T01-U界面已验收；比较身份与其他估计量仍待验收，当前证据见IMPLEMENTATION。

依据用户授权修复审查R01—R12及S01—S06。本专题细化ARC06/07/08、METRIC02—05、COMPARE01、RW02—05、CN04；不降低阶段验收要求。

## 导出与来源

- 每个RD-Agent结果以来源实例、会话、Loop、runner事件定位；只有同一实验workspace的报告/指标/有效配置/质量能组成结果。缺少报告不借用其他实验或图表补齐。无runner的独立图表可以作为报告观察，但不附会话其他因子/指标。
- 事件按Loop关联；同Loop有多个runner时，公共事件只能标为Loop过程，不能把反馈指定给某个runner。历史会话URL保留为分轮导航。原有结果revision不改写，旧导出版本标为归属未复核、禁止排名。
- 所有证据在首次持久化前统一递归脱敏；配置密钥、敏感键及异常文本适用同一策略。快照与结果包均须通过此步骤。
- 源证据中的synthetic优先于导入者声明；二者冲突拒绝发布。未知来源保留declared性质，不宣称认证；fixture必须synthetic。配置指纹必须核验，不能代替数据内容版本。
- MLflow只读操作使用SQLite mode=ro备份出的临时副本，客户端仅连接副本；非SQLite文件来源复制元数据后读取。任何客户端升级不得迁移源库。

## 当前DTO切片

| 字段 | 语义/校验 |
| --- | --- |
| schema_version / run | 版本1；不透明平台身份；带时区created_at必填，按真实瞬时时间排序；新包时间规范为UTC，历史对象不重写 |
| series.axis | time/trading_date/step/scalar；time按瞬时严格递增且不重复；step为非负整数且有step_kind；交易日有calendar_id |
| availability | available须有点；empty/not_recorded/unsupported/error无点，均合法；null观测须reason；freshness为独立信息，缺失时unknown |
| series summary | 全量revision的point_count、valid_points、missing_points、start/end、first/last及端点reason、minimum；不从第一页推算摘要 |
| 查询分页 | 最多2000点；offset/next_offset/total_points明确；UI可翻页，显示当前范围；分页不是降采样，不无界下载 |
| review事实 | ending_equity及total_cost取报告原末点，缺失保留null及原因；最后有效观测另列日期/值；完整区间回撤遇缺口返回null，不冒充完整结果 |
| drawdown定义 | observed_equity.v1只从首个观测权益起；initial_equity.v1须有初始权益证据。两者均为工作台派生；旧错误definition名称保持历史对象并给限制注解 |
| provenance / data_nature | 来源与真实/模拟性质分开；源证据冲突拒绝；旧无来源证明的声明不得变成认证 |

当前运行时验证器为model.validate_package；`/v1`路由覆盖与核心DTO键集合已由契约测试冻结（API03，`scripts/workbench_gate.sh`一键复核）。全领域MetricDefinition/主体、freshness采集与完整JSON Schema校验器仍为M0未完成项。本表约束当前切片，不以缺字段自动填造fresh/coverage。

## 执行结果自动入库（EXEC12）

- 自动入库与显式 `import-qlib` 使用同一适配器与校验；来源实例、外部ID、adapter_version 与内容哈希共同决定 run/revision 身份，同内容重复导入复用既有 revision。
- 每次自动入库在平台库记录 ImportReceipt（attempt、run、revision、来源实例、外部ID、适配器版本、状态、时间、失败原因）；Attempt 的 `outcome.result_import` 是投影，回执是事实记录。
- 自动入库不得跳过来源冲突拒绝、脱敏、情景指纹核验与只读源库访问；导入失败时 Attempt 保持执行成功但入库状态为失败并给出原因。
- 导入对象的 provenance/字段来源与显式导入一致：引擎原始记录、工作台派生与模拟标记照旧，`imported` 不等于研究有效。

## 数据集内容版本与评估口径（比较表前置）

- `run.dataset.version` 记录**已物化数据快照的内容摘要**：对已声明的数据组件按稳定相对路径排序后取文件 SHA-256，再汇总摘要（当前本地 `basis=files_sha256`）；排除 `scenario.json`、`content.json` 等配置/摘要元文件，并把摘要写入快照的 `content.json`；只登记文件数量与字节数，不写原始行情。
- 内容摘要与情景/配置指纹是两件事：GOV-CONFIG 仍然禁止用配置指纹代替数据内容版本。本机 CN 快照由固定种子与日历确定性生成，因此内容摘要稳定可复算。
- CN适配器的比较身份按下方「身份分层」分别生成。旧版将 `evaluation_id` 直接等同完整情景指纹的规则已被替代，不能继续作为当前实现依据。
- 历史 revision 不改写：缺少内容摘要或 `evaluation_id` 的旧对象继续保持不可排名状态，原因随比较结果显示；重跑或重新导入会产生新 revision。
- 数据目录正式接入后，`dataset.version` 应由供应商数据的内容摘要或版本号填充，本机的文件摘要机制仍然适用于本地快照与夹具。

## 比较模式

API/CLI支持mode=auto/equity/metric；auto对platform.equity选equity，其余选metric。并排浏览一直允许，未知/差异显示原因。尚不提供费用实验的自动排名，费用不同仍可并排查看。

比较按对象分组（[因子层规范](FACTOR_ANALYSIS.md) §2）：训练/研究/回测各有自己的指标集合，**跨组只并排、不做排名**；当前只有回测组且同一把尺子（数据内容 + 执行口径 + 评估口径）时才允许最优/最劣标记；训练/研究组仅并排。分组由服务端登记，未登记归入「其他/未登记」并只并排。

| 必须已知且匹配 | equity | metric |
| --- | --- | --- |
| 数据集id+内容version、synthetic性质、非fixture | 是 | 是 |
| 单位、定义版本（unknown/unspecified不视为已知）、轴 | 是 | 是 |
| 完整有效观测及相同坐标、交易日日历/step_kind（按轴适用） | 是 | 是 |
| currency | 是 | 金额指标适用；其他指标不适用 |
| evidence.comparison.execution_id | 是 | 是；当前可排名的回测指标均须真实执行语义身份，不创造无交易占位身份绕过检查 |
| initial_equity、cashflow_policy、price_basis、benchmark_id | 是；现金流首版只接受none | 当前回测金额/收益/风险指标同样要求这些字段；将来例外须先登记定义与验收，不能由调用者声明不适用绕过 |
| evidence.comparison.evaluation_id | 是，标识同一评估语义/样本口径 | 是 |
| evidence.comparison.experiment_id（研究实验身份） | 允许不同：作为实验变量列出，不阻断排名 | 同左 |

comparison为中立证据对象，不固定要求cn_scenario。未知字段不能因两个null相等就通过。权益比较需实际初始资金，首个观测权益不充当初始资金。叠图至少要求已知且相同单位、轴、币种、日历/step_kind；排名另满足整套检查。默认模式不自动重基准化或转换币种。

### 身份分层（2026-09-26修订）

比较需要三类匹配身份与一类允许变化的实验身份，混淆它们就会出现"要么永远不能排名，要么把实验变量当同质条件"的偏差：

| 身份 | 覆盖内容 | 用途 | 不覆盖 |
| --- | --- | --- | --- |
| `dataset`（id + 内容版本） | 数据来源身份与**逻辑内容摘要** | 排名必须先已知且一致；Qlib/RD-Agent物化引用同一规范数据清单；不能对不同引擎物化字节直接判等 | 配置、模型、费用规则 |
| `execution_id` | 交易与成本口径：市场规则、账户与费用、日历、撮合/成交参数、基准、币种 | equity/metric排名的执行测量条件 | 模型、策略、Agent、评价区间 |
| `evaluation_id` | 样本与度量口径：评价区间、训练/测试切分、标签、质量规则 | equity/metric排名的样本口径 | 模型、策略、Agent |
| `experiment_id`（新增） | 研究实验变量：模型与超参、策略参数、Agent 配置 | **允许不同**；差异必须作为实验变量显式列出，不得当作相同条件 | 交易/成本/样本口径 |

- CN 适配器把已核验的情景配置拆成上述身份：`execution_id` 与 `evaluation_id` 分别对"交易与成本"、"样本与度量"取确定性哈希，`experiment_id` 对模型/策略/Agent 取哈希；完整情景指纹仍用于数据物化与模板版本，但不再充当排名门槛。
- 排名要求 `dataset`、`execution_id`、`evaluation_id` 三者已知且一致；`experiment_id` 不同时进入"实验变量"列表并照常显示，不阻断排名。
- 费用/规则差异属于 `execution_id` 差异：按 COMPARE01 作为实验变量并排展示，默认不参与排名；接入费用实验模式后再定义其排名口径。
- 未知不能因两个 null 相等而通过；历史对象缺少任一身份时保持不可排名，并在界面写明缺哪一项。

### 可比较性反例与未知处理

- 同数据、执行和评价身份，模型/策略不同：可进入回测指标排名；方向未知的行仍不排名。
- 同一金额指标即使选择metric模式，初始资金不同或现金流未知也不能排名，不能利用mode绕过equity要求。
- 模型相同但测试窗口、费用、标签或数据版本不同：并排展示并列差异，默认不排名。
- experiment_id未知时：可以在三类匹配身份已知且一致的前提下比较观测结果，但必须注明实验变量未记录，不能声称差异由某个模型参数造成；未知不是“实验相同”。
- 本节是适用性合同，首批须把允许排名的指标及所需字段登记为服务端清单；未登记指标只并排，不自行推断例外。

## 绩效与风险指标族（U22）

这些指标由平台从**已记录的收益或权益序列**计算，属于工作台计算；必须随结果返回公式、样本区间、年化参数与来源说明，样本不足或退化情形返回 `not_available` 与原因，不返回近似值、不填 0。

| 指标 | 口径 |
| --- | --- |
| 总收益 / 年化收益 | 复利总收益 `Π(1+r)-1`；年化按 `(1+总收益)^(ppy/N)-1`，`ppy`取调用方显式参数或本次配置（CN情景为238），记录来源；不能当作历史运行参数 |
| 波动 / Sharpe | 波动=`std(r, ddof=1) ×√ppy`；Sharpe=`mean(r-rf)/std(r-rf, ddof=1) ×√ppy`，rf与收益同频；首版默认rf=0须显式记录为工程假设；已扣rf的输入不得重复扣减；基准超额收益须声明参照物，不得同名冒充无风险超额Sharpe；零离散度返回不可用 |
| Sortino（纠正定义 `platform.sortino.target_downside.v2`） | 同频目标收益T；`DD = sqrt(mean(min(0, r-T)^2))`，mean分母包含全部N个观测；`Sortino = mean(r-T)/DD ×√ppy`。默认T=0须声明为工程假设；DD=0返回不可用，不围绕负收益子集均值计算标准差 |
| Calmar | 年化收益 / \|最大回撤\|；无回撤时返回不可用 |
| 最大回撤与回撤期 | 由权益曲线（收益累乘）计算峰谷回撤；回撤期给出开始、谷底、恢复日期、深度与持续天数，未恢复的回撤标记 `recovering` |
| VaR / CVaR | 历史法：日收益的 5% 分位为 VaR；分位以下样本均值为 CVaR；同时给出样本数与窗口 |
| 分布与极值 | 正收益比例、偏度、峰度、最好/最差单日 |
| 月度 / 年度收益 | 按日历月/年聚合的复利收益矩阵；缺月显示 `null` 而不是 0 |

定义卡与兼容：上述风险指标遵循METRIC06。Sortino目标下行偏差参照 [CME托管的定义说明](https://www.cmegroup.com/education/files/rr-sortino-a-sharper-ratio.pdf)。旧实现 `mean(r)/std(r|r<0)` 与本定义不等价：旧产物保留旧公式和限制，新实现必须使用新definition_id；历史0.1验收不能证明v2正确。回归必须覆盖恒定负收益、相同亏损幅度但不同发生频率、非零目标和无下行偏差；手算参考不能只复制实现。T01-R已实现风险API/CLI的v2纠正；API/CLI默认v1保持旧定义，UI显式请求v2；T01/A34已验收，证据见IMPLEMENTATION。

### 首批定义卡、版本选择与验收样例

风险、因子分析API/CLI已增加 `analysis_version=1|2`（CLI对应 `--analysis-version`）；验证分析的同名版本机制仍待T02实现，不能据此认为验证接口已支持版本2。风险/因子省略参数时保留版本1响应，工作台UI已在T01-U显式请求2。版本1保持原字段/数值及既有来源说明；CLI文本/界面呈现旧版时额外标注“旧定义，未满足当前纠正合同”，不能宣称符合纠正定义；版本2使用新的响应schema_version及定义卡，不改变结果包schema_version或 `/v1` 路径含义。版本1停用须另记录兼容决定，不能把默认值悄悄切换。

版本2风险输出用 `sortino_target_downside` 替代旧 `sortino`；因子输出用新相关相似度/距离字段，旧 `redundancy` 不出现在版本2中。每个计算项附definition_id、formula、input_refs（确切结果revision/因子panel/数据snapshot身份）、input_basis（绝对/相对谁、成本前后）、parameters、availability/reason；同输入以新公式复算是新分析结果，不改旧ResultRevision。参数、输入引用与定义版本完整一致才可复算对照，持久化报告另存不可变报告身份。

首批rf、T仅接受同频有限标量，默认0并注明default来源；不自动转换年收益目标，不支持曲线输入时明确拒绝。年化系数优先取调用方参数，否则取本次配置，并返回来源；两者均为此次分析参数，不补写成历史运行事实。Sharpe/Sortino用sqrt(ppy)为明确约定，声明适用假设，不将重叠收益宣称为独立样本。输入缺测、现金流未解释或收益口径未知时不静默删除/补0；指标按适用性返回不可用。

#### T01-R风险接口切片（2026-09-27实施决定）

- 风险API增加 `analysis_version`、`risk_free_rate`、`target_return`；CLI对应 `--analysis-version`、`--risk-free-rate`、`--target-return`。标量单位是日频小数收益；版本1传入新增收益参数须拒绝，避免静默忽略。CLI旧版警告写stderr，stdout的JSON不变。
- v2返回 `schema_version=2`，每个item带确切 `revision_id`、`definitions`、原来源/行情性质与 `basis`；不持久化分析报告、不改历史revision。定义卡的 `input_refs` 包含run、revision、源metric/definition和已记录dataset身份；未知snapshot保持null，不把当前数据补为历史身份。
- 首批仅认可已登记的日频绝对收益：`native.qlib.return` + `native.qlib.report.return.v1` 为Qlib报告成本前收益；`platform.equity` + `platform.equity.account.v1` 推导成本后观测区间收益（不含首个权益点之前的收益）。这是定义映射，不是源数据真实性认证；来源分类另保留。两者均要求记录 `evidence.comparison.cashflow_policy=none`。权益首版仅支持正有限值；原始收益导致财富非正（r≤−1）时整组返回 `nonpositive_wealth_unsupported`，本批不支持破产后的绩效统计。
- 不因metric名称猜定义。未登记定义（包括已扣rf/基准超额）、未知现金流、缺测、非日频、无交易日历或样本不足，v2对应风险项统一null并给机器原因；不尝试另一序列掩盖优先源的缺口。已扣rf的序列本批不支持，因而不会再次扣rf。没有任何收益源同样返回不可用item；未知run仍404。当前拒绝显式null缺测，尚不能根据完整日历快照识别被完全省略的交易日，必须披露覆盖未核验限制。
- 当前v2复用其他风险量的既有估计量，并提供逐项公式/参数/不可用原因；本批只认证Sharpe/Sortino纠正与输入保护，不宣称所有统计量完成外部认证。回撤维持“首个观测权益起”的口径，不冒充含初始资金的完整回撤；CVaR尾部不足2点时为null，原因和值一致。
- 实施拆为T01-R（风险后端/API/CLI）、T01-F（因子/NW）、T01-U（UI显式v2与浏览器验收）。UI风险卡必须核对返回revision与页面选定revision；接口尚不支持历史选择时，版本不符应显示不可用及两端版本，不得混显最新风险值。三个切片已在3a8f52b8、50f9f366、58fdeeb3验证并关闭限定范围的T01/A34；旧服务响应不得作为纠正指标展示。其他统计缺陷不随此关闭。

手算样例（单期未年化，测试年化时统一乘sqrt(ppy)）：

| 输入（小数收益） | T | 下行偏差DD | Sortino |
| --- | --- | --- | --- |
| 连续20期均为−0.01 | 0 | 0.01 | −1 |
| 20期中5期−0.01、15期0 | 0 | 0.005 | −0.5 |
| 连续20期均为0 | 0.01 | 0.01 | −1 |
| 连续20期均为0.01 | 0 | 0 | 不可用：no_downside_deviation |

连续恒定负收益的Sharpe因标准差为0不可用，但Sortino有定义；两者不能共用“常数序列全部无效”的判断。T=0与T=0.01为不同分析参数，报告必须可区分。完整定义卡入口不意味着本轮已补全所有指标的估计量细节；首批只按A34冻结上述纠正项。

边界：结果里同时给出"未接入"清单（当前为交易日历外的分红再投资与真实交易成本细分），不得用估算替代。

最小样本：风险指标族要求 ≥20 个观测（尾部分位与年化对短样本敏感）；PSR/DSR 的 ≥10 与比较表的容差定义见 [验证口径](VALIDATION.md)，两处阈值回答不同问题，不共用。平台内所有非有限值在 DTO 边界统一转 `null`（`dto.json_safe`），lazy numpy 与容差只保留一份实现（`numeric.py`）。

每个R编号对应回归测试，涵盖正向可比较、缺失/冲突、跨时区、分页尾部极值、多轮失败、发布前脱敏、不同客户端源库不变。历史审查证据冻结不改写。规范S01—S05通过主合同和专题同步修订解决；S06以本字段表和逐项验收追踪收敛，完整机器Schema与CI仍保留原阶段缺口。
