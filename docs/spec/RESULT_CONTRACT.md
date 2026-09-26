# 结果安全与查询合同（2026-09-26修订）

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

- `run.dataset.version` 记录**已物化数据快照的内容摘要**：对快照目录按相对路径排序后逐个文件取 SHA-256，再对这些摘要做一次 SHA-256（`basis=files_sha256`），并把摘要写入快照的 `content.json`；只登记文件数量与字节数，不写原始行情。
- 内容摘要与情景/配置指纹是两件事：GOV-CONFIG 仍然禁止用配置指纹代替数据内容版本。本机 CN 快照由固定种子与日历确定性生成，因此内容摘要稳定可复算。
- CN 适配器把执行/评估语义标识映射为 `evidence.comparison.evaluation_id = <情景指纹>`（同一指纹表示同一评估配置与样本范围），与 `execution_id` 并存；权益比较仍需 `initial_equity`、`cashflow_policy`、`price_basis`、`benchmark_id`。
- 历史 revision 不改写：缺少内容摘要或 `evaluation_id` 的旧对象继续保持不可排名状态，原因随比较结果显示；重跑或重新导入会产生新 revision。
- 数据目录正式接入后，`dataset.version` 应由供应商数据的内容摘要或版本号填充，本机的文件摘要机制仍然适用于本地快照与夹具。

## 比较模式

API/CLI支持mode=auto/equity/metric；auto对platform.equity选equity，其余选metric。并排浏览一直允许，未知/差异显示原因。尚不提供费用实验的自动排名，费用不同仍可并排查看。

| 必须已知且匹配 | equity | metric |
| --- | --- | --- |
| 数据集id+内容version、synthetic性质、非fixture | 是 | 是 |
| 单位、定义版本（unknown/unspecified不视为已知）、轴 | 是 | 是 |
| 完整有效观测及相同坐标、交易日日历/step_kind（按轴适用） | 是 | 是 |
| currency | 是 | 金额指标适用；其他指标不适用 |
| evidence.comparison.execution_id、initial_equity、cashflow_policy、price_basis、benchmark_id | 是；现金流首版只接受none | 不适用 |
| evidence.comparison.evaluation_id | 不适用 | 是，标识同一评估语义/样本口径 |

comparison为中立证据对象，不固定要求cn_scenario。CN适配器可把已核验的配置指纹映射execution_id；其他引擎可提供自己的等价证据。未知字段不能因两个null相等就通过。权益比较需实际初始资金，首个观测权益不充当初始资金。叠图至少要求已知且相同单位、轴、币种、日历/step_kind；排名另满足整套检查。默认模式不自动重基准化或转换币种。

## 修复验收

每个R编号对应回归测试，涵盖正向可比较、缺失/冲突、跨时区、分页尾部极值、多轮失败、发布前脱敏、不同客户端源库不变。历史审查证据冻结不改写。规范S01—S05通过主合同和专题同步修订解决；S06以本字段表和逐项验收追踪收敛，完整机器Schema与CI仍保留原阶段缺口。
