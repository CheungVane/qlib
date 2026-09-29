# 一键数据准备流水线

状态：生效设计合同，版本1，2026-09-29；U29。**本批只设计，未实现接口、任务、自动拉取或UI。** 当前人工脚本处理与真实因子入口保留，基线233dc589；实际能力以IMPLEMENTATION为准。本文唯一负责采集编排、统一观察格式、多源合并、质量报告与一键交互；已有快照字节保护、FINV具体换算遵循[DATA_PROCESSING](DATA_PROCESSING.md)，来源事实遵循[DATA_SOURCES](DATA_SOURCES.md)。

## 1. 产品目标与边界（ING01）

用户在数据页选择或复用一份“数据方案”，点击“拉取并准备”，系统自动完成预检、采集、格式映射、清洗、合并、质量报告和合格快照发布。不是要求用户逐个运行脚本，也不是要求首批实现全部供应商。可选择多个**已接入**来源；新增来源按统一适配接口增量实现，不修改编排主流程。

首批为个人本地、A股日频、价量/状态/日历/历史成分/基准。财务修订、分钟、实时与交易不随本需求自动纳入。可登记未来组件能力，但不能给未实现来源显示可用按钮。既有FINV及BaoStock缓存优先做离线端到端验收，再按来源实际可访问性接入在线任务；历史BaoStock黑名单不是已恢复的证据，不做绕过或无限探测。

默认模板来自已验证场景，明确显示股票池、起止日期、来源、更新方式、预计资源和能力限制。首次配置凭据/数据根只需一次；之后同方案一键运行。日期/股票池/缺失容忍度均属版本化工程模板，不自动扩大到全市场。凭据只用服务端secret_ref，定义、产物、日志、API不含明文。定时刷新可后续实现，本批合同不要求后台定时器。

## 2. 定义、运行与发布分离（ING02）

| 对象 | 最低字段与语义 |
| --- | --- |
| DataPipelineDefinitionRevision | id/digest/schema_version、方案父ID、market/frequency/timezone、universe_ref、起止规则、组件字段、source_bindings、merge_policy_ref、cleaning_policy_ref、quality_policy_ref、输出规范版本、资源政策引用；不可变 |
| DataPreparationPlan | plan_id/digest、definition_revision、已解析的绝对日期/股票池/来源能力版本、base_snapshot_ref或null、冻结源发布版本或查询边界、预计分块/字节/行数（不可估则null）、限制与预检、expires_at；一次执行的精确计划 |
| Run / Attempt | 共用执行身份和确认终态；Run.workflow_kind=data_prepare，definition_ref为数据方案及确切plan；数据Run无需虚构研究Experiment，映射见ARCHITECTURE；每次重试新增Attempt |
| RawBatchManifest | 批次ID、source/adapter版本、脱敏请求摘要、源发布ID、requested/actual coverage、分页游标引用、local_completion/remote_completion及证据、请求次数、fetched_at、文件清单/SHA/大小；原始字节只追加 |
| NormalizedBatchManifest | raw引用、canonical_schema_version、字段/单位/证券/日历/价格解释版本、分区文件摘要、变换记录、逐字段来源映射及缺失原因 |
| QualityReport | 输入/计划/规则版本、检查项、计数分母、冲突/未知/失败、用途许可、发布结论、覆盖及来源证据分类；不可变、可单独浏览失败报告 |
| DatasetSnapshot | 已发布的冻结数据和解释/质量/合并/原料清单引用；新内容新身份；当前默认快照只是可变指针，不修改旧快照 |

plan是执行输入，不能将“截至最近完整交易日”留到执行时再解释：按已登记市场日历及来源覆盖解析为绝对日期并显示；不能将机器日期当最新可用日。无日历或目标边界不能确定时返回需要处理的预检原因。计划过期不得静默更新，UI刷新预览再由用户发起新命令。幂等重放先返回原Attempt，不因plan过期改变既有结果；过期计划的新准入返回409/plan_expired。重新计划建立新Run，旧失败Run仍可追溯，不静默续到不同输入。同一plan重试不得重新解析latest；源不能锁定版本时记录事实，并按§3冻结已取得批次。

## 3. 固定流程、幂等与失败（ING03）

固定阶段：`preflight → acquire → normalize → reconcile → validate → publish → report`。每阶段证据持久化在(attempt_id, stage_id)，不另造进程状态机；资源/取消/失联服从EXEC13及SR01—03修复门槛。GET只读，刷新页面不会触发采集、重试或发布。

1. 预检核对配置、来源能力、字段/单位、历史范围、磁盘、请求/墙钟预算及权限配置。任一必需能力不满足就拒绝启动；可选源不可用必须显示且按冻结策略处理：未执行的校验为not_checked，不将“无冲突”渲染成“已通过跨源校验”；必需字段只能按事先登记的fallback补齐。
2. acquire按证券/时间/源分页分块采集；原始字节和完成标志先落盘，再提交checkpoint。EOF/终止游标或明确范围证据才是完成，文件存在、HTTP200、非空、达到某个行数均不是完成证据。供应商空成功和请求失败分开。
3. normalize只做已登记的确定性格式/单位/缺失转换；reconcile按§5合并，保留冲突。validate总会尽可能生成报告，失败不丢原料。
4. publish是门禁，不因进程退出0而成功。必须完成必需获取、统一格式/身份和质量校验后，以临时目录→校验清单→原子发布登记的顺序执行；部分产物不可被目录或下游当published。
5. report汇总发布/未发布/有条件可用。发布回执和快照先持久化；若最终摘要生成失败，恢复依据回执补报告，不能撤销/重复发布已有快照。终态Attempt与publication_status分别展示。

最小状态投影：执行用queued/running/succeeded/failed/cancelled/interrupted；publication_status用not_attempted/blocked/published/reused；质量结论用pass/limited/fail。质量门禁拒绝时Attempt=failed、reason=quality_gate_failed，完整失败报告仍可用。limited只有满足已冻结受限用途许可才可发布；pass不等于官方认证或可实盘。

断点是**输入批次复用**，不是单Stage进程续跑：新Attempt仍从固定流程起点开始，复用经过摘要/请求范围/适配版本/源版本核验的已完成原料分块，后续重算；部分页不冒充完整分块。源无版本锁时，不拼接跨Attempt的未完成分块，重新获取该分块并保留旧版；checkpoint记录不稳定来源限制。未知旧缓存仅走“导入并审计原料”，remote_completion=unknown，不能伪装在线完整采集。定义的acquisition_mode区分online_fetch与registered_import：前者必需分块的请求完成性必须verified；后者必须有本地完整文件清单/字节审计，远端完成性unknown只能以exploratory_limited用途发布。这是两种明确准入政策，不能以自动降级掩盖在线失败。

相同幂等键+同一plan及载荷返回原Attempt，不重复扣预算；同键异载荷409。失败重试新键/新Attempt；修改来源/日期/策略为新定义/plan/Run。网络重试计请求预算，指数退避/Retry-After/有限次数由来源政策冻结；认证失败、禁止访问、黑名单立即停止该源，来源可用性记blocked（不是新增Attempt状态），不切换身份规避。达到请求/字节/时间上限保留原料和失败原因。原始分块可并行但源并发上限共享，不能各worker独立计数。

取消确认前维持占槽；取消发生在原子发布后保留快照与回执，不能把已发布事实改写成未发布。重启恢复先核对旧Attempt/发布回执，不能凭无HTTP轮询推断任务结束。

### 全量、增量和历史修订

方案必须声明update_mode=full/incremental与revision_policy。incremental引用确切base_snapshot；不能只按“最大日期+1”追加。对支持源版本/分区摘要的来源核对变动分区；不支持的来源按冻结回查窗口重新取得并对比，窗口外修订未检查则在报告中明确。源复权锚点、证券映射、日历/历史成员或字段解释变化时，重建受影响历史分区/全部依赖派生列，不能拼接两个复权基准。

新快照可引用旧快照中摘要验证且语义一致的不可变分区；新分区与旧分区共同进入新清单，不原地追加旧文件。报告新增/修订/撤回/未检查分区、旧→新缺失变化及受影响研究引用。更正历史数据只提示下游可重新研究，不自动改写旧报告。若无法判断哪些历史分区受影响，拒绝增量并建议创建full计划；不把“未检出差异”说成“历史未修订”。本阶段不要求自动重训或自动重算已有研究。

## 4. 统一观察格式 CDF1（ING04）

先有统一**语义格式**再做通用清洗，不强迫各供应商直接输出Qlib bin。目标持久化为按market/frequency/year分区的Parquet和版本化manifest；引擎bin/HDF属于下游物化产物。首批可用有同一schema/空值规则的CSV交换，但必须由manifest声明serialization，不按扩展名猜。大数据按分块流式处理，不把全历史装进浏览器/单次分析。

| 记录族 | 逻辑主键和最低字段 |
| --- | --- |
| calendar | (market, session_date)，时区与开闭市时刻/状态及依据；日频日期是当地交易日 |
| security / membership | 证券稳定instrument_id、source_symbol映射的有效区间；成分(universe_id, instrument_id, valid_from, valid_to)，闭区间解释；无交叉上市身份依据不合并 |
| bar | (instrument_id, frequency, session_date)，raw_open/raw_high/raw_low/raw_close、adjusted_open/adjusted_high/adjusted_low/adjusted_close、volume_shares、amount及currency、price_basis与adjustment_ref；每字段可空且有原因 |
| status | (instrument_id, session_date)，tradestatus/is_st/turnover_ratio等；状态未知为null，不当false；停牌与缺数据不同 |
| benchmark / adjustment | 通过同一稳定标识和解释引用登记；复权因子方向/基准/修订依据必须显式，不能只用字段名factor |

每条观察另有observed_at（对应市场日期/事件时刻）、available_at及availability_evidence、ingested_at、source_ref/raw_batch_ref、source_revision或unknown、transform_ref。**ingested_at是本次取得时间，不补成历史available_at。** 原始层允许不同来源/修订同键并存，规范快照只保留按冻结规则选定的字段值并引用所有候选；缺失原因以同键同字段旁表/紧凑字典存储，不需为每格复制长文本。

单位：raw_*价格为对应币种/股；adjusted_*须另声明是币种计价复权还是归一化指数单位及基准，不能通称币种/股。成交量为股，成交额为币种金额，turnover_ratio为比例（0.001586对应原turn_percent=0.1586）；日期ISO8601、时间戳UTC并保留市场时区。换算必须是适配器登记函数，原值和原单位可追溯。不是所有值都能转换成原价：归一化复权价单独保存为adjusted_*，带basis和基准；无法可靠还原的raw_*为null。跨证券价格水平比较必须有可比口径，不能用首值归一化价格代替原价。

CDF1不改写现有DATA_PROCESSING年度CSV列及schema2：旧turn_percent仍是百分数，旧FINV解释保持不变。新流水线输出DatasetSnapshot **schema3**（设计目标），纳入CDF1清单、原料/合并/规则/质量报告摘要，所有被引用清单均纳入传递内容校验；快照digest算法沿用规范JSON但以schema版本区分。质量报告引用发布前candidate_data_digest，最终快照再引用报告digest，避免报告和快照摘要循环依赖。v2→CDF1必须是显式无损转换任务并生成新身份；不能原地升级、改变旧reader分支或覆盖基线因子输入。schema3 reader/写入器未通过兼容测试前，不开启新快照的研究消费。

清洗允许：格式解析、编码/时区/单位转换、空白/源sentinel映射成null、完全相同重复记录折叠并计数、已确认代码映射、成员重叠区间归并。禁止默认填0、前向补价/状态、删除异常证券、仅留存活股票、均值插补、缩尾、标准化、以未来价/状态过滤当前因子行。其中均值插补、缩尾、标准化只能作为显式研究预处理，服从训练窗口与缺失标记合同；未来信息过滤当前特征/因子永远不允许，不能以研究预处理名义放行。冲突重复或不可解析非空数字不得按“空白”吞掉；隔离并阻断该必需分区发布。

## 5. 多源补充与冲突裁决（ING05）

source_bindings逐组件/字段组声明source_id、角色primary/supplement/validator、priority、必需性及允许的fallback。用户可以“一次选择全部已配置来源”，但系统按能力映射字段并标出无贡献来源，不做所有源盲目重复全量抓取。新供应商只实现其支持组件，能力不全不阻止其它已就绪组件运行，但必需数据缺口阻止整份目标快照发布。

- 选择顺序先匹配市场/频率/证券/时间/单位/价格基准/修订语义，再按冻结优先级选择；不同来源不按数值好看与否选取。不对冲突报价求均值。
- 默认OHLCV/amount及其复权解释为原子bar组：同日不跨源逐字段拼接；替补须该组整体兼容。状态/换手/成员可按各自明确字段策略补充，保留逐字段来源。若需求只需close，可另建显式close-only方案，不能对外称完整bar。
- 主源缺失可用明确允许且语义兼容的补源，报告fallback行数与覆盖；主源已有值且校验源超容差冲突，默认保留候选、阻断必需bar发布，不能伪装为主源缺失后覆盖。容差按字段、币种、精度与absolute/relative规则版本冻结；没有容差规则就不声称一致。
- 同源修订仅在明确as_of与真实available_at支持时选当时可用最新修订；历史时间不明保留unknown并限制用途。跨源同意且共用一个上游不算两份独立证据；报告upstream_group/独立性未知。
- “多源校验一致率”只对实际可比重叠样本计算，同时给对总预期样本的校验覆盖率。未覆盖、不可比、冲突各单列。不同复权锚点没有登记变换时为不可比，不以归一化后看似相关证明相同。

## 6. 质量报告与可信程度（ING06）

不输出一个未经校准的“正确概率”。首版UI的“可信程度”由四轴构成：**来源证据分类、结构/数值检查、跨源校验覆盖与一致性、历史可用时点完整性**，并有用途结论。source_evidence保留来源目录的source_class、原料溯源/发布清单校验状态及independence=independent/shared_upstream/unknown；没有证据不自动定高/低等级。historical_availability统计有依据的available_at覆盖，未知为unknown或partial，不把本次下载时间当完整证据。用户需要百分数的地方给可复算质量指标，不把覆盖率命名成置信度。后续若要综合评分，必须另冻结权重、校准样本与验证，当前不设权重。

对于已知历史池与日历：E为区间内应有的唯一(date, instrument_id)集合。每字段f在E上分为有效V、缺行A、存在行但值缺失N、非法/未解冲突I、明确不适用X，互斥且总和=|E|。D=|E|-X；missing_rate=(A+N)/D、invalid_rate=I/D、valid_rate=V/D。D=0时比率null，显示无适用样本。E无法确定时分母unknown，禁止报100%覆盖。

空白是缺失原因的一种：源空字符串/纯空格→blank；源null/NaN/sentinel分别记录；整行缺失为absent_row；覆盖外为outside_source_coverage（属于A的原因）；无法判断为unknown。不要把“空白数”再加到“缺失数”中。多字段缺失格与缺失行是不同分母；报告同时提供至少一必需字段缺失的唯一行数、各字段缺失格数及未受影响行数。有效零计入V。额外键、原始重复、折叠重复、非成员分别在E之外统计，不扩充覆盖分母。

必备报告：请求/实际覆盖日期、成员/证券数与日历依据、按年/证券/字段的缺失原因、原始/规范/隔离/重复数、已应用转换、异常检查/门禁阈值与结果、停牌/ST数量及未知状态、源请求完成性、跨源冲突及替补比例、数据新鲜度（目标交易日和实际末日）、修订/PIT限制、快照/报告/规则身份。摘要默认最多20条问题样例，详情分页与文件导出，不把百万行报告返回浏览器。

检查状态pass/warn/fail/not_checked/not_applicable；未知不归pass。逐用途给available/limited/blocked及理由，至少包含价格描述、探索性因子分析、需要PIT的训练验证、组合回测。硬错误（身份/结构/单位未知/未完成必需分块/未解冲突）不可由用户点“忽略”发布；缺测可按冻结阈值发布limited，但下游仍对实际所需字段/窗口再预检。首次工程模板至少要求每个必需字段存在有效观察V>0、历史日历/成员及必需文件可验证，否则阻断；允许观测缺测仅用于探索性分析，报告精确数量，不给PIT训练/回测许可；允许的缺失比例不是金融通用标准，用户改阈值会产生新政策版本。

## 7. UI和跨页衔接（ING07）

数据页顺序：当前研究数据（快照、覆盖、适用用途）→“拉取并准备”主按钮→最近任务/报告→高级方案与来源配置。默认不用理解adapter、registry、schema；来源能力、缺字段与凭据缺失转换成具体中文操作建议。切换来源要显示覆盖/字段/口径变化。

若plan所需输入尚未预览，点击主按钮先内联显示来源/范围/预检摘要；首次确认配置后“一键”指只需一次执行提交，不能无提示更换源或发起收费请求。开始后显示7步状态、当前处理分区与已完成/总量（未知总量就显示已处理数），停止按钮及冻结输入。离开页面任务继续；刷新还原同一Run；失败主操作为“查看原因/重试”，不自动无限重跑。成功页先回答“可用于什么、缺什么、与上版变化多少”，再展开数字。

新快照发布默认**不替换**正在研究的输入。完成页提供“设为新研究默认数据”和“用这份数据研究”两项；前者只改变新建草稿默认引用，已保存定义/运行不变。批量拉取/清洗一键完成，不强制逐阶段确认；遇到不可判定的冲突才停下等待修改方案。新研究显式引用快照ID/digest/报告；不能靠全局当前路径获得数据。

## 8. 接口、模块及验收出口（ING08）

端口与服务职责以[ARCHITECTURE](ARCHITECTURE.md)新增§9为准。下表描述用例；精确键名、必填/null、完整Ref与错误以[COMMAND_CONTRACT](COMMAND_CONTRACT.md)为唯一传输合同，物理载荷见[ARTIFACT_CONTRACT](ARTIFACT_CONTRACT.md)。新API为**待实现目标**，不声称现有服务已有路由：

| 接口 | 语义 |
| --- | --- |
| GET /v1/data-sources | 配置和能力目录；ready/limited/blocked/not_configured/not_implemented、组件/范围/限额/最近检查；无secret |
| POST /v1/data-pipeline-definitions | 保存数据方案版本，返回id/digest；同内容可复用，更新须expected_revision |
| POST /v1/data-preparation-plans | 输入definition_revision及base_snapshot_ref；返回冻结plan、预检与限制；无采集 |
| POST /v1/data-pipeline-runs | 输入plan_ref、idempotency_key、execution_policy_ref；创建Run/Attempt，202及Location；重放200 |
| GET /v1/data-pipeline-runs/{run_id} | 分阶段证据、Attempt、质量报告/快照引用；未发布明确null |
| GET /v1/data-quality-reports/{report_id} | 摘要及分页问题链接，冻结版本 |

取消/重试共用执行服务命令和错误外壳；定义保存/plan保存同样需要幂等键，内容冲突409，格式错误422、能力/门禁不满足409、未知身份404。CLI提供等价命令，调用同一用例服务；预览不产生采集Attempt。例：计划P1包含2025-01-02至2026-09-24，提交包含完整plan_ref与execution_policy_ref的命令（完整JSON见COMMAND_CONTRACT §5）；成功返回{run_id:R1,attempt_id:A1,status:queued}；若BAO必需且blocked，409/precondition_failed且checks包含source_unavailable，不创建Attempt、不扣采集预算。

验收A43见IMPLEMENTATION：多源/单位/冲突、分母手算、缺失与零、断点、并发幂等、取消/恢复、schema2保护和低负担UI。跨源与PIT未认证不会因流水线自动化而消失。

### 全项目消费边界（U31）

发布快照不自动开启训练/回测。数据流水线只证明报告所覆盖的组件与用途；下游根据自己的字段、时间和账户要求再次准入。全局身份及输入准备见ARCHITECTURE §0.3：CDF1统一使用DATA02的instrument_id，引擎物化是快照的派生产物，不能取代快照身份。新默认指针仅用于新草稿，不能改变已有公式、训练或回测的冻结引用。
