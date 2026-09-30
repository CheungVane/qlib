# 项目 Spec：长期演进的核心锚点

**维护优先级：最高项目优先级。** 本目录定义需求、架构、数据语义、能力声明与验收。核心合同版本0.4.1；规范生效不等于功能交付。**当前状态、证据范围与下一步统一见[IMPLEMENTATION](IMPLEMENTATION.md)**，不要从历史审查恢复待办顺序。开发接手直接定位IMPLEMENTATION中的“当前TODO：执行队列与任务完成门”，领取G1-0及其后续切片。

## 阅读顺序

每次项目定制先读本页 → [治理](SPEC_GOVERNANCE.md) → [核心规范](WORKBENCH_SPEC.md) → [实施与验收](IMPLEMENTATION.md)，再读受影响专题。跨模块变更先核对[架构 §0](ARCHITECTURE.md#0-全项目主合同u31--arc13目标设计)的数据流、对象所有权、输入身份和上下游验收；来源或能力表达变化必须读来源合同。

## 生效合同索引

下表说明语义归属，不重复维护完成状态。新增模块沿现有合同填充；字段、公式和状态机只有一个权威定义。

| 范围 | 唯一入口与职责 |
| --- | --- |
| 治理与产品 | [SPEC_GOVERNANCE](SPEC_GOVERNANCE.md)：权威顺序、变更/归档和交付；[WORKBENCH_SPEC](WORKBENCH_SPEC.md)：需求ID、范围与跨域约束 |
| 整体架构 | [ARCHITECTURE](ARCHITECTURE.md)：完整数据流、目录/端口、对象所有权、时序与填充规则；[代码导航](../../extensions/workbench/quant_workbench/README.md)定位实现 |
| 共享实现合同 | [PHYSICAL_CONTRACT](PHYSICAL_CONTRACT.md)：DDL、事务和恢复；[COMMAND_CONTRACT](COMMAND_CONTRACT.md)：命令/查询DTO；[ARTIFACT_CONTRACT](ARTIFACT_CONTRACT.md)：产物封套、输入准备和worker交接 |
| 数据准备 | [DATA_SOURCES](DATA_SOURCES.md)：来源登记/限制/纠正验收；[DATA_PROCESSING](DATA_PROCESSING.md)：现有格式2标准和处理规程；[DATA_PIPELINE](DATA_PIPELINE.md)：多源流水线、CDF1、质量和格式3发布 |
| 研究输入与生命周期 | [HUMAN_RESEARCH](HUMAN_RESEARCH.md)：方向/假设/公式三入口和交接；[RESEARCH_LIFECYCLE](RESEARCH_LIFECYCLE.md)：实验/模型/策略版本、Run身份及RW01—06结果消费与过程追溯 |
| 计算与结果 | [FACTOR_ANALYSIS](FACTOR_ANALYSIS.md)：因子与统计；[VALIDATION](VALIDATION.md)：验证协议和证据；[RESULT_CONTRACT](RESULT_CONTRACT.md)：结果查询、风险指标与比较身份 |
| 执行 | [EXECUTION](EXECUTION.md)：Attempt状态机、执行保护、取消、预算与恢复 |
| 来源与引擎 | [PROVENANCE_AUDIT](PROVENANCE_AUDIT.md)：来源分类和能力声明规则；[RDAGENT_INTEGRATION](RDAGENT_INTEGRATION.md)：外部Agent适配边界 |
| 市场假设与后续边界 | [CN_A_SHARE_AUDIT](CN_A_SHARE_AUDIT.md)：规则来源、审计时点和账户假设；[配置说明](../../configs/cn/README.md)：操作入口，实际参数以configs/cn/profile.json为准；[TRADING_BOUNDARY](TRADING_BOUNDARY.md)：后续交易边界，非当前实盘能力或授权 |
| 状态与追溯 | [IMPLEMENTATION](IMPLEMENTATION.md)：当前状态、T工作包、A验收与未关闭缺口；[CHANGELOG](CHANGELOG.md)：逐批决定及兼容记录；[历史资料索引](archive/README.md)：旧审查/研究输入/被合并原文；[evidence](evidence/)：脱敏证据 |

数据来源、格式2处理、多源编排各自职责不同；DDL、DTO、产物合同也不合成一个巨型文档。结果消费已合并到研究生命周期，不再独立维护RESEARCH_WORKBENCH。

## 执行与交付底线

- 生效合同是目标；已实现、已验收、待设计冻结和历史观察分别表达。无证据不提升完成状态。
- 模拟/真实、原始记录/派生计算/模型意见、未支持/未知/零值必须区分；历史配置和环境不能用当前值补写。
- 先修订受影响规范再改语义；同步代码、必要测试、证据与限制，按GOV02提交并推送用户fork。
- 合并或归档不删除要求ID、原始证据或开放缺口。旧审查与聊天只供追溯；冲突先登记解决，不选较宽松条款。
