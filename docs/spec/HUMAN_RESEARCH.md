# 人参与的研究流水线：方向、假设与公式

状态：生效设计合同，版本1，2026-09-29；U30。**本批只设计，三个新入口、Agent能力适配、公式执行和持久化产物尚未实现。** 基线233dc589的真实基线分析不是本合同验收。本文负责研究输入/评议/交接/人工决策；生命周期归RESEARCH_LIFECYCLE，统计定义归FACTOR_ANALYSIS，执行保护归EXECUTION。

## 1. 三个独立入口，共用一个研究主题（HR01）

| 用户入口 | 最小输入 | Agent任务 | 正式输出 | 下一步 |
| --- | --- | --- | --- | --- |
| 方向猜想 | 一段方向描述；市场/频率继承明确可见的草稿默认值，可附资料 | 拆解机制、反例、已知证据、可检验性和数据需求，识别有区别的候选假设 | DirectionReview + 0..N个HypothesisProposalRevision | 选择候选→经济学假设入口 |
| 经济学假设 | 因果/行为机制或统计规律描述；预期方向/时域可由Agent建议，未知则指出 | 审查机制、反驳路径、可观测代理和时间信息；符合可检验条件后生成形式化因子候选 | HypothesisReview + 0..N个FactorFormulaProposalRevision | 选择/确认公式→因子公式入口，执行评估 |
| 因子公式 | 人写的公式文本或结构化表达式；数据快照与评价方案 | 解释/核查公式含义、输入字段、单位、时点与泄漏；解析为受限表达式并触发确定性计算/评价 | FormulaReview、FactorDefinitionRevision、FactorPanel、FactorEvaluationReport | 保存候选、对比/继续验证；后续可进入训练/回测 |

方向无需先写公式；有经济学假设无需先建方向；已有公式可直接评估。三个入口的“Agent分析”均要求至少一个已配置且支持相应能力的Agent；未配置时仍可保存/编辑和做本地语法预检，执行分析则明确阻塞，不假用固定模板冒充Agent。三者都是主题Experiment内的工作入口，不是互不相通的三份因子库。上游内容、评议、选择理由和确切版本引用随交接保留。没有前序产物时parent_refs为空，不能伪造方向/假设历史。

“经济学假设”是界面名称，不要求证明经济学理论；Agent给的是研究评议。对统计规律可明确标statistical_pattern，不能强行编造因果故事。首版仍限定价量/日频：例如“利润增长带来重估”可保存和评议，但若必需财务/PIT数据未接入，必须显示数据能力阻塞，不将价格动量偷偷替代财务假设。

## 2. 评议不等于验证（HR02）

禁止用单一“Agent说OK”作为通过所有阶段的标志。保留三个互相独立的结论：

- review_decision：ready_to_test / needs_clarification / not_supported / rejected，由Agent提供结构化理由，人工可追加意见；ready_to_test只表示机制/定义足够清楚且可设计检验。
- computability：computable / blocked / unknown，由平台按字段、语法、资源、历史时点与数据用途检查；Agent不得改写平台门禁。
- evaluation_outcome：completed / limited / unavailable及各统计项状态，由量化分析器给出；计算成功、p小、IC正均不自动等于假设成立。

评议最低结构：用户原意摘要、类型（因果机制/风险补偿/行为解释/统计规律）、作用对象、预期符号/持有期、机制链、替代解释与反例、证伪条件、所需数据/代理、已知与未知、证据来源及其时间。外部事实有引用才标有证据，未检索不能编参考文献；Agent自报置信分数不冒充校准概率。文献引用/建议、用户观点、平台检查和实算结果保持不同来源标签。

用户可在ready_to_test之外选择“仍作为探索性候选继续”，但必须说明理由并形成Decision记录；不能越过非法公式、缺必需字段、未来信息或执行资源硬门禁。rejected是该版本的评议结论，不删除输入；修改产生新版本可重评。

## 3. 版本化产物和交接（HR03）

新增的逻辑对象均遵循LIFE01的ID/schema_version/digest/created_at/provenance/parent_refs；DirectionReview/HypothesisReview/FormulaReview是ReviewArtifact的review_kind，不再建三份独立评议仓储：

| 对象 | 必需内容 |
| --- | --- |
| ResearchInputRevision | input_kind=direction/hypothesis/formula、用户原文、语言、假设类型、市场/频率、明确的范围/限制、可选附加资料摘要、输入作者、父产物版本引用 |
| ReviewArtifact | 输入版本、review_kind、decision、结构化理由/反例/数据需求、agent/model/prompt版本、工具/引用证据、actual_usage/unknown、产生的Run/Attempt |
| HypothesisProposalRevision | 可检验命题、预期符号/时域、变量/代理、机制与证伪方案、来源方向/评议、待确认项；生成后不可变 |
| FactorFormulaProposalRevision | 原假设引用、数学表达、受限表达式候选、变量/单位、回看/信号时刻/样本/缺失规则、方向、限制；未编译前不是可执行因子 |
| FactorDefinitionRevision | 通过校验的规范AST及operator_registry_version、数据字段契约、时间/单位推导、参数、预处理规则/拟合范围、代码/编译器身份、作者与来源；身份独立于某次数据面板 |
| FactorEvaluationReport | definition/panel/data/label/评价协议/参考因子集/验证与分析器版本、有效样本/排除、统计状态、搜索范围和限制；查询不能覆盖旧报告 |
| HumanDecision | actor=user、被评议产物确切版本、accept/revise/reject/defer/explore_anyway、理由、时间与后续引用；选择行为可自动记录accept，无需另填表 |

既有factor_id/panel_id及来源字段继续保留：新FactorDefinitionRevision是公式语义身份，panel绑定definition+snapshot+计算参数/编译器版本；同公式不同数据生成不同面板，不能用同名覆盖。旧手工/RD-Agent因子不补造definition或输入链，可显式“从旧面板创建研究草稿”，并显示历史来源不完整。

交接按钮“用作下一步输入”创建可编辑草稿，复制结构化字段并引用不可变上游版本；原文和来源可展开，用户修改只产生新的下游版本。父引用必须同主题或通过显式“复制到新主题”动作；接口检查对象存在、版本匹配和无循环。上游后来变更不会改写下游；UI提示“有新版，可复制重建”，不能自动替换。

## 4. 人工参与和自动推进（HR04）

默认是**辅助模式**：方向评议后最多展示3个有区别候选供选择；假设评议后提出最多3个公式候选供选择；公式入口一次“分析并评估”自动跑校验→面板→统计→报告。人主要负责研究意图与分支选择，机器负责格式化、计算和记录，不要求逐步确认每个技术动作。

可选**自动推进到因子报告**：用户在启动时明确选择，冻结目标、数据、评价协议、参考因子集及预算。默认工程限额为最多3个假设候选、每个最多3个公式、总计最多3个进入数值评价；这些是待实现产品默认，不是统计合理性保证。最多1轮澄清/改写建议，不自我无限循环；政策允许用户改小/改大但重新冻结版本。候选选择顺序基于预先声明的可检验性/数据可得性规则，不能偷看测试结果再挑。超数值预算的提案保留not_selected及原因，不当作计算失败，也不从搜索账本删除。

自动推进由工作台编排器在父Run成功、产物协议校验通过且ready_to_test/平台预检通过后创建**下一独立Run/Attempt**，不是在一个Attempt里无限运行Agent。每条自动边以(parent_artifact_revision, child_kind, workflow_revision)唯一键去重，其中parent_artifact_revision是被选候选自身的版本（H1/H2/F1），不能用包含多个候选的评议包ID合并它们；创建子Run与预留额度原子一致；重启核对账本，不能重复推进。方向→假设→公式为固定有向链，无回边。手工改写新输入不是自动修复回圈。

needs_clarification、分支互斥而无法按冻结规则选择、数据能力阻塞、预算不足或非法表达式时停止自动推进，主题显示“需要你处理”并给一个具体问题与可选操作。没有后台挂起进程等待用户：本次Attempt正常产出评议后结束；workflow_state=awaiting_input属于编排投影，不新增Attempt状态。用户回答创建新输入/定义/Run。用户关闭页面不取消任务；停止流水线先禁用后续边，再请求取消活动Attempt，确认规则沿用EXECUTION。

工作流总预算跨所有子Run/Attempt累积，包括显式重试和一次格式修复；EXEC13的policy_revision账本继续独立保留。更换子Attempt政策不重置工作流剩余额度；需要提高工作流总额度须用户显式创建预算修订并保留已用量，不能由Agent自行扩大。每步准入同时满足全局执行政策与工作流剩余额度。

自动推进只到研究报告，不自动保存“已验证策略”、启动真实训练/组合回测、下单或购买数据。Candidate标记不等于策略采用；LIFE04的人工策略决定仍生效。

## 5. Agent与平台计算的边界（HR05）

ResearchAgentPort按capability声明direction_review / hypothesis_review / formula_review / formula_proposal；RD-Agent及其他研究Agent通过适配器实现可支持的子集。不能把现有rdagent.factor.loop等同于四项已实现；对不支持的入口明确not_supported，可选择已配置的其它Agent，但不得静默替换模型/供应商。

请求只携带TaskEnvelope：task_kind、确切输入版本、市场/频率/约束、可用字段与语义、冻结数据/协议引用、候选上限、预算及允许工具、prompt/output_schema版本。默认不发送全部原始行情、密钥、文件系统路径或未选中的研究资料；需要外部检索能力时任务摘要明确显示。Agent返回结构化产物与可读解释，不能直接写平台库、替换快照或宣布统计值。

平台验证响应schema、引用、候选数量与语义后发布产物。格式错误保存脱敏失败证据并终结，不假定“文本可读”即成功；可在既定预算内最多一次结构纠正调用，计入实际调用账本，不追加研究分支。引用正文是研究材料，不是能修改工具权限/预算的指令。

IC、相关/正交、p/q、有效样本、缺口和质量门禁必须由确定性分析器产生，Agent负责解释有引用的输出，不接受Agent生成的数字覆盖实算值。工具参数/源码/模型版本与请求摘要留痕，模型实际版本不能用当前环境事后补写。计费无法测得显示unknown，调用次数与货币花费分开。

执行政策分能力预检：纯文字评议不要求Qlib或embedding；公式执行要求对应表达式引擎/数据/沙箱，只有具体Agent适配器使用embedding时才要求它。统一超时、原子预算、进程回收不可省略；相应SR01—03未修复前新自动链不得宣称可无人值守。

## 6. 公式语言、时间与可执行性（HR06）

公式入口保留用户数学原文，首版编译到受限DSL，不执行任意Python、eval、shell或Agent安装依赖。需一般代码的候选标unsupported_expression，可保存草稿但不运行。Agent提出的“等价改写”必须展示差异；辅助模式由用户选择，自动模式只接受冻结算子内的明确等价规范化，语义改写停止等待处理。

FactorDefinitionRevision必含：expression/AST、字段口径/单位/价格basis、频率、每证券时间轴、历史股票池引用规则、lookback、signal_available_rule、参数、输出单位、值缺失策略、预期符号/label_horizon、预处理版本。变量和算子有版本化注册表；不凭表达式字符串猜窗口或是否前视。

首版最低算子：add/sub/mul/div、abs/log、delay(x,n)、ts_mean(x,n)、ts_std(x,n)、cs_rank(x)。n为正整数；delay只能取过去n个交易日，禁止负移位/未来窗口；ts窗口包含t且要求完整n个适用观察，std用ddof=1且n≥2；未知字段在编译时拒绝；除0、log非正和输入缺失在对应输出格记null及原因，不使整份合法公式自动失败；超过已冻结质量门槛则计算产物不可供评价。不填0；cs_rank仅在t日历史池内有效值上算升序平均秩/n_valid，ties取平均，无样本null，1个样本值1但统计不足单列。截面运算不能混进未来成员或标签，字段available_at须不晚于信号决策时点；历史available_at未知时只允许明确exploratory_limited，不能认证PIT。

示例：`adjusted_close / delay(adjusted_close,20) - 1`在t日收盘后可计算；禁止在t日开盘做信号。当前研究标签t收盘→t+h收盘可用于预测关联描述，不能因信号收盘后才形成就宣称该价可成交；回测需单独选择下一可交易时点，沿用执行合同。标签不得作为公式输入，预测期末成分/状态不得反向删除当日因子。任何按样本估计的缩尾/标准化/正交回归参数都必须锁定拟合范围并遵守VALIDATION。

编译产物、输入分块、执行产物均有digest；计算运行在受资源限制的独立进程，网络默认关闭。最大回看/表达式深度/算子数/面板大小由版本化预算预检；缺少预算值拒绝，不能让任意嵌套算子耗尽主服务。超当前单面板400000格时先提示缩小范围，只有A38分块验收通过后才启用更大任务，不能静默截断。

## 7. 自动评价协议（HR07）

在任何数值试验前冻结EvaluationProtocolRevision：snapshot身份、历史池、样本和探索/验证/保留区间、标签定义/h列表/primary_horizon、候选数上限、预处理/缺失规则、参考因子集确切definition/panel版本、统计分析器版本、FDR族与账本范围、资源上限。有数据时冻结完整数值协议；只做无数据的文字评议时protocol_ref可为null，不能自动进入数值评价，选择数据后形成新工作流版本。默认工程模板可预填h=1/5/10且primary=1，用户必须在启动摘要看到它；不以算出的最优h作为主口径。

必备报告包含：字段与面板质量、覆盖/有效截面数、Pearson IC/Rank IC及其时序、NW显著性与可用性、ICIR、分位差/单调性代理、稳定性分段、与参考库的因子值相关/IC序列相关/共线性、正交诊断与增量诊断。公式和计算限制服从FACTOR_ANALYSIS；现有换手跨缺口、混用相关方法的正交增量、留一组合样本不同等缺陷未修前必须逐项标limited/unavailable，不因新入口接通就升级为有效证据。

“正交”必须声明**相对哪个参考集和在哪些样本/拟合范围**。未选参考集默认使用启动时已冻结、语义兼容的基线集合；不存在可用参考集则正交/增量unavailable/reference_set_missing，单因子IC仍可计算，不返回0。需要规模/行业中性化但数据仅为近似时给近似来源与限制；不能把去掉相关性说成经济学独立。修正后的正交计算版本与独立oracle验收见FACTOR_ANALYSIS新增合同；旧v2响应保留历史定义。

经济学假设入口在ready_to_test且公式/数据/预算通过后可以自动生成并评估公式，无需用户另开脚本；辅助模式先选择公式，自动模式按HR04继续。不能生成有效公式时仍交付假设评议和阻塞原因，因子/统计产物为空，不造“通过”指标。

TrialLedger保存该研究搜索范围下全部候选、原始方向/假设/公式分支、改写、失败/拒绝/评估/选择、参数、测试集访问、运行和报告。评价前登记分支；同公式同数据同协议复用可缓存计算但仍记录本次查看/选择，不伪装成独立证据。FDR族默认是**本次冻结工作流、主h、全部进入数值评价的唯一公式定义**；只对满足显著性前提的检验做BH并披露计划/进入/可检验/排除数，未完成分支时标family_incomplete，不给最终筛选结论。多h的探索表不借主h的q证明每个h。

新一轮改参/新公式产生新协议/试验集合，但持续披露同主题累计搜索与保留集访问；不能重置小族以声称全搜索已控制错误率。保留集在冻结选择前不发给Agent/优化器，访问即记录；若已用于选择，后续报告降为探索，不能保留“未使用测试集”的声明。首版默认只做探索性报告，严格样本外结论依赖T07/A36实际执行证据。

## 8. 页面与恢复（HR08）

研究中心顶部是“方向猜想 / 经济学假设 / 因子公式”三个入口，下面是同主题时间线与产物；旧引擎集成入口移到“高级/历史集成”，仍显示模拟性质，不删除已有记录。输入区分别给一句例子和解释：方向“短期拥挤交易会不会随后反转？”；假设“放量后收益反转可能来自短期流动性压力”；公式为HR06示例。示例不作为自动填入并运行的真实用户输入。

首屏显示原文/公式、数据、评价模板、Agent、自动推进开关与预算摘要；启动Agent评议必须选择Agent，数据/数值评价模板只在进入计算时必需；高级参数渐进展开。未选择数据时方向/假设可只做文字评议并生成草稿，数值计算明确blocked/data_required。用户不必读spec猜测“分析”是否启动付费调用：按钮旁显示将执行阶段、候选/调用/时间上限与不能估算的费用。

结果页先显示：Agent评议、平台可计算性、量化证据、下一步主操作；显著性数值不渲染成“假设成立”绿勾。任务失败与研究否定分开；生成0个候选也可是一份完整否定报告。澄清仅列阻塞问题；结果文本/公式可编辑成新版本，不修改原产物。复制链、输入差异、参考集、数据覆盖和完整过程均可展开。

同主题的方向→假设→公式→评价保留精确版本链接；网页刷新还原草稿（版本冲突提示）、工作流、活动Attempt与待处理项，旧报告不随当前选中数据更新。取消/重试使用既有语义；失败前已完成产物可浏览，继续时通过明确输入引用建立新Run，不称原Attempt断点续跑。

## 9. 命令与返回例（HR09）

以下为待实现目标，共用API/CLI用例服务，不占用现有只读`/v1/research`源快照路由：

| 接口 | 语义 |
| --- | --- |
| GET /v1/research-agent-capabilities | 已配置Agent及四类任务能力/可用性/预算需求；缺适配不提供假启动 |
| POST /v1/research-inputs | 保存ResearchInputRevision，携带experiment_id/input_kind/content/parent_refs/expected_revision及幂等键 |
| POST /v1/research-workflows | 固定链定义：input_revision、entry_kind、辅助/自动模式、data/protocol/参考集、agent/capability版本、预算、stop_after；返回workflow_id/revision/digest |
| POST /v1/research-workflows/{id}/start | 以确切workflow_revision/digest、idempotency_key启动首个Run/Attempt，202；重复200；无GET启动 |
| POST /v1/research-handoffs | 输入parent_artifact_revision、target_kind、selected_candidate_refs及人工决定，生成下一步草稿引用；不会偷偷执行 |
| GET /v1/research-workflows/{id} | 各Run/Attempt、固定边、预算、awaiting_input/blocked原因与产物引用 |
| GET /v1/research-artifacts/{id} | 不可变评议/候选/公式/报告；大面板只返回摘要和分页引用 |

例：从方向D1执行得到假设H1/H2，用户选择H2：handoff载荷{parent_artifact_revision:DR1,target_kind:hypothesis,selected_candidate_refs:[H2],decision:accept,idempotency_key:K2}，返回{input_revision:HInput1,experiment_id:E1,created:true}。对HInput1做假设任务产生公式F1；评估报告同时引用D1/H2/F1和快照S1。直接公式输入不要求D1/H2。

错误外壳沿用code/message/request_id/details：未知引用404，版本/幂等冲突409，结构字段错误422，能力缺失409/capability_unavailable，必需数据或预算不满足409/precondition_failed。非法公式可保存带diagnostics的草稿，但执行准入409/formula_not_executable；不创建计算Attempt。Agent运行后返回需澄清是业务产物，不是HTTP失败；输出无法通过schema校验则Attempt failed/agent_output_invalid。

## 10. 实施和验收（HR10）

先实现对象/端口/输出schema/输入交接与一次确定性公式评价，再接一个真实Agent能力适配，最后启用有预算的自动链；第一批不建设通用可视化DAG编辑器、任意代码市场或并发Agent协商体系。用户现在只授权设计，不在本批发模型请求、运行采集或公式，也不修改上游。

验收A44覆盖：三个入口独立可用且可串联、中文方向/否定/澄清/多候选、人改写版本、缺数据、非法/未来公式、同参考集正交oracle、所有候选账本、不可用指标、断网/超时/取消/恢复/重复推进、预算守恒、无代码/spec使用测试。没有真实Agent按结构化合同完成的产物和浏览器证据，不标记入口完成。

### 全项目交接约束（U31）

对象所有权与数据流统一依ARCHITECTURE §0；ResearchWorkflowService不得同时实现第二份Run管理或执行预算。因子报告向训练交接的是用户所选FactorDefinitionRevision/面板引用及所见样本记录，不能直接把报告数值当特征；数值计算和训练共用输入准备合同。用户查看全样本IC后选特征，相关区间须标已用于选择，不能再声明为未见测试。若希望严格验证，特征筛选须限制在允许的训练/验证区间，并在冻结方案下重新执行；保留集访问如实入账，不通过新建主题清除历史访问事实。
