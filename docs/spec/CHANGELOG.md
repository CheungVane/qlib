# Spec 重要变更记录

本文件保留决策历史；当前合同见[入口](README.md)，维护流程见[治理规范](SPEC_GOVERNANCE.md)。以下既有工作为追溯登记，不冒充当时已具备的治理机制。

## 2026-09-30 — G1-1共享校验器与schema6→7迁移工具

- 来源：用户要求按spec开始实现；在G1-0映射基础上完成G1-1，基线`ff1f5e54`。关联U28/U31、T06、A35存储子项、A45-1；不关闭SR与A43—45父项。
- 实现：新增`domain/contracts.py`（严格JSON、标量、Ref/SnapshotRef/WriteMeta/Save/Parent/Check/ArtifactEnvelope及9类已冻结技术载荷；未注册类型`payload_schema_not_frozen`）、`maintenance.py`运维门面、`adapters/storage/migrations.py`与`qwb storage status|migrate|verify`。迁移按PHYSICAL §6.1执行一致性备份、打开Attempt逐项确认、指纹预检、单事务DDL、旧行/绑定守恒、外键与完整性核对、重复执行不重跑。
- 边界：`supported_schema`仍为6，启动路径不新增6→7迁移；schema7仓储/命令payload/原子准入/监督/发布仍归G1-2—5。业务命令载荷（research/data/model等）未注册前按契约拒绝，随各自入口实现注册；本轮只对临时隔离库运行。
- 验证：完整`workbench_gate.sh`退出0，Python 341项（7跳过、0失败）、JS 28项通过；专项`test_contracts.py`11项、`test_migrations.py`7项、`test_architecture.py`7项通过；CLI `status→migrate→verify`实跑返回6→7、外键/完整性ok、备份摘要记录。保留既有subprocess ResourceWarning与预期故障注入traceback。脱敏摘要见[证据](evidence/20260930-g1-migration-contracts.json)。
- 架构：CLI不直接导入存储适配器；新增`maintenance.py`运维组合根并纳入依赖门禁许可，cli/api仍禁止绕过服务边界（门禁反例保留）。

## 2026-09-30 — G1-0实施映射冻结（仅文档）

- 来源：用户要求按spec开始实现；先执行G1-0实施映射，基线`ff1f5e54`。影响U28/U31、T04/T06、A40/A41/A43—45，不改变已冻结DDL/DTO语义、不提升运行能力。
- 迁移：冻结[PHYSICAL §6.1](PHYSICAL_CONTRACT.md)维护命令`storage status|migrate|verify`、一致性备份、打开Attempt逐项确认、指纹预检、单事务迁移、守恒核对、重复执行与启动/维护分离；G1-1交付时`supported_schema=6`，只对隔离夹具执行6→7。
- 端口与校验：[ARCHITECTURE §9.4](ARCHITECTURE.md)把PHYSICAL §3能力逐项映射到端口/所有者/事务边界/落点，并冻结五层校验职责与反例到G1-1—5、G2的测试证据层级；共享校验器归`domain/contracts.py`，旧`domain/research.py`只作兼容。
- 监督：[EXECUTION EXEC13-B](EXECUTION.md)冻结单实例`qwb supervise`、`supervisor.lock`所有权、检查间隔5s/终止确认5s/25秒有界窗口、`describe_instance`/`confirm_stopped`身份协议与重启核对；SR01—03仍开放。[ARTIFACT §6](ARTIFACT_CONTRACT.md)补齐Parameter闭合形状并规定未注册payload拒绝。
- 兼容：没有新增HTTP路由、数据库迁移、引擎启动或managed生产注入；0—6遗留引导路径保持到G1-5，6→7只能由维护命令执行。
- 验证：文档链接/锚点、围栏、G1依赖与反例映射自查及`git diff --check`；本批为设计交付，运行验收归G1-1—5。

## 2026-09-30 — TODO执行交接补齐（仅文档）

- 来源：用户要求检查TODO能否指导执行者开发；核对基线4a150314。关联U28/U31、T04/T06/T09/T11/T12、SR01—05及A35/A40/A41/A43—45，不新增业务能力或关闭缺口。
- 发现：G1只有大目标，缺首片出口；T06等待T04/T05父项与共享底座依赖容易形成循环；旧表仍称共享DDL/DTO未补且允许自选字段/迁移号；T编号、G编号及代码README的顺序重复维护，UI被误读为必须等待整条后端链。
- 处理：IMPLEMENTATION新增唯一队列G1-0—5，区分可开始/待前片/待专属设计；逐片给输入、现有代码落点、交付、反例、依赖及不包含范围。G1-0只补维护命令/端口映射/监督协议/测试映射；共享存储不等待T04/T05父项全完成。后续SR与G2—G4保留适用前置，专业页面按垂直切片交付；T表只映射范围，代码README引用唯一队列。
- 兼容：仅修spec与代码导航文档；没有执行迁移、启动引擎、修改应用代码或改变能力状态。共享DDL、DTO、现有端口名和预算默认继续遵循已冻结合同，不因工程切片允许另选。
- 验证：42份Markdown的396条本地链接（含9条标题锚点）和围栏检查、G1的6片依赖无环、原96个T/A/SR编号保留、12处代码/测试落点核对及git diff --check通过；未重复运行代码门禁，上一批结果不作为本批新运行验收。

## 2026-09-30 — 全spec组织复审、合同合并与框架约束纠正

- 来源：用户要求review整个spec，识别废弃/相似文档及代码架构优化空间；基线4f11929a。影响GOV03、U09/RW01—06、U10、U28/U31、A40结构子项；没有降低业务验收门槛。
- 根目录35→22份Markdown；13份旧审查、研究输入及被合并入口移入archive，添加历史身份和承接索引，更新仓内引用。RW01—06逐条原文合入RESEARCH_LIFECYCLE §8；PROVENANCE_AUDIT保留持续来源规则、原审计快照另存；IMPLEMENTATION重复批次表归档。历史正文除链接/历史标记不改，evidence原文件原路径不变；未永久删除审查证据。
- 纠正当前与历史状态混用：共享DDL/DTO已设计冻结但未实施迁移；验证v2已有接口/界面但SR04仍开放；4f11929a为本次结构核对基线。README只维护职责导航，IMPLEMENTATION为当前状态入口。数据来源/处理/编排、DDL/DTO/产物各有独立职责，保留分开。
- 架构继续采用现有模块化单体；后续按G1补独立监督/事务仓储，再按G2提取专业页面，随引擎适配拆执行器。明确位置、依赖与验收见ARCHITECTURE §11，不另建平行基础设施。修复WorkflowPlan/Step接受list导致校验后可变的问题；旧生命周期类保持hash/接口兼容，仅纠正注释。
- 验证：完整workbench_gate退出0，Python328项（323通过、5跳过）、JS28项通过；文档文件/标题链接、围栏、RW原文和13份归档正文核查通过，git diff --check通过。脱敏摘要见[evidence/20260930-spec-structure-review.json](evidence/20260930-spec-structure-review.json)。未对统计公式逐项重新独立复算，未运行真实采集/训练/Agent/回测或用户库迁移，不关闭SR/A45父项。
- 兼容：仓内链接已更新；仓外旧文档URL需改到新入口或按Git历史追溯。不保留13份平行跳转stub以免重新污染活动目录。能力状态、运行数据及数据库schema不变。

## 2026-09-30 — U28/U31共享代码框架与边界门禁

- 用户明确授权按设计在代码中准备目录、模块、接口、交互/流程与角色。在现有分层内新增领域引用/准入/worker/来源计划/编译结果、7类固定计划、ResearchRunService/DataPipelineService/ResearchWorkflowService和中立能力端口；生产组合显式注入，未配置managed依赖时拒绝。
- 现有ExecutionService唯一负责准入；新路径固定重放→只读预检→单一事务端口admit→回执身份校验，不同步启动进程、不另造执行状态机。领域入口依赖门禁阻止绕过Run服务；保留旧门面/旧执行签名和统计口径。
- 补代码导航与后续填充顺序；14项隔离框架行为测试及6项架构检查通过，完整回归结果见IMPLEMENTATION。测试替身不作为SQL原子性/真实引擎证据；无用户数据库迁移、真实采集/训练/Agent或交易操作，不关闭SR及A43—45。

## 2026-09-29 — G0共享DDL、DTO、产物及恢复细化（仅spec）

- 用户明确要求沿全项目路线补齐DDL/DTO，不碰代码。核心合同0.4.1；新增PHYSICAL_CONTRACT、COMMAND_CONTRACT、ARTIFACT_CONTRACT，作为ARCHITECTURE的共享详细设计，不另造底座。
- 基于当前schema6冻结目标schema7：保留旧Run/revision/Attempt身份，外部绑定迁移；不可变版本、准入/预算/自动边、进程身份和发布回执共用事务。schema3以SQLite发布为权威，外部文件索引可恢复，旧schema2登记不改。
- 闭合字段定义新增命令/查询/错误/分页/CLI，明确旧幂等证据缺失、CAS、绑定冲突；补充数据/研究/准备/模型/预测产物载荷、摘要、反循环发布与工程限额。实际源/Agent能力如实保持未验；具体引擎参数schema与机器校验器仍是实施前/实施阶段工作。
- 在内存SQLite从现有schema6定义构造空库及含历史Run/revision/Attempt样例，执行文档DDL，核对身份保留、外键与integrity_check，故障注入确认DDL整体回滚；未访问实际数据库。JSON样例及文档链接/围栏/差异检查。仅docs/spec变更，不以设计验证宣称迁移或新能力已实现。

## 2026-09-29 — U31全项目数据流与架构一致性修订（仅spec）

- 用户要求从全项目审查，避免单点设计堆积。基线f2a8821a记录SYS01—07；核心规范0.4，ARCHITECTURE版本2新增全链主视图、对象唯一所有权、共享输入准备、身份分层、能力与页面上下文，原§3/§4/§9职责同步纠正。
- 修正RESULT_CONTRACT中物化/逻辑摘要/供应商版本混用及CDF1证券身份命名；生命周期明确managed/imported Run、外部绑定冲突和判别定义，保留历史ID/摘要。各专题引用同一主合同，不另造训练/因子标签和状态机。
- 实施按G0—G4整合现有T工作包，增加A45跨模块反例与实际用户旅程；SR01—04等未解决缺口仍开放。新增治理要求每次沿上下游核对影响；详细DDL/DTO/迁移仍需编码前设计门，不声称文档已可跳过详细设计直接实现全部能力。
- 验证：当前6项架构测试通过，文档相对文件链接/围栏与git diff --check检查；只修改docs/spec。未改应用代码、启动数据/Agent/训练/回测或迁移数据库；未提升功能验收状态。

## 2026-09-29 — U29/U30一键数据与人参与研究设计（仅spec）

- 用户要求先设计、不写代码。新增DATA_PIPELINE（ING01—08）与HUMAN_RESEARCH（HR01—10），核心合同升0.3；冻结三入口、版本产物/人工交接/有界自动推进、数据统一格式/多源冲突/质量分母及四轴可信程度。没有凭空定义“数据正确概率”。
- ARCHITECTURE §9明确服务/端口/适配器/前端归属、共享Run/Attempt、独立子任务、事务/恢复与物理设计门；补充CDF1/schema3兼容方向、受限公式与factor_orthogonal_v1目标。现有schema2、v1/v2统计与历史运行不改写。
- 同步数据处理/来源、生命周期、研究中心、RD-Agent、执行与来源声明边界；新增T11/T12和A43/A44。基线233dc589的新真实因子页不算这些能力已实现；原SR缺口保持开放。逻辑合同已冻结，物理DDL/完整DTO/数值限额须在首个编码里程碑前补齐。
- 验证仅审查文档一致性、相对链接和Git改动范围；未改代码、未跑训练/采集/Agent、未迁移数据，不重复运行无关代码测试。按GOV02单独提交推送spec。

## 2026-09-29 — 恢复UI资源并接入真实快照因子分析

- 用户要求恢复不可点击UI并切换真实数据；先登记ARCHITECTURE §8与FACTOR_ANALYSIS，随后实现冻结数据端口、组合根注入、三个基线的显式幂等导入与UI默认真实组。补充加载失败提示、无运行的数据目录、来源说明与极小概率显示；历史模拟记录不改写。
- 原因实测为旧服务资源白名单导致state.js 404。确认无活动Attempt并一致性备份后重启，按现有迁移schema4→6，所有前端模块返回200。真实v2 API/UI已使用processed_v1的401日×643历史成员面板；重复导入无新面板。没有启动训练、组合回测或新数据采集。
- 完整门禁313项Python（308通过、5跳过）及28项JS通过，退出0；保留既有ResourceWarning/预期故障注入日志说明。首轮旧测试对module脚本的断言失败，保留module启动器后完整复跑通过。浏览器键盘导航与统计展示通过；IAB自动点击落点偏移不当作完整鼠标验收。见[脱敏证据](evidence/20260929-real-factor-ui.json)与[截图](evidence/20260929-real-factor-ui.png)。
- 边界：只完成真实因子入口的ARC11/A40子项；其他分析路径、真实训练/自动挖掘闭环/组合回测、PIT认证与SR01—04仍待做。代码、spec、测试与脱敏证据一并提交，不含库、原始行情、运行日志或模型。

## 2026-09-28 — 免费数据实际处理、拒绝错误发布及研究纠正

- 先提交DP1规范`af4dd5d9`，随后实现格式2逐文件身份/验证字节、独立副本、全历史行情与缓存审计、年度规范物化及原子拒覆盖发布。补齐发布前状态覆盖及面板门禁；本批中间v2/v3保留，最终入口为`free_cn_20260924_processed_v1`。
- 最终冻结19,824文件；12年度面板1,426,359唯一成员行。独立oracle对原文件逐值核验12,581,224数值及256,007空值单元；缺行情36,628、缺状态286均保留，不插补、不假称停牌/历史采集完整。
- 研究三入口修正历史池、已复权口径、全窗口状态/价格、固定热身/成熟尾部、完整IC轴NW及跨折标签；原通用因子未知价格口径拒绝。缓存新采集要求请求身份、终态、返回范围、内容SHA；未调用数据供应商网络。
- 三条实际研究复算：421日/历史并集643只；12假设8过FDR、4过成本、交集0；4折选择0/2/4/3。保留旧报告，仅写新证据；不据此认证alpha或完成训练/回测。
- 完整门禁308 Python（303通过、5跳过）与26 JS通过；最后成员反例、缓存元信息与不可变解析缓存补充后31项数据专项通过。[验收摘要](evidence/20260928-data-processing.json)精确区分两次测试范围。API/CLI保留DATA04-A错误码，旧schema1可浏览但标limited；不自动迁移旧登记。
- FD限定路径与SR06本批复验完成；SR01—04及SR05通用分析ARC11仍开放，T06/T07账本和真实训练、源PIT/修订认证、组合回测未交付。没有提交原始数据、数据库、模型或运行日志。

## 2026-09-28 — DP1数据处理标准先行

用户授权“先把标准/步骤写入spec，再处理数据”。新增DATA_PROCESSING，冻结本批输入范围、逐文件哈希格式2、归档比对与独立副本、失败拒绝发布、年度规范面板、历史成员/标签完整窗口、保守单价日过滤、跨折标签和NW缺口规则。明确原料不覆盖、旧来源完成性unknown、不同口径不可猜测。架构/治理/实施索引同步；本检查点仅规范，数据与代码尚未处理，FD缺口不关闭。

## 2026-09-28 — 免费数据处理专项审查（仅spec与证据）

- 来源：用户要求检查免费来源数据是否处理正确；基线2d1e2985。只读现有归档/快照/缓存/物化，在临时目录构造反例；未调用行情供应商API、未改应用代码或生产数据。
- 确认FD01—07：期末成分回看历史、通用因子入口重复复权、物化重复行/有效期与header对齐缺口、训练标签使用测试价格、内容身份不覆盖实际组件、失败仍发布、缓存完成性缺失。详情与精确影响见[专项审查](archive/review-20260928-free-data.md)。SR05/SR06继续开放，旧研究/物化证据保留但收窄能力声明。
- 实测：421日研究窗口历史成员并集643只、脚本选期末500只；2025-01-02漏133个当日在册成员；两份360行物化样例各18个唯一键/1只股票；SH600000除权窗口直接close收益−0.4531%被通用读取器变成+4.2466%；坏bar夹具gate=false仍published并退出0。
- 正面证据：原archive SHA一致；1802历史标的10字段header范围一致；1791缓存4601971行结构扫描未见重复日期/非法枚举；期末500标的现有bar检查0问题。65项既有专项测试通过，隔离反例仍成立，不当作修复验收。[脱敏摘要](evidence/20260928-free-data-review.json)及两份可重跑观察脚本纳入spec，不提交原始日志/数据。
- 规范纠正：DATA_SOURCES 1.2新增§10逐项判定；修正百分比换手率公式、close首值归一化、原价例子乘除符号、单点精度外推和换源/发布/物化能力夸大。IMPLEMENTATION同步FD状态，并纠正上一批遗留D06架构状态描述。
- 限制：没有多源逐值全量核对、所有公司行动/历史修订认证，也未证明真实缓存被截断；通用读取器的复权反例不能外推所有现有UI结果受影响。业务修复、真实研究新版本复算与A16/A17/A30/A36/A37/A40完整验收均待后续。

## 2026-09-28 — U28代码框架与架构交接合同

- 来源：用户要求提前把关目录、模块、接口、定位、交互流程及时序，让后续实现者沿框架填充。先新增生效[ARCHITECTURE](ARCHITECTURE.md)，再落代码；登记U28并同步治理/导航和当前实施状态。
- 结构：实际调用下沉到结果、比较、因子、风险、验证、目录、待处理和执行8个服务；SQLite/对象存储移入adapters/storage；仓储、执行、观察与分析配置拆端口；bootstrap统一组装并提供显式目录设置。生命周期规则进入domain，新增三种固定流程设计对象（非运行器）。
- 前端：原生ES模块提取state与transport，保持URL/选择与过期读取语义；API白名单与打包包含新资源。页面和注册表未拆全；写操作仍保留原响应/错误处理，不自动重试。
- 护栏：自动检查核心/服务/适配层依赖方向、旧兼容转发、新平铺模块、仓储端口覆盖/签名；精确登记旧模块依赖。包含错误依赖反例，纳入已有workbench_gate。比较读取次数测试改为观察真实仓储边界，保留每个运行仅读取一次的断言。
- 验证：Python 298项（293通过、5跳过）、JS 26项通过；最终架构6项复跑通过；wheel构建、临时目录解包导入及空库API/三个JS资源检查通过；公开门面无方法删除，存储主体AST未改；spec链接和diff检查通过。[脱敏证据](evidence/20260928-architecture-framework.json)不含原始运行日志。既有可选集成跳过、进程ResourceWarning与依赖弃用警告保留，不声称真实容器专项复验。
- 兼容：旧Python入口为转发，CLI/API/数值版本保持；无数据库schema、历史对象或用户数据迁移。生产执行器和服务使用同一加载的policy，兼容直接构造仍有默认加载路径。
- 范围：A40仅结构子项；C2剩余编排已下沉。SR01—06、ARC11数据身份、部署恢复、T06/T07物理schema/命令及产物DTO/实际训练、C7页面/注册表和C10快慢测试分层仍待完成。旧分析profile、执行policy配置和传递IO依赖明确为过渡债务；没有新增研究/交易能力声明。

## 2026-09-27 — 个人训练/挖掘/回测工作流与UI审查

- 来源：用户要求从个人工作台角度检查能力缺口、低精力低负担及不读代码/spec的正确使用；本轮不考虑实盘，长期U25保留，明确使用目标登记为U27。
- 新增[产品审查](archive/review-20260927-personal-workflow.md)：3284a7a5静态核对及当前8765服务六页面只读走查；记录能力声明矛盾、运行版本不匹配、技术术语与创建/恢复路径缺口。当前运行服务提交未确认，不将运行中的旧响应当作最新代码无v2功能。
- 建议分为既有合同待落地与候选新增能力，提供三条工作流、页面结构、优先级及无需文档的候选用户验收；新页面/功能尚待设计冻结，未擅自将全部建议变成实施合同。
- 本批只改spec与审查记录，未修改UI/业务代码，未启动训练、Agent、数据更新或交易；未做真人可用性测试，文档验证不构成功能验收。

## 2026-09-27 — 监督修复交接合同补全（仅spec，未改业务代码）

- 来源：用户要求spec可独立交给他人实现，不依赖聊天、不留下行为猜测。上一批3979265e已记录问题，本批将剩余歧义的判定写入各权威专题，不把审查建议另立为第二套合同。
- 冻结：EXEC13-A明确独立监督、冻结政策、失联占槽及trial准入计费/幂等原子性；VALIDATION §2A.3A明确混用与请求错误的优先级、逐输入口径及revision配对；DATA04-A明确读时内容身份和拒绝错误；FACTOR_ANALYSIS §4.2A明确内部缺测与尾部未成熟标签、FDR不可用传播与复验范围。
- 交接：IMPLEMENTATION新增每个SR的权威依据、交付证据与关闭格式，区分可直接修复与T06/T07/T10后续详细设计门。核心规范移除“首个真实供应商待选”的过期状态，具体选择仍引用DEC01。
- 兼容/限制：新增判定要求实施时同步服务/DTO/API/CLI/测试，保持v1与旧revision/历史证据；物理迁移方案由实现批次先登记，不在本次虚构schema或验收。SR01—06保持开放；本批只检查文档一致性、链接和Git差异，不重跑无关业务测试。

## 2026-09-27 — 增量开发监督复审：重新打开T02/T04合同验收

- 来源：用户要求作为监督者和质量审查者，核对另一会话开发后的spec、架构、代码质量与设计一致性。基线`668506ed`，覆盖`6d59bc97..668506ed`的48个提交；本批只修改docs/spec下的规范状态、审查报告与脱敏反例，不修改业务代码。
- 发现：SR01无轮询时墙钟超时不强制；SR02失联释放槽位且宿主pid消失被当作容器取消完成；SR03并发试验预算可超支；SR04混合成本/日历仍产生DSR/PBO，DTO/错误响应不完整；SR05快照身份不校验被读取组件内容；SR06研究脚本重新删除缺IC计算NW。证据与修复出口见[监督审查](archive/review-20260927-supervision.md)。
- 状态纠正：撤回当前T02全线与T04/A41整体通过声明，仅重新打开被反例影响的验收；T01指定项、T03及容器/调用钩子限定证据保留。T05目录浏览已接入，但分析身份与内容保护未通过；T08-P历史数值保留、待纠正复验。既有CHANGELOG里的“通过”是当时结论，本条登记后续推翻依据，不重写历史。
- 可执行性：修正README、IMPLEMENTATION及执行/验证/生命周期/Agent/数据/因子专题的冲突状态；下一步先修SR01—06，再按原依赖推进。容器测试手册统一为从仓库根执行，未在本轮重跑容器验收。
- 验证：基线完整门禁Python292项（287通过、5跳过）、JS25项通过，退出码0；新增临时目录隔离反例仍复现上述缺口，输出无原始运行日志或用户数据。176个本地文档链接与差异格式检查通过，反例复跑输出一致。业务缺陷尚未修复，禁止把本批提交作为修复完成证据。

## 2026-09-27 — review 修正批次：容器路线的一致性、打包与文档可执行性

- 来源：用户要求"先review，看实现与 spec 是否无遗漏、能否指导下一个人继续"。review 以实际重跑为准，发现并修复下列问题。
- 代码缺陷①：`RDAgentExecutor.checks()` 仍把宿主 `.venv/bin/python` 当作**硬前置**（`required_for` 覆盖两个入口）。容器路线下它只影响宿主调试；不修的话，只有容器运行时的机器会被以错误理由拒绝准入。现改为 `required_for=[]` 的信息项。
- 代码缺陷②：`agent_max_calls` 的钩子目录 `extensions/workbench/hooks/` 不在打包范围内（`pyproject` 只收 `quant_workbench*`），独立安装时会缺文件。现把钩子移入包内 `quant_workbench/hooks/agent_budget/`（含 `__init__.py`，随包分发），执行器只把该目录挂到子进程 `PYTHONPATH`。
- 代码缺陷③：容器启动缺少"清理同名残留"步骤。确定性容器名在重试时复用，上一次崩溃留下的容器会让 `docker run` 直接以 125 失败（review 中真实复现）；现在 `start()` 先做一次 best-effort `docker rm -f`。另把重复的账本加载逻辑收敛为 `_agent_budget_module()`。
- 测试补充：新增"取消必须移除容器而不只是杀掉 docker 客户端"的容器用例（`QWB_CONTAINER_TESTS=1`），并确认容器测试可在重复运行后仍然通过。
- 文档过时更正（此前会误导下一位执行者）：`EXECUTION.md` 的"当前实现未覆盖…资源配额/并发上限…子进程内存/CPU硬限制"与"EXEC13 待实现"已按实况改写；`RESEARCH_LIFECYCLE.md` 的"当前保护未实现"改为已实现并指向证据；`RDAGENT_INTEGRATION.md` 的"资源上限未满足"与宿主 `.venv` 复现路径改写为两条路径（平台入口受政策约束、宿主直跑仅调试）；`IMPLEMENTATION.md` 的 U13 行更正；政策配置 `container.note` 与 `policy_summary().notes.memory` 里"RD-Agent 尚未接容器"的旧文案更正。
- 文档补充：`EXECUTION.md` 新增 §5.1"容器路线运行手册"（构建两个镜像、用 `docker inspect` 核验上限、如何跑容器用例与看入口前置），并在验收映射表加入 EXEC13/A41 行。
- 验证：门禁 `[gate] ok`（Python 290 项 + JS 25 项）；`QWB_CONTAINER_TESTS=1` 下容器与预算用例 19 项全通过；证据文件的 Attempt ID 由截断改为完整。
- review 追加发现（虚假能力风险）：调用计数依赖 `litellm.completion` 被包装，若上游改用其它客户端，账本会保持 0 次而界面仍显示 `calls_enforced=true`。现由探针在导入后端后**自检包装标记并拒绝运行**（`assert_budget_hook_installed`），并有离线用例覆盖"有预算无钩子即拒绝、无预算则放行"。
- review 追加（易误读语义）：EXEC13 明确写出"预算作用域是 `policy_revision`，改政策即额度从 0 重算、界面必须显示 scope"，避免下一位把额度重置读成数据被清零。本段为纯文档补充，未改动代码或运行时行为。

## 2026-09-27 — T04 第12片：RD-Agent 入口容器化，A41 通过

- 来源：用户"那就给他上容器吧"（承接 `agent_max_calls` 之后 T04 的最后一项）。
- 镜像：新增 `extensions/workbench/docker/rdagent-runner/Dockerfile` 与 `scripts/build_rdagent_runner_image.sh`，从 RD-Agent 上游 `requirements.txt` 构建 `qwb-rdagent-cpu:local`（本机基于 commit 484776c；RD-Agent 检出只挂载、**不打包**，所以上游代码变化无需重建镜像，只有依赖变化才需要）。首次构建因 `pip install /src` 的构建隔离环境缺 numpy 失败，改用 `--no-build-isolation` 后通过。
- 路由：整个 Attempt（驱动 + 因子代码）在一个容器内运行，`--memory/--memory-swap`=政策值、`--ulimit cpu=`=政策值；挂载 `/qwb/agent`(rw，检出与 `git_ignore_folder`)、`/qwb/repo`(ro)、`/qwb/hooks`(ro)、`/qwb/platform`(rw，研究快照与调用账本)、`~/.qlib`→`/root/.qlib`(ro，模板里的 `~` 路径原样可用)。
- 解耦：**仍未改上游源码**。三处适配都在平台自己的脚本里——①探针把 `QTDockerEnv` 换成同容器的 `LocalEnv`（本机 `.env` 设了 `MODEL_COSTEER_ENV_TYPE=docker`，否则 workspace 会去连嵌套 Docker，实测即失败于此）；②`FACTOR_COSTEER_PYTHON_BIN`/LocalEnv 的 `bin_path` 在容器内指向容器解释器；③Ollama 基址由平台改写为宿主可达地址（`host.lima.internal`，实测容器内可访问 bge-m3）。
- 顺带修：`run_rdagent_factor_smoke.py` 的研究快照出口硬编码 `<repo>/.data/workbench`，容器内 repo 只读即失败；新增 `QWB_PLATFORM_ROOT` 由平台注入并挂载。
- 缺陷修复：`container_environment()` 起初没传 `QWB_ATTEMPT_ID`，平台级 loop 的 `attempt_used` 记成 0、`blocked_by_this_attempt=false`；补上后归属正确。
- 验证（全部实机）：门禁 `[gate] ok`（Python 290 项 + JS 25 项）；平台 Attempt `231ed548`（`rdagent.factor.baseline`）在容器内退出 0、metric_count 19、quality `passed_checks`，运行中 `docker inspect` 读到 `Memory=MemorySwap=2147483648`、`Ulimits=cpu=3600:3600`；容器内真实 `--mode loop` 在 limit=3 时发 3 次即被拦（10 次内部重试全拒、`used=3` 无超支）；平台级 loop 在临时 limit=4 下以 `outcome.agent_budget.calls.status=budget_exhausted`（`used=4`、`attempt_used=4`、`blocked_by_this_attempt=true`）收尾，**策略随后已还原为 200**。证据见[agent-call-budget](evidence/20260927-agent-call-budget.json)（含 RD-Agent 容器段）。
- 出口：**A41 通过（本机）**，T04 完成；本项不含多任务调度/排队、远程执行器与按供应商计量的 token 核算。

## 2026-09-27 — T04 第11片：`agent_max_calls` 强制（不改 RD-Agent 源码）

- 来源：用户"`agent_max_calls` 没有强制，去做吧，如果需要修改 rd-agent 的源代码，记得尽量与原始架构解耦"。
- 机制（解耦）：新增仓库内 `extensions/workbench/hooks/agent_budget/`（仅标准库）：`sitecustomize.py` 是 Python 标准启动钩子，`qwb_agent_budget.py` 用 meta-path loader 在 `litellm` 被导入后包装 `completion`，**不改 RD-Agent 任何文件**。执行器只对 Agent Attempt 设置 `PYTHONPATH`+`QWB_AGENT_BUDGET_FILE/LIMIT/STRICT`，其余 Python 进程完全不受影响（有测试专门验证"无平台环境时不写账本"）。
- 计数与到限：每次调用前在 `flock` 保护的文件账本里原子预留；到限时**不发出调用**，抛 `AgentCallBudgetExhausted`（`qwb_agent_call_budget_exhausted`）。计数单位是"一次 `litellm.completion` 调用"（其内部重试不再细分），embedding 不计入。账本 `used` 单调不回退；服务在启动前用 durable count 续接、在终态把用量单调核对进 V5 `agent_budget` 表，因此取消/重启不清空。
- 暴露：`policy_summary().agent.calls_enforced` 由执行器能力得出（现为 true），`used.calls` 来自账本；`notes.memory` 的旧文案（"当前执行器为裸子进程"）改为容器实况；执行面板新增内存上限与"Agent 调用 used/max"。
- 顺带修：`scripts/prepare_cn_scenario.py` 编译 Agent 模板时**忽略 `QWB_RDAGENT_ROOT`**、硬编码兄弟目录，会静默编译到另一个（或不存在的）checkout；改为 `agent_root()` 优先读该环境变量。
- 验证：门禁 `[gate] ok`（Python 全套 + JS 25）。真实引擎：用 RD-Agent 自己的 venv 导入其 backend 后 `completion.__qwb_budget_wrapped__=True`；跑 `--mode loop` 并把 limit 设为 3，循环恰好发出 3 次调用后被拦，**其内部 10 次重试全部被拒、账本 `used=3` 无超支**，上游以 `Failed to create chat completion after 10 retries` 结束。另有 4 进程并发抢占只放出恰好 limit 个名额的测试。证据见[agent-call-budget](evidence/20260927-agent-call-budget.json)。
- 边界：平台级 RD-Agent Attempt 仍未跑通——该入口按内存必须项拒绝准入（`rdagent.limits`），故调用计数是在**真实引擎调用点**而非平台 Attempt 上验证的；A41 仍不通过，仅剩 RD-Agent 容器路由。

## 2026-09-27 — T04 第10片：Qlib 入口容器化，内存/CPU 硬上限落地

- 来源：用户对"为什么要设上限"给出结论"那要容器"，授权把 Qlib 执行器改走容器。
- 路由：`QlibCNExecutor` 现在用 `docker run --rm --init --name qwb-<executor>-<attempt>` 运行 `qrun`，镜像 `qwb-qlib-cpu:local`（colima `rdagent` 池 4 CPU / 5.77 GiB）。内存 = `--memory/--memory-swap`（cgroup 硬上限，禁用交换），CPU = `--ulimit cpu=<policy cpu_seconds>`（容器内 RLIMIT_CPU）；宿主侧不再对 docker 客户端注入 `ulimit -t`。取消时按确定性容器名 `docker rm -f` 兜底，避免只杀掉 docker 客户端而容器继续运行。
- 路径：挂载固定为 `/qwb/run`(rw)、`/qwb/data`(ro，行情快照)、`/qwb/src`(ro，平台代码，`-e PYTHONPATH` 保证挂载的检出优先于镜像内快照)；编译后的 `workflow.yaml` 在这些挂载路径下重写，**残留任何宿主绝对路径即拒绝执行**。实测发现 colima 对"宿主路径=容器路径"的同路径 bind 时好时坏，故不采用同路径挂载。
- 归一化：容器内 MLflow 记录的是 `/qwb/run/...`，宿主读不到；`outcome()` 在导入前把 Attempt 自身跟踪库（`experiments.artifact_location`、`runs.artifact_uri`）与 `meta.yaml` 的该前缀改回宿主工作目录，**只改路径字符串**，指标/参数/产物字节不动，并把它登记在 `outcome.container_paths_normalized`。
- 归类：退出码 137（cgroup OOM 或 RLIMIT_CPU 硬杀）在有强制上限时归 `failed/resource_limit`，不再读成 `nonzero_exit`；同时回收已结束的 Popen，减少门禁里的 ResourceWarning。这条修掉了此前"CPU 上限因 shell 先被终止而落 interrupted"的时序依赖。
- 政策：`configs/workbench/execution_policy.json` 改为 `enforce=["cpu","memory"]`、`memory_bytes=2GiB`（2 并发 × 2GiB < 池 5.77GiB），`note`/`container` 段说明机制与池约束；`container_flags()` 取代原先按 `cpu_seconds//3600` 猜 `--cpus` 的写法。
- 前置检查：Qlib 入口新增 `cn.container`（Docker 引擎为 linux、镜像存在、池内存 ≥ 强制上限），不再要求仓库 `.venv/bin/qrun`；编译改用工作台自身解释器（`sys.executable`，含 PyYAML）。RD-Agent 入口新增 `rdagent.limits`：其因子代码经 `scripts/run_rdagent_factor_smoke.py` 在宿主 `LocalEnv` 执行，上游 `DockerConf.mem_limit` 不适用于本仓库路径，故在 `memory` 属必须项期间**拒绝准入**，不再无上限运行。
- 验证：全程门禁 `[gate] ok`（Python 281 项含 5 项容器用例跳过、JS 25 项）；`QWB_CONTAINER_TESTS=1` 下 128MiB 上限分配 400MB → `failed/resource_limit`(137)、2 秒 CPU 上限忙循环 → `resource_limit`；真实容器化 Attempt `e7d21a20` 退出 0、质量 `passed_checks`（123 IC 日/122 交易日）、引擎证据含镜像 ID、EXEC12 自动入库 `imported`；另一次 Attempt（`7fbac10e`，归一化前）导入失败，补归一化后经 `qwb import-attempt` 重试 `imported`。证据见[container-route](evidence/20260927-container-route.json)与[container-limits](evidence/20260927-container-limits.json)。
- 边界：`agent_max_calls` 仍未强制（需执行器→平台回报通道）；RD-Agent 容器路由未做，**A41 仍不通过**。本批未改数据、指标与结果语义；`.data/workbench-container-check` 是本次验证用的独立平台库，未触碰演示库。

## 2026-09-27 — 更正：RD-Agent 入口的内存上限来自 RD-Agent 自身，不是本平台 policy

- 触发：用户问"qlib 为什么需要容器"，核对"（RD-Agent 执行器已走容器）"这句措辞时发现它会被读成"RD-Agent 入口已受平台内存上限约束"。
- 事实（代码与上游核对）：`RDAgentExecutor.command()` 启动的是**宿主 subprocess**（`RD-Agent/.venv/bin/python scripts/run_rdagent_factor_smoke.py`），平台不传 `--memory`/`--cpus`；该脚本进一步用 `LocalEnv` 覆盖 `get_factor_env`，**生成的因子代码就在宿主 RD-Agent venv 里跑**，所以上游 `rdagent/utils/env.py` 的 `DockerConf` 默认值（`mem_limit="48g"`、`cpu_count=None`）对本仓库这条路径**并不生效**——它只约束使用 DockerEnv 的其它场景。上一条把"容器由 RD-Agent 自建"写进结论是错的，见同日的《Qlib 入口容器化》一条。
- 更正：准确说法是**两个入口都没有受 policy 的 `memory_bytes`/`cpu_seconds` 约束**，缺的是平台侧容器路由（Qlib 与 RD-Agent 都要接）；容器能强制内存上限的结论（`docker run --memory=…` 实测 OOM）仍然成立，那是"平台有能力"，不是"执行器已用上"。
- 影响：A41 的"内存/CPU 硬上限由执行器可核验"对两个入口都未落地，T04 剩余范围不因此缩小；`enforce=["cpu"]` 保持不变。

## 2026-09-27 — 数据源文档状态刷新：删除与实现记录冲突的"未开始/未验证"

- 来源：用户询问"spec中还记录有哪些现在要做的事"，核对时发现 [DATA_SOURCES](DATA_SOURCES.md) 的 §6/§7/§8/§9 停留在下载前口径，与同文件 §3/§6 的实现记录及 IMPLEMENTATION 的 T05/A16/A17 行直接矛盾。
- 更正：①快照状态由"已落盘但尚未接入数据目录"改为"已发布进注册表并可由适配器读取，但**分析路径仍按当前CN配置解析**"；②§7"仍未完成"改为实际剩余四项（分析路径按snapshot解析、真实财务修订源与真实bar范围门禁、全量面板同种子复跑、特征/标签管线与非csi500扩展）；③§8 去掉已完成的"字段单位未解包核验"与已由 DEC01 回答的"股票池/区间/频率未定"，保留真正未核实项（`$factor` 生成规则、跨年代口径、数据许可条款）；④§9 四行状态由"未开始"改为与 IMPLEMENTATION 一致的"接近完成/部分证据/未开始（DEC01已定）"，并把主源获取命令标注为"已于2026-09-27执行一次"。
- 范围：仅文档更正，无代码、数据、接口与验收状态变化；A16/A17/A40/T05 仍未通过，不因此升级任何阶段。

## 2026-09-27 — 测试沙箱硬边界：executor 不再写进真实 checkout

- 来源：用户确认删除仓库根目录的测试残留 `runs/`（`stub_sleep`、`rdagent_factor_baseline` 的工作目录，实测 1.1 MB）。
- 根因（已复现）：`test_execution_policy.py` 的两组用例把**裸临时目录**交给 `StubExecutor`，而 `discover_project_root(explicit)` 在校验失败后继续扫描 `here.parents`，回退到已安装的 checkout——于是 stub 的 workspace 落进仓库根 `runs/`。删掉目录只是清掉表象，测试会再造一次。
- 修复：①`cn_market.discover_project_root(explicit)` 改为**显式根权威**：不像 checkout（缺 `configs/cn/profile.json` 或 `scripts/`）即抛 `ProjectRootNotFound`，不再静默回退；②新增 `tests/sandbox.py::isolated_repo_root()`（打标记并断言解析回自身），`test_execution.py` 与 `test_execution_policy.py` 三处裸 `Path(tmp.name)` 改用该助手；③`.gitignore` 增加 `runs/` 作为兜底。
- 测试：新增 `tests/test_sandbox_isolation.py` 3 项（沙箱内 workspace 不外泄、未标记显式根被拒、真实 checkout 仍被接受且 `runs/` 仍被忽略）；全量门禁 `[gate] ok`（Python 272 项含 2 项环境跳过、JS 25 项）；复跑原先泄漏的两组用例后仓库根不再出现 `runs/`。
- 边界：无显式参数时 `discover_project_root()` 仍按"`QWB_REPO_ROOT`→包位置→cwd→包根"解析，生产路径未改；本次不涉及数据、指标、能力声明。
- 清理：`runs/` 已移入废纸篓；未提交任何测试残留。

## 2026-09-27 — BaoStock 访问规则写入代码：单只顺序 + 强制 sleep + 遇封即停

- 来源：用户明确要求"baostock 适合单只循环，必须加 sleep，禁止多线程并发。这个写到代码里，然后同步到spec"。
- 实现：`scripts/fetch_csi500_turnover.py` 重写为**纯顺序**抓取——删除 `ProcessPoolExecutor`/`--workers` 及全部并发原语，改为单进程逐只循环；`--sleep` 默认0.5s且**下限强制**（<0.5含0在联网前退出码2）；查询间必 sleep；源端返回 `10001011`/含"黑名单"时**立即停止**并保留已写文件（退出码3），不循环重试；保留父进程预检、断点续跑与 `unsupported_symbols.json`。`scripts/probe_data_sources.py` 的BaoStock探测也在每次查询间暂停1秒。
- 测试：新增 `test_fetch_pacing.py` 3项（离线：sleep下限在联网前拒绝、`--help`无`--workers`、源码不含`concurrent.futures`/`multiprocessing`/`ThreadPool`等并发原语）。
- spec：DATA_SOURCES 新增"BaoStock 访问规则（硬约束）"四条，并更新 §7 重建手册的采集命令（去掉`--workers`、写明sleep下限与遇封即停）。

## 2026-09-27 — A40 修正：legacy 登记不得混入快照列表

- 来源：用真实注册表做A40端到端演示时发现——`list_snapshots()` 的 `*.json` 通配把 `*.legacy.json` 也当成快照列出，于是 `cn_data.legacy`/`qwb_cn_current.legacy` 会以"不可读快照"出现在接口与页面上。
- 修复：`data_directory.list_snapshots()` 显式排除 `*.legacy.json`；legacy 登记仍由 `list_legacy()` 单独提供。新增1项测试（同一注册表中 legacy 与快照并存时，列表只含快照）。
- 复验：真实注册表下 `data_snapshots()` 现在只返回 `free_cn_20260924`（日历2000-01-04→2026-09-24、6479天、reproducible、摘要不含绝对路径）；全量门禁 `[gate] ok`。

## 2026-09-27 — A40 第三步：已登记快照显示到数据页

- 来源：用户授权20:30前自主推进（也承接此前"接到界面"的方向）。
- 实现：数据页新增"已登记数据快照"卡片——逐快照显示ID与内容摘要前缀、日历覆盖（起止与天数）、组件清单、可复现性状态与原因；**未配置数据目录时如实显示原因**（不伪装成空列表），接口不可达时降级为 `interface_unavailable`；原"当前研究的数据证据"卡片保留在下方。
- 测试：新增1项JS（正常渲染各字段、未配置目录提示），JS套件25项全通过；全量门禁 `[gate] ok`。
- 边界：分析路径仍读当前CN配置，页面只是**展示**已登记快照；A40/ARC11仍未通过。

## 2026-09-27 — A40 第二步：快照目录接入 service/API/CLI

- 来源：用户授权20:30前自主推进。
- 实现：`WorkbenchService` 增加可选 `data_directory` 与只读方法 `data_snapshots()`/`data_snapshot(id)`；`build_service()` 在 `QWB_DATA_ROOT`（默认 `~/.qlib/qlib_data`）下存在 `_registry` 时自动装配 `LocalDataDirectory`；新增 API `GET /v1/data-snapshots`、`GET /v1/data-snapshots/{id}`（未知快照返回**404**，未配置目录返回 `available=false` 与原因，不伪装成功）与 CLI `qwb data-snapshots` / `qwb data-snapshot <id>`。
- 语义：未知或不可读快照按"不可用（404）"处理，而不是"请求非法（400）"——测试覆盖该差异。
- 测试：新增3项（service+API列表/详情/404、未配置目录如实报不可用、CLI两条命令）；全量门禁 `[gate] ok`（含API03新路由与OpenAPI覆盖检查）。
- 边界：**分析路径仍读当前CN配置**，尚未改为按snapshot解析，故A40与ARC11仍不通过；适配器只提供读取与摘要。

## 2026-09-27 — A40 第一步：本地数据目录适配器

- 来源：用户授权20:30前自主推进；T05 剩余项之一为"把 data_directory 接入应用层"（ARC11/A40）。
- 实现：新增 `adapters/local_data_directory.py`（`LocalDataDirectory`）——按**快照ID+配置的数据根**解析，提供 `available()/list_snapshots()/load()/summary()/validate()`；`summary()` 只暴露身份、组件覆盖、可复现性、限制与日历范围，**不回传绝对路径**；快照不可读时给出 `unreadable_reason` 而非假装可读；未知快照与空注册表 fail-closed。
- 定位：**适配器与摘要层**。应用服务/API/CLI 的装配（把分析路径从"当前CN配置"切到"按snapshot定位"）仍未做，A40 与 ARC11 均未通过。
- 测试：新增3项（列表与摘要、绝对路径不泄漏、未知/空注册表拒绝、不可读快照如实报告）；全量门禁 `[gate] ok`。

## 2026-09-27 — T06 接口草案（对象、身份与复用规则）

- 来源：用户授权20:30前自主推进。T06 前置为T04/T05（均未完成），但 spec 明确"接口草案可先行"，故只冻结接口、不落库、不接API。
- 实现：新增 `research_lifecycle.py`——①`ExperimentDefinitionRevision.build()` 要求11项研究身份字段齐全且ID为不透明安全标识，内容摘要由身份字段（不含标签/名称）计算；②`ModelArtifactVersion.accepts()` 要求特征/预处理/标签契约完全匹配才允许复用（"文件能加载"不算兼容）；③`StrategyVersion.build()` 允许无模型的规则策略；④`classify_repeat()` 冻结"同有效输入=重试 / 输入变化=新定义版本"的判定；⑤`is_retry_allowed()` 要求 interrupted 必须先确认旧进程结束；⑥`TrialLedgerEntry` 保留失败候选、同一有效配置的多次Attempt归同一trial、记录最终测试集访问并给出账本快照摘要。
- 定位：**接口草案**。物理schema、仓储、API、TrialLedger持久化与A35验收均未实现，T06不得据此标完成。
- 测试：新增8项（摘要稳定性与身份敏感性、缺字段/非法ID拒绝、重复分类、重试确认、复用契约不匹配、规则策略、账本重试归并与访问记录、未知状态拒绝）；全量门禁 `[gate] ok`。

## 2026-09-27 — T05 覆盖门禁：区间与数据一致性检查

- 来源：用户授权20:30前自主推进；接着补 T05 的"真实bar覆盖范围门禁"。
- 实现：`data_directory.coverage_report(reader, instruments, as_of)` 逐标的比较"instruments区间声明的结束日"与"feature序列实际末日"，输出`truncated/missing/ok`与样本；语义明确写为**标记而非结论**——真实退市或吸收合并会让交易早于指数剔除，仍在上市却提前断档才是数据缺口；并声明它**不能替代**`free_sources.survivorship_report`的"过期vs退市"判定。
- 实测（见[覆盖门禁证据](evidence/20260927-coverage-gate.json)）：中证500区间文件22,503行中15行数据短于区间声明（抽查为真实退市/合并，如SH600068葛洲坝2021-09停牌、指数2021-12剔除）；全市场`all.txt`6,161行**0处不一致**。北交所缺口之所以不被该门禁捕获，是因为其instruments区间的结束日已被数据本身覆盖（需要"是否仍在上市"的判定，即survivorship_report的职责）——此点已写入证据解读。
- 测试：新增1项（区间长于序列→truncated并给出实际末日与提示）；全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第9片：resource_limit 归类的可实现部分（含平台限制）

- 来源：用户授权20:30前自主推进。
- 实现：包装脚本在声明CPU上限时增加 `trap ... XCPU`，被上限杀时尝试写专用标记 `resource_limit`；`poll()` 识别两种证据——标记字面量 `resource_limit`，或退出码 **152**（128+SIGXCPU，即子进程自身被CPU上限终止）——并归类为 `state=failed`、`error_code=resource_limit`；无标记时仍按 `process_lost_without_exit_evidence`/interrupted 处理，不猜测。
- 平台实测（如实记录）：本机 `/bin/sh` 包装器在能执行 `trap` 之前就被终止，标记未落盘，因此该场景**仍落 interrupted**；但"子进程被SIGXCPU杀、shell存活写入152"的路径与"trap成功"的路径都能给出 `failed/resource_limit`。A41的"被上限终止记录 failed/resource_limit 及证据"在本机**只能部分满足**，取决于信号时序；该限制已写入测试注释。
- 测试：CPU上限强制测试改为接受两条路径并分别校验（failed ⇒ 必须带 `resource_limit` 标记与错误码；interrupted ⇒ 必须无标记），另保留"无上限时不注入`ulimit`"。全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第8片：槽位的单事务预留

- 来源：用户授权20:30前自主推进。
- 实现：`storage_attempts.create_attempt(..., max_concurrent=)` 在**同一个 `BEGIN IMMEDIATE` 写事务内**统计未终态Attempt，超限即抛 `StorageCapacityExceeded`（事务回滚，不产生记录）；`ExecutionService.submit()` 传入 `policy.max_concurrent` 并把该异常映射为 `CapacityExceeded`(409)。保留提交前的快速预检（避免满槽时白跑 preflight），但**权威判定在事务内**。
- 意义：此前是"插入前查数量"，并发提交存在两个请求都拿到最后一个槽的窗口；现在槽位判定与插入在同一写事务，窗口消除（EXEC13"并发槽在持久化事务中预留"）。单进程下 `BEGIN IMMEDIATE` 会串行化写者，语义成立。
- 测试：并发准入5项保持通过（含槽满拒绝不创建Attempt、取消释放、幂等重放不占槽）；全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第7片：持久化 deadline 与 policy_revision（schema V6）

- 来源：用户授权在20:30前自主推进并实时刷新spec。
- 实现：schema 升到 **V6**，`attempts` 新增 `deadline_at`、`policy_revision` 两列；`create_attempt` 写入政策revision，`submit()` 在**确认启动时**按 `started_at + policy.timeout_seconds` 计算并落盘 deadline；`enforce_timeouts()` 优先读**持久化的 deadline**，仅对缺该列的旧记录回退到运行时推导。
- 语义修正：EXEC13 要求"任务超时从确认启动计时，持久化deadline"，此前是运行时推导（改政策会移动历史任务的截止时间），现已落盘冻结；测试验证"提交后更换政策不会移动已冻结的deadline"。
- 测试：新增1项（deadline/policy_revision落盘、差额≈政策超时、改政策后仍按原deadline判超时），共20项政策测试；全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第6片：执行政策与预算接到界面

- 来源：用户"去接到界面吧"。
- 实现：`ExecutionService.policy_summary()` 汇总冻结政策与用量，经 `/v1/executions/catalog` 返回（并加入 `capabilities()`）；字段含 revision、来源、并发、超时、宽限、CPU秒、内存字节、`enforce`、**未强制项**、Agent试验上限/已用/scope 与 `calls_enforced=false`。UI 执行面板新增"执行政策"区，逐项展示并**显式写出未强制的能力**（"未强制：内存硬上限（需容器路径）；Agent 调用次数（子进程无法回报调用数）"），同时说明"槽满或达试验上限时拒绝准入且不创建 Attempt，超期任务由状态核对路径终止"。
- 契约：`/v1/executions/catalog` 顶层键新增 `policy`，按 API03 要求**与键冻结测试同一提交**更新（非静默漂移）。
- 测试：新增1项JS（政策区渲染、未强制项与不可用政策提示）与1项Python（`policy_summary` 报告上限与用量）；全量门禁 `[gate] ok`（Python 250项、JS 24项）。
- 缺口（如实记录）：`agent_max_calls` 仍未强制（需执行器→平台回报通道）；Qlib执行器未走容器；`failed/resource_limit`归类、deadline持久化、槽位单事务预留仍待做。**A41不通过**。

## 2026-09-27 — T04 第5片：Agent 试验预算预留

- 来源：用户"接着来吧"。
- 实现：schema 升到 **V5**，新增 `agent_budget(policy_revision, scope, kind, used, updated_at)`；`reserve_agent_budget()` 在**单事务内**先读后写——超限时直接返回不允许且**不写账本**，允许时 `used += amount` 并落盘（键为策略revision+scope+kind，故换政策即新账本）。`ExecutionService.submit()` 对 `rdagent.*` 入口在启动前预留 1 次 trial；到限抛 `BudgetExhausted`（code=`budget_exhausted`、409），**不创建 Attempt**。
- 语义：重试**再次计数**（每次提交都预留）；**取消与重启都不清空**账本——测试覆盖"取消后仍被拒"与"新服务实例读同一仓库仍被拒"；非Agent入口不消耗trial额度。
- 测试：新增2项，共18项政策测试；全量门禁 `[gate] ok`（含V5迁移）。
- 缺口（如实记录）：**`agent_max_calls` 未强制**——子进程无法把 LLM 调用数回报给平台，需要执行器→平台的计数通道，故EXEC13"Agent到限阻止下一调用"只完成了trial这一半；预算余额尚未在界面展示；容器路由、`failed/resource_limit`归类、deadline持久化、槽位单事务预留仍待做。**A41不通过**。

## 2026-09-27 — T04 第4片：超时终止监督

- 来源：用户"可以。记得回写spec"。
- 实现：`ExecutionService.enforce_timeouts(now=None)` —— 按 `started_at + policy.timeout_seconds` 判定超期，超期调用既有终止流程（SIGTERM→宽限→SIGKILL）；**确认结束才落 `failed` + `error_code=timeout`**，未确认则保留 `interrupted` 并记 `timeout_unconfirmed` 与超时请求（写入`cancel_requested_at`），不假报终止；完成证据早于 deadline 的任务不被追溯改写。
- 触发方式与理由：本版本无调度器，监督挂在状态核对路径——`list()`/`get()` 都会先 `reconcile()`，故读取时即可收敛超期任务；该路径**只结束超期任务，不创建新任务**，符合"读取接口不启动执行"。
- 测试：新增2项——超期任务被终止且终态为`failed/timeout`（含早于deadline时不触发）；已成功完成的任务在 deadline 之后也不被追溯改写。共16项政策测试。
- 边界（如实记录）：①**deadline 是运行时推导**（started_at + 当前政策超时），尚未持久化为列，未达EXEC13"持久化deadline"的字面要求；②无调度器，监督依赖有人触发状态核对（无心跳线程）；③`failed/resource_limit`归类、Agent预算预留、容器路由仍未做。**A41仍不通过**。
- 验证：全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第3片：并发准入（槽满拒绝）

- 来源：用户"继续"。
- 实现：`execution.py` 新增 `CapacityExceeded`（code=`capacity_exceeded`、HTTP 409，经既有`ExecutionError`处理器自动映射）；`ExecutionService` 接受注入的 `policy`，缺省从 `configs/workbench/execution_policy.json` 加载；`submit()` 在幂等重放之后、preflight 之前按 `policy.max_concurrent` 统计未终态Attempt，**槽满即拒绝且不创建Attempt**；政策缺失/非法时以 `execution_policy` 前置失败拒绝（fail-closed），读取路径不受影响。
- 测试：新增3项——槽位被占时第二次提交抛`CapacityExceeded`(409)且未新增Attempt；取消后槽位释放、下次可提交；**幂等重放不消耗槽位**。共14项政策测试；tearDown 取消遗留Attempt避免泄漏子进程。
- 边界（如实记录）：槽位判定在插入前完成，**不是EXEC13要求的"持久化事务内预留"**；单进程单用户下竞态窗口极小但未消除。
- 未完成：deadline与超时终止监督、Agent预算预留、Qlib执行器改走容器、`failed/resource_limit`归类。**A41仍不通过**。
- 验证：全量门禁 `[gate] ok`。

## 2026-09-27 — T04 第2片：容器内存探测 + CPU 上限真实注入

- 来源：用户"可以"，接续 T04 剩余项。
- 内存探测改为**容器OOM实测**：`probe_enforcement()` 现在会 `docker run --memory=128m` 并让容器分配超限内存，只有拿到 OOM 退出码(137)才判为可强制；本机结果 `cpu=true`(rlimit)、`memory=true`(container_cgroup)，并标注"平台有能力≠执行器已用上"。新增 `container_limits()` 输出 `--cpus/--memory/--memory-swap`。
- CPU 上限**真实注入子进程**：执行器新增 `limits` 参数，`start()` 在包装脚本里前置 `ulimit -t <秒>`；`cli.py` 组合根按政策传入 `child_limits(policy)`。
- 新增2项强制测试：注入上限后跑死循环子进程，**确认被限制终止**（poll 报 interrupted、无退出标记、20秒内停止）；不设限时不产生 `ulimit` 前置。共11项政策测试。
- **发现新缺口（记入A41）**：被上限杀掉时包装 shell 自身收到 SIGXCPU，写不到退出标记，因此当前只能落 `interrupted` 且退出码为 None，**达不到 A41 要求的"failed/resource_limit 及证据"**；需要信号级证据或包装器改写退出标记的方式。
- 过程记录：接线时曾漏写字符串拼接的 `+`（变量不能与字面量隐式拼接），导致 CLI 语法错误被门禁捕获，已修正。
- 未完成：并发槽准入、deadline与超时终止监督、Agent预算预留、Qlib执行器改走容器（内存强制的前置）、resource_limit 归类。**A41 仍不通过**。
- 验证：全量门禁 `[gate] ok`。

## 2026-09-27 — T04 内存上限结论更正：容器可强制，rlimit 不可

- 来源：用户质疑"内存上限不够"的判断依据，要求先查清 macOS 到底怎么设。复查结论如下。
- rlimit 侧（复核并加强证据）：`man 2 setrlimit` 的资源列表**不含 RLIMIT_AS**；`ulimit -v`（虚拟内存）、`ulimit -d`（数据段）、`ulimit -m`（RSS）在本机**全部返回 `Invalid argument`**；Python `setrlimit` 对 AS/DATA/RSS 同样失败；仅 `RLIMIT_CPU` 可用（1秒 SIGXCPU）。故 macOS 上**没有任何可用的进程级内存硬上限**，这与数值大小无关。
- 容器侧（新证据，决定性）：本机 Docker 可达（Ubuntu 24.04，池内存 5.77 GiB），`docker run --memory=256m --memory-swap=256m python:3.12-alpine` 内分配 400MB **被 OOM 杀掉（rc 137）**；同样的分配不加限制则成功（rc 0）。即**内存硬上限在本机可通过容器真实强制**。
- 结论更正：先前"该环境内存硬上限不可强制、A41在本机无法通过"的表述过于绝对。准确说法是——**rlimit 路径不可行，容器路径可行且已验证**；当前障碍是 Qlib 执行器仍为裸子进程（RD-Agent 执行器已走容器）。A41 仍不通过，但原因是实现未接入，而非平台不可行；配置中 `enforce=["cpu"]` 保持不变，接入容器后再纳入 `memory`。
- 未改动：未修改执行器实现与准入逻辑；A41/T04 状态不变。

## 2026-09-27 — T04 执行政策（第1片）：政策冻结与资源上限能力探测

- 来源：用户"继续"，按 spec 顺序执行 T04。
- 实现：新增 `configs/workbench/execution_policy.json`（max_concurrent / timeout_seconds / terminate_grace_seconds / cpu_seconds / memory_bytes / agent_budget，均为显式正数）与 `execution_policy.py`：`load_policy` 对缺字段、0/负数、布尔、字符串、非法 `enforce` 一律拒绝；`revision()` 对冻结值取内容哈希；`probe_enforcement()` **真跑子进程探测**；`unsupported_limits()` 命名不可强制项；`child_limits()` 输出待注入上限。9项测试。
- **平台能力实测（决定A41收口）**：CPU硬上限**可强制**——子进程设 `RLIMIT_CPU=1` 后 1 秒被 SIGXCPU 终止（rc −24）；内存硬上限**在本机不可强制**——macOS 对 `RLIMIT_AS` 与 `RLIMIT_DATA` 均返回 `ValueError: current limit exceeds maximum limit`，且 400MB 分配照样成功。故配置只声明 `enforce=["cpu"]`，把内存不可强制登记为可见限制；若声明需要内存强制，`unsupported_limits()` 返回 `["memory"]`（准入必须拒绝）。
- 按 spec 收口：EXEC13 明确"若某环境尚不支持，上限能力与A41保持未完成，该环境不得通过完整EXEC06准入"——因此 **A41 不通过**，T04 标为部分完成。
- 未完成（下一步）：持久化并发槽准入、deadline 与超时终止监督、Agent 试验/调用原子预留与跨重启计数、把 CPU 上限注入子进程（执行器已用 `/bin/sh` 包装，`ulimit -t` 可注入）。
- 验证：全量门禁 `[gate] ok`（Python 239项含新增9项、2跳过；JS 23项）。

## 2026-09-27 — T03 比较合同复验：mode 不得绕过身份校验

- 来源：用户"顺序做吧"，执行 spec 顺序中的 T03。
- 发现的两处真实缺口：①**equity 模式此前不校验`evaluation_id`**；②**metric 模式此前不校验`execution_id`与资金口径字段**（initial_equity/cashflow_policy/price_basis/benchmark_id），而 RESULT_CONTRACT 身份分层要求排名必须具备 dataset+execution_id+evaluation_id，且金额/收益/风险行无论mode都必须核对资金口径——即 `mode=metric` 可绕过equity要求。
- 实现：`metrics` 新增 `field_applicability`/`requires_execution_basis`/`requires_money_basis`，把"首批回测指标字段适用表"登记为契约（回测行必需执行身份；金额/收益/风险行必需资金口径；纯比率行豁免资金口径但仍需执行身份）；`assess()` 改为按该表校验，equity模式补 evaluation_id 检查。
- 测试：新增 `T03IdentityCounterexampleTests` 6项——equity缺评估身份、metric不同成本情景（并排可用/不排名）、不同初始资金、未知现金流、纯比率行豁免、适用表覆盖；同时更新 `test_review_regressions.py` 的R05夹具补 `evaluation_id`（该夹具此前缺评估身份，按现行spec本就不可排名，属夹具过期而非实现放宽）。
- 影响：**历史缺评估身份的对象变为不可排名**（fail-closed，符合"缺少任一身份时保持不可排名"）；比较页UI未改，方向与可比性仍由服务端判定。D08关闭，T03完成。
- 验证：全量门禁 `[gate] ok`（Python 230项含新增6项、2跳过；JS 23项）。

## 2026-09-27 — T02-U 验证卡切换v2与浏览器验收

- 来源：用户"去做"，执行 spec 的下一步 T02-U。
- 实现：`ui/app.js` 的验证卡改为显式请求 `analysis_version=2`；遇到非v2响应显示"旧定义，未满足当前纠正合同"而不混用字段；展示逐期Sharpe、PSR/DSR逐项可用性与中文原因、可用配置数、**声明试验数N及其来源**、唯一性权重和Σw并标注"不是独立样本量"、共同观测交集窗口、相关性假设、PBO丢弃余数与折叠重复、被排除配置及原因、探索性警告、定义卡与限制；说明注册表同步（删除"有效样本数"口径，补N来源与Σw语义）；扩充验证类不可用原因的中文词表。`validation_v2` 的限制文案改为中文，配置补 `title`。
- 测试：`test_ui.cjs` 新增3项（v2正常渲染且断言请求带 analysis_version=2 / v1响应拒显 / 不可用与退化PBO），JS 合计23项通过。
- 浏览器验收：启动带§2A.9夹具的临时服务（4个配置），实机打开比较页，确认卡片显示 PSR 0.665/0.802/0.899/0.956、DSR 0.44/0.607/0.757/0.87、PBO 0、可用配置4/4、N=4（本次选择推断）、Σw 10.3（不是独立样本量）、共同观测交集与探索性警告；截图见[证据](evidence/20260927-t02u-validation.png)。
- 影响：T02全线（D/B/U）完成，A31/A32诊断子项证据齐备；A36仍待T06/T07；A30其他估计量缺陷独立保留。
- 验证：全量门禁 `[gate] ok`。

## 2026-09-27 — T02-B 验证v2实现（后端/API/CLI）

- 来源：用户"按照spec，继续往下做"，执行 spec 声明的下一步 T02-B。
- 实现：新增 `quant_workbench/validation_v2.py`，按 [VALIDATION §2A](VALIDATION.md) 实现 PSR/DSR/PBO——声明N真实进入Φ⁻¹、CSCV秩ω=r/(K+1)且排除候选自身、等长分块并披露丢弃的最早余数、重复配置按1e-12折叠、零离散度与非有限值fail-closed；新增 `leakage.uniqueness.weight_sum`（不再叫effective_samples，并注明不是独立样本量）。service/API/CLI 增加 `analysis_version=1|2` 与成对 `revision_id`；**默认v1行为与字段不变**；收益口径复用风险v2的登记映射（主来源不可用时不回退）。
- 验收：`tests/test_validation_v2.py` 共22项，**复现§2A.9全部独立参考值**——PSR 0.6645/0.8024/0.8990/0.9557；DSR在声明N=4/10/20为0.6075/0.4944/0.4235且随N单调下降、不饱和；PBO主导夹具=0、中间值夹具=1/3、重复配置=`degenerate_configurations`；另覆盖单配置（PSR可用、DSR/PBO不可用）、N<可用配置数、缺测排除、horizon不影响PSR/DSR/PBO但影响leakage、revision成对校验400、API/CLI端到端。
- 修正记录：实现时曾把DSR判定顺序写反（单配置回报`declared_trials_below_two`），按§2A.8要求改为先判可用试验数并回报`deflated_sharpe_needs_at_least_two_trials`；测试同时暴露我漏实现§2A.8要求的`leakage.uniqueness.weight_sum`，已补齐。
- 影响：A31/A32诊断子项记录v2证据；**A36父项不关闭**（TrialLedger与训练协议归T06/T07）；下一步为T02-U（界面切v2+浏览器验收）。
- 验证：全量门禁 `[gate] ok`（Python全量含新增22项 + JS 21项）；文档链接与表格检查。

## 2026-09-27 — 数据管线spec审计：补操作手册并修正过期状态

- 来源：用户问"当前做的那些数据处理的，刷新spec了嘛"。
- 审计方法：把本轮新增的7个脚本与10份证据逐一对照 spec 引用，并核对T05-S行的"剩余范围"是否仍成立。
- 发现的缺口：①脚本与证据虽都有引用，但**没有一处可执行的操作手册**——命令散落在各脚本docstring和叙述里，换机重建或交接时无法照做；②磁盘资产（归档/快照/缓存/注册表/物化/备份）没有权威清单，分不清哪些可重建；③T05-S行的剩余范围**已过期**（仍写着"物化引用/旧路径/迁移恢复未做、未跑全量门禁、特征标签管线未做"，而这些均已完成）。
- 处置：DATA_SOURCES 新增 **§7 数据管线操作手册与资产清单**（资产表+能否重建、5步重建顺序、5条关键不变量、替换来源要改什么），原§7/§8顺延为§8/§9（确认无外部引用指向旧编号）；T05-S行重写为与事实一致，并注明`register_free_snapshot.py`与全量门禁绿。
- 未改动：任何实现、数据与验收结论；A30/A33/A37仍不关闭，T05本体的剩余项（真实财务修订源、真实bar覆盖门禁、A40子项、data_directory接入应用层）明确保留。
- 验证：文档相对链接与表格列数检查通过。

## 2026-09-27 — 样本外 walk-forward：样本内结论未复现

- 来源：用户"可以"，接续上批建议的样本外切分。
- 实现：`factor_pipeline` 新增 `load_symbol_series`（共享取数，消除脚本重复）与 `walk_forward_windows`（扩张窗口折分）；新增 `scripts/run_factor_walkforward.py`——**选择只用训练窗口**（FDR q≤0.05 且成本门槛通过），**评估只用其后的块**。
- 实测（csi500，2025-01-02→2026-09-24，4折、min_train=120日、每块约75日）：仅第3折选出4个假设（全部h=5），训练均值IC −0.0376，其后测试块 **+0.0066**，组合均值符号不保持（单条2/4保持）；另外3折无假设同时通过两门槛。
- 结论：上批"1/12同时通过FDR与成本门槛"是**样本内**结论，样本外未复现。样本极小（1折有选择/4个测试块），只能作负面信号，**不能反证所有因子无效**；它证明"同一窗口既选又评会把噪声当信号"。
- 重构验证：抽出共享取数后重跑研究脚本，证据与提交版本**逐字节一致**。
- 影响：DATA_SOURCES 新增 walk-forward 小节、FACTOR_ANALYSIS 旁注与 IMPLEMENTATION 的 T08-P 行同步更新；A30/A33/A37 仍不关闭。
- 验证：全量门禁 `[gate] ok`；文档链接与表格检查。

## 2026-09-27 — 因子研究三件补齐：beta中性化、稳定性、成本门槛

- 来源：用户"继续做完"（补完上批列出的三项）。
- 实现：`factor_pipeline` 新增 `rolling_beta`（用archive自带的中证500指数`SH000905`收益，滚动窗口、PIT）、`neutralize` 扩展为多暴露（size+beta）+行业哑变量、`stability`（分折同号率与离散度）、`cost_threshold`（成本门槛筛选）；`run_factor_research.py` 接入全部四项并输出 `summary.survives_both`。
- 费率：往返成本 9.2bp 取自 `configs/cn`（佣金万2双向 + 印花税万5卖出 + 过户费万分之0.1），滑点未计入，明确标注为筛选而非回测。
- 实测（csi500，421交易日，12假设）：**7个过FDR、6个过成本门槛、仅 `volatility_20_h5_neutralized` 同时通过**（IC −0.033、NW t −2.80、q=0.0122、6折同号率0.83、净价差+8.2bp）。
- 关键发现：①加入beta后中性化IC由−0.051降至−0.035，说明此前size+行业中性化残留市场beta；②过FDR的假设多数过不了成本、过成本的多数不显著，**两个门槛必须同时用**；③唯一同时通过者净价差仅+8.2bp且未计冲击成本。
- 仍未做：训练/测试切分（当前全窗口既探索又评估）、组合层验证、冲击成本；A30/A33/A37不关闭。
- 验证：全量门禁 `[gate] ok`（Python 196项含新增4项、JS 21项）；证据见[factor-research](evidence/20260927-factor-research.json)。

## 2026-09-27 — 依赖落地为运行环境、全量门禁转绿与连接泄漏修复

- 来源：用户指出上一批只声明依赖未真正安装，要求把因子研究依赖补齐。
- 环境：`extensions/workbench/.venv` 用 `uv sync` 安装 `analysis`+`api`+`test`+`data-fetch`+`qlib-import`（Python 3.14.7）；`uv.lock` 同步更新（+95行，含baostock及其依赖）。验证导入：numpy 2.5.3 / baostock 0.9.4 / fastapi 0.141.1 / httpx 0.28.1 / pandas 2.3.3。
- 门禁：`scripts/workbench_gate.sh` **通过**——Python 196项（2跳过）+ JS 21项，退出码0；`[gate] ok`。此前"未跑全量门禁/无.venv"的限制解除。
- 缺陷1（真实实现错误，门禁暴露）：`storage_base._connect()` 每次新建 sqlite 连接，而 `with conn:` 只提交事务**不关闭**连接；Python 3.14 对未关闭连接发 ResourceWarning，恰好落进 `test_risk_v2` 的 stderr 断言导致偶发失败。修复：新增 `_connection()` 托管上下文（保留事务语义并 `finally: close()`），替换 25 处调用与 3 处测试调用；全新字节码缓存下196项稳定通过。
- 缺陷2（可用性事件）：BaoStock 在全量抓取（1,802只×6进程）后返回 `10001011 黑名单用户`，此后登录失败。已抓缓存（1,791只/4,601,971行）完整保留，因子研究不依赖源端在线；`fetch_csi500_turnover.py` 改为父进程预检+明确失败（退出码3）、默认并发降到2、新增 `--sleep`。已登记到 DATA_SOURCES 且不隐藏。
- 确定性：用项目 venv 复跑 `run_factor_research.py`，输出与提交的[因子研究证据](evidence/20260927-factor-research.json)**逐字节一致**（跨解释器）。
- 验证：全量门禁通过；两个采集/研究脚本在项目 venv 下运行；文档链接与表格检查。仍不宣称因子有效（A30/A33/A37未关闭）。

## 2026-09-27 — 因子研究依赖补齐与全链路切片（T08-P）

- 来源：用户"继续，把因子研究的所需依赖一次都做完，然后刷新spec文档"。
- 依赖：`pyproject.toml` 新增 `data-fetch = ["baostock>=0.9.4,<1"]`（此前采集脚本需要但未声明）；因子研究运行使用既有 `analysis`（numpy）extra。两个 extra 在本 worktree 均未安装（无`.venv`），实测用系统 python3。
- 能力补齐：`factor_pipeline.py` 新增两端可交易过滤（t与t+h）、日频流通股本科与对数流通市值、PIT统计行业滚动聚类、size+行业中性化、秩换手、分位差、Newey-West t、BH-FDR与正态双侧p；新增 `scripts/run_factor_research.py`。
- 实测（csi500，2025-01-02→2026-09-24，421交易日，12假设）：h=5动量 raw −0.055(t−3.11) → 中性化 −0.051(t−4.40)；波动 −0.029(t−1.14) → −0.041(t−2.51)；换手 −0.022(t−0.84) → **−0.043(t−2.94)**；**7/12 假设 q≤0.05**。证据见[20260927-factor-research.json](evidence/20260927-factor-research.json)。
- 关键解读（写入spec）：①换手因子中性化后才显著，说明原始换手主要是市值代理；②h=5分位差仅−0.22%~+0.61%且与IC符号不一致，远不足以覆盖交易成本；③行业为统计代理、size由推导得到、未做beta/风格中性化与样本外滚动检验。因此**不是alpha或可交易证据**，A30/A33/A37不关闭。
- 修正：测试暴露 `float_shares_from_series` 换手百分比换算漏一层（流通股本小100倍），改为复用已验证的`free_sources`公式避免两份实现漂移；`rank_turnover` 完全反转的期望值修正为2/3（4只标的的秩口径上限）。
- 测试：55项通过（含因子管线17项、数据目录与免费源38项）；未跑工作台全量门禁（本worktree无`.venv`）。
- spec刷新：DATA_SOURCES 因子研究切片章节、FACTOR_ANALYSIS 验收表旁注、IMPLEMENTATION 顶部依赖声明与T08-P行、本CHANGELOG。

## 2026-09-27 — 首个特征与标签切片（T08-P 试点）

- 来源：用户"可以，继续"，接续 T05 之后搭建特征/标签链路。
- 实现：新增 `quant_workbench/factor_pipeline.py`——`aligned_series`（按快照日历对齐）、`forward_return`（日历步进标签，末尾h行无标签）、`tradable`（停牌/ST/一字板过滤，`change`按小数处理）、`momentum`/`volatility`/`mean_of`、`cross_sectional_rank`（并列取平均秩）、`rank_ic`（Spearman，重叠<3返回None）；新增 `scripts/run_factor_slice.py`。
- 实测（csi500，2025-01-02→2026-09-24）：421个交易日、500只、208,777可交易行、过滤1,723行；均值Rank IC：20日动量−0.055、20日波动−0.029、20日平均换手−0.021，含逐因子IC序列摘要；证据见[20260927-factor-slice.json](evidence/20260927-factor-slice.json)。
- 定位：**仅证明管线可用，不是alpha有效证据**——无行业/规模中性化、无t+h卖出可交易性过滤、无多重检验与样本外；A30/A33/A37不因此关闭，T08未完成。
- 测试：新增9项，与数据目录/免费源合计47项通过（system python3 + numpy）；未跑工作台全量门禁（本worktree无`.venv`）。

## 2026-09-27 — T05 物化、质量门禁、旧路径与迁移（数据源切片收尾）

- 来源：用户"继续t05"。
- 实现：`data_directory` 增加 `materialize_panel`（确定性长表，同输入+同seed摘要一致）、`verify_materialization`（复算校验）、`validate_bars`（对齐/正数/无穷/OHLC门禁，**NaN计为缺失而非损坏**）、`register_legacy`（旧路径显式登记且不可静默升格）、`migrate_registry`（升级前备份、拒绝降级新版本）、`restore_registry`（从备份恢复）；新增 `scripts/register_free_snapshot.py`。
- 实测：中证500全量500只bar审计**0问题**（0 issue，NaN单列为missing）；物化close/volume窗口两次摘要一致`sha256:db60e4b6…`且复算通过；`cn_data`、`qwb_cn_current`登记为`legacy_unknown`；快照`reproducibility=reproducible`。证据见[20260927-t05-directory.json](evidence/20260927-t05-directory.json)。
- 发现并修正：初版OHLC不变量写错（漏“收盘高于最高价”）、且把NaN当作损坏报错245处；两者均由测试/真实审计暴露后修正，NaN改为缺失计数。
- 测试：数据目录与免费源相关38项通过（system python3 + numpy）。仍未跑工作台全量门禁（本worktree无`.venv`）。
- 边界：T05仍差真实财务修订源、真实bar覆盖/范围门禁、A40数据访问子项与完整A16/A17验收；特征与标签管线未做。

## 2026-09-27 — T05 目录端口与快照登记（数据源切片续）

- 来源：用户同意"先做T05本体"。
- 实现：新增 `quant_workbench/data_directory.py`——快照记录与组件清单、内容摘要、已发布不可追加修改（同摘要幂等）、摘要校验、reproducibility（证据不完整即limited）、`select_as_of`（不泄漏未来修订）、`resolve_symbol`（代码复用区间解析）、`FreeSnapshotReader`（按快照ID+数据根读取日历/成分/字段，不导入Qlib）。
- 登记：`verify_free_snapshot.py` 增加 `--record-output`，产出[快照记录](evidence/20260927-free-snapshot-record.json)（4组件：calendar/universe/bar/status，内容摘要`sha256:2d6f5367…`）；数据根不写入记录。
- 验收：新增 `tests/test_data_directory.py` 11项，A16（as-of不泄漏、代码复用、缺字段fail-closed）与A17（不可变、幂等重放、篡改拒绝、复现受限）为**部分证据**；两模块合计30项测试通过。
- 边界：T05仍未完成——物化引用、旧路径显式登记、迁移/恢复、同种子复跑未做；A16/A17不得据此关闭；未跑工作台全量门禁（本worktree无`.venv`）。
- 验证：30项新增/相关测试通过（system python3 + numpy）；文档链接与表格检查；快照校验器 `ok:true`。

## 2026-09-27 — 执行轨迹澄清（仅文档）

- 来源：用户质疑"是不是跳了，直接到T05"。
- 澄清：主线下一步仍是 **T02-B**，且尚未开始；数据源工作是你明确要求并授权的并行推进，在IMPLEMENTATION中登记为 **T05-S 数据源切片**，**不等于T05里程碑完成**（T05端口、组件清单、物化引用、旧路径登记、迁移/恢复与A16/A17均未做）。此前CHANGELOG条目标题中的"T05首片/二片"仅指数据源切片，原文保留不改写，以本条为准。
- 同时修正IMPLEMENTATION顶部过期表述"上述登记批次没有改动运行代码或数据管线"：实际新增了`free_sources.py`与两个采集/校验脚本，并落盘了快照与换手率缓存。
- 验证：只改文档；文档链接与表格检查。不改变任何功能状态或验收结论。

## 2026-09-27 — csi500 池子与换手率缓存落地（数据源切片）

- 来源：用户决定"先用中证五百作为池子"，并要求继续推进已授权的落地工作；DEC01 的股票池由此确定。
- 决定：股票池=中证500（历史成分1,802只，2026-09-24在册500只）；研究区间=2015-01-05→2026-09-24；来源=FINV主+BAO校验。csi300/csi500/csi1000成分不含北交所，天然规避先前发现的北交所缺口。
- 实现：新增 `scripts/fetch_csi500_turnover.py`（BaoStock 多进程、可续跑、写 CSV + unsupported 清单）；`quant_workbench/free_sources.py` 增加 `universe_by_date`、`load_turnover_csv`、`float_shares_from_archive`；测试增至19项。
- 实测：1,791/1,802 只抓取成功，4,601,971 行，覆盖 2015-01-05→2026-09-24，含 `tradestatus`（停牌128,171行）与 `isST`（152,895行）；11 只空结果为2015年前退市/吸收合并的历史成分（SH600087/600102/600253/600263/600553/600607/600840/600991、SZ000515/000522/000602），不补造、排除在研究窗口外。
- 派生：`流通股本=(volume×factor×100)/turn`、`流通市值=(close/factor)×流通股本`；停牌日不反推，保留缺口。
- 验证：19项测试通过；快照校验器 `ok:true`（含 enrichment 覆盖块：1,791缓存/1,802宇宙/11缺失，记录见[快照登记](evidence/20260927-free-snapshot.json)）。未跑工作台全量门禁（本worktree无.venv）。
- 边界：仍**未接入数据目录**（T05端口/A16/A17/A37未完成）；特征与标签管线、非csi500扩展未做。

## 2026-09-27 — FINV 快照落地与三项缺口实现（T05 首片）

- 来源：用户授权下载主源并落地，同时要求实现日频市值、PIT行业、生存者偏差三项处置。
- 快照：下载 release `2026-09-27`（566,505,035字节），archive SHA-256 与清单逐位一致，发布方 `validate_archive.py --require-publishable` 返回 `ok:true`；解包到独立版本目录（不覆盖既有 `cn_data`/`qwb_cn_current`），日历末日 `2026-09-24`。快照登记见[免费快照登记](evidence/20260927-free-snapshot.json)，来源类别 `free_community_unverified`，未记录绝对路径。
- 解包实证（更正此前未验证的推断）：字段共10个（adjclose/amount/change/close/factor/high/low/open/volume/vwap）；价格为复权价（原始=复权÷factor）；volume反向复权（原始手数=volume×factor）；amount单位为千元；三者与BaoStock/东财逐值一致（9.00元 / 528,364手 / 475,964,884元）。退市股在库（`SH600005` 2000-01-04→2017-02-13）。**发现北交所缺口**：597只中241只区间终止于2025-09-30，抽样 `BJ430047/430090/430198` 的 `delist_date` 为空，属数据缺口而非退市；csi300/500/1000不含北交所可规避。
- 实现：新增 `quant_workbench/free_sources.py`（bin读取、单位换算、流通股本反推、区间化universe与生存者偏差报告、收益聚类统计行业）与14项测试；新增 `scripts/verify_free_snapshot.py` 生成快照身份记录（只读、不记录绝对路径与主机名）。
- 边界：快照**已落盘但未接入数据目录**；T05/A16/A17/A37仍待实现，本次不声明"真实数据已接入"。全市场换手率批量拉取（日频流通市值所需）与统计行业的正式接入仍待T05后续。
- 验证：字节数与SHA-256校验、发布方脚本 `ok:true`、解包结构核对、14项新测试通过（system python3 + numpy）。**未运行工作台全量门禁**：本 worktree 无 `extensions/workbench/.venv`，未重跑既有套件。

## 2026-09-27 — 三个数据缺口展开与处置方案

- 来源：用户要求展开日频股本/市值、PIT行业分类、生存者偏差三个缺口。
- 新增实测：主源 `show tables` 共14张表且**无任何股本/市值表**；发布包按 `qlib/normalize.py` 仅导出 `open/close/high/low/vwap/volume`+`amount`+`factor`（不含换手率、ST/停牌与股本，archive内字段未解包核验）。`ts_a_stock_list` 含 `list_date`/`delist_date`；`bao_a_stock_eod_info` 含 `turn`/`tradestatus`/`is_st`/`adjfactor`。BAO `query_stock_industry` 返回 `updateDate=2026-09-21` 的证监会行业（当前快照）。
- 处置：①日频流通股本用 `成交量÷换手率` 反推，实测误差0.025%（33,314,247,793 vs 33,305,838,300），需额外取换手率且只给流通股本；②PIT行业用"当前行业近似+显式标注"，严格中性化改用收益相关性聚类等统计行业，正式PIT行业留DEC01后续；③universe只从含日期区间的instruments构造，用delist_date对账退市数量，并以"全集vs仅存活"的IC差值量化偏差。
- 严重度排序：生存者偏差 > 日频市值 > PIT行业；三者都不阻塞价量因子起步。影响DATA_SOURCES §1B，验收要求不变。
- 验证：只读DoltHub schema/样例行与BaoStock查询（含600005退市样本、换手率反推）；文档链接与表格检查。未下载数据包、未落库、未接入。

## 2026-09-27 — 数据充分性评估：价量因子与多因子训练

- 来源：用户确认范围——只做因子挖掘与多因子训练，**不考虑基本面（财报）**，**不需要实时更新与分钟线**；据此判断现有免费来源是否够用。
- 结论：够用，可开始 T05。价量、波动、换手、流动性、量价关系、高低价位置、K线形态、横截面统计、停牌/ST/涨跌停特征与历史指数成分均有来源支持；数据量（约 5,000 只 × 250 日 × 20 年）不构成瓶颈。
- 新增实测：BAO 日线含 `tradestatus`、`isST` 字段；BAO 保留退市股历史（600005 在 2016 年有 244 行，2026 年无数据，符合退市事实）。FINV 退市覆盖因 DoltHub 聚合查询超时未能在线上确认，登记为下载后必须核对项。
- 登记缺口（不阻塞价量因子，限制特定因子族）：①日频股本/市值缺失，size 类只能用季频股本近似，送转/增发时点会跳变；②无 PIT 行业分类，行业中性只能用当前行业近似并有回填偏差；③必须用历史成分（含退市）构造 universe，否则产生生存者偏差。
- 影响：DATA_SOURCES.md 新增 §1A 因子族可用性矩阵与三条实现要求（复权标签、剔除不可成交样本、历史成分 universe），§1 需求表标记本阶段排除项；T05 接入与 A16/A17 验收要求不变。
- 验证：只读 API 探测（BaoStock 日线与退市样本、DoltHub 抽样查询）；文档链接与表格检查。未下载数据包、未落库、未接入数据目录。

## 2026-09-27 — 免费数据源登记（因子研究用）

- 来源：用户要求寻找免费开源数据接入，至少满足中低频因子训练与因子挖掘、尽量覆盖到2026年9月，并登记哪些是免费但精度/可信度不足的来源以便后续替换；回测成交细节明确不在本批。
- 实测（2026-09-27，只读探测）：FINV `chenditc/investment_data` release `2026-09-27`，清单 `target_trade_date=2026-09-24`，带 archive SHA-256、Dolt/Qlib 提交号与 `validate_archive.py`；BAO 实测日线、日历、复权因子与带 pubDate 的2026Q2财务到 `2026-09-24`；EM 东财接口实测178行到 `2026-09-24`，总股本与 BAO 一致；CSI 中证成分表 HTTP 200；YF 三次探测为 429/200/429；QLIB-EX 最新 release 为 2024-05-22 静态快照；TS 未验证。
- 产物：新增[数据源清单](DATA_SOURCES.md)（字段需求、来源总表、逐源评估、`free_community_unverified`分类、推荐组合与替换路径、未验证项、验收映射）；新增只读探测脚本 `scripts/probe_data_sources.py` 与证据[20260927-free-data-probe.json](evidence/20260927-free-data-probe.json)。[来源审计](PROVENANCE_AUDIT.md)新增免费来源类别，README登记索引，IMPLEMENTATION更新D05/DEC01/T05。
- 结论与边界：建议 FINV 作日线主源、BAO 作校验、EM 作行业与补充、CSI 作 universe 对照；免费来源不稳定（EM 一次断连、YF 限流），必须带重试、失败留痕与降级路径。未下载数据包、未落库、未创建 snapshot、未接数据目录；A16/A17/A37 与 T05 仍待实现，DEC01 的股票池/起始区间/下载授权待确认。
- 验证：只读网络探测（脚本可复跑）＋文档链接/表格/diff范围检查。未修改 `extensions/workbench/` 运行代码；新增的 `scripts/probe_data_sources.py` 只做只读探测。

## 2026-09-27 — T02-D 验证 v2 定义冻结（仅文档）

- 来源：用户确认继续推进；按IMPLEMENTATION的T02-D设计门先冻结口径再进入实现。核对代码基线58fdeeb3，本批只改 docs/spec。
- 冻结：PSR/DSR/PBO公式与估计量约定（逐期不年化、ddof=1、矩分母为n、峰度非超额）、收益与rf口径（沿用风险v2登记映射、不扣rf、说明SR*=0含义）、M/C/N关系（N必须进入公式、N≥可用配置数、缺账本标探索性、相关性unmodeled_iid）；PBO分块（S为偶数4—12、T≥2S、余数丢弃最早并披露）、秩 ω=r/(N+1)（不含候选自身）、重复配置折叠、零离散度fail-closed。
- 记录缺陷：DSR声明trials未进入公式；PBO秩含自身并用N归一，N=2时把“IS与OOS同为最优”误判为过拟合；近等长分块与组合静默跳过；PSR静默丢弃非有限值；验证链路弱于风险v2的登记校验；uniqueness的effective_samples名称误导。以上均为T02-B待修，本批不修代码。
- 参考值：新增独立复算脚本[20260927-t02d-reference.py](evidence/20260927-t02d-reference.py)（仅标准库、不导入工作台）：夹具A的PSR为0.6645/0.8024/0.8990/0.9557；候选C2在声明N=4/10/20的DSR为0.6075/0.4944/0.4235，基准随N上升；PBO夹具给出0与1/3，逐组合可手算复核。
- 影响与出口：U20、VAL03/05/06、METRIC06、A31/A32及A36诊断子项；VALIDATION升版2.2新增§2A，IMPLEMENTATION与README同步下一步T02-B。A36父项、TrialLedger与实际训练证据仍归T06/T07，M0—M5不提升。
- 验证范围：只读核对validation.py/application/API/CLI/UI边界；运行独立参考脚本（全部断言通过）；检查文档链接、表格与diff范围。顺带修正 review-20260926b.md 中 C3 行多出的空单元格（渲染时“建议”列会被丢弃），只改格式、不改历史结论。未修改代码、未重跑功能套件、未训练、未迁移数据、未做浏览器验收；不声明DSR/PBO缺陷已修复。

## 2026-09-27 — Spec可执行性复审与勘误（仅文档）

- 来源：用户要求review信息/记录错误、可理解性及其他agent能否无歧义执行；核对基线58fdeeb3。逐项发现与处置见[复审记录](archive/review-20260927-handoff.md)。
- 纠正：区分已实现与计划中的验证v2/revision接口；确认DSR声明trials未参与公式的代码缺陷并保持开放；拆分A32单配置规则；标注历史“真实运行”仍基于合成行情、唯一性权重和不等于独立样本量。历史数字不覆盖、不提升为新验收。
- 交接：补T02-D/B/U顺序、定义/DTO/独立样例设计门；纠正因子单调性代理和增量能力声明、年化参数来源、Attempt身份、UI关键事实展示与v1兼容边界；当前T01-U补确切交付58fdeeb3。影响GOV03、API01/UI04、METRIC06、U19/U20、A32、EXEC04及T02交接。
- 验证：只读核对Git及相关接口/实现；文档链接、表格、映射与diff范围检查。只修改docs/spec，未重跑功能测试、训练或浏览器，未修改API/代码/数据；不声明DSR缺陷已修复、不关闭A30/A36或提升M0—M5。公式进一步核验和具体DTO冻结归T02-D。

## 2026-09-27 — T01-U界面v2与验收

- 来源：用户要求继续逐步实施并回写spec；实现基线8dd1cf9e，与本条同提交。涉及METRIC06、U19/U22、A34。
- 实现：风险/因子UI显式请求v2；展示目标Sortino、rf/T来源、精确输入、NW均值标准误与显著性状态、相关/相似度/距离及实际FDR计数；提供定义卡与限制。缺失不填零；风险接口只分析最新revision，页面选择不匹配时阻止混显。修复窄窗口卡片被表格撑宽并保留标准误列。
- 验证：门禁141项Python（140通过、1项Qlib隔离跳过）、20项JS通过；新增revision保护后JS复跑21项通过。既有subprocess告警及故障注入日志保留。浏览器验收与脱敏截图见[记录](evidence/20260927-t01-u.md)。T01/A34限定纠正范围通过；A30其余估计量、真实数据/PIT及M0—M5缺口保持开放，下一步T02。
- 兼容：API/CLI默认v1不变，不迁移存储或重写历史产物，没有训练、真实行情或交易操作。本批包含UI代码、回归和spec，非纯文档提交。

## 2026-09-27 — T01-R/F交付后的spec状态刷新（仅文档）

- 来源：用户要求“刷新spec”；核对实现基线50f9f366与风险交付3a8f52b8。
- 更新：统一README能力摘要、IMPLEMENTATION里程碑/批次表和来源审计指针，修正仍称Sortino/相关命名未实现的过期描述；T01-F填写真实交付提交。纯文档复审明确为历史背景，D01—09仍是当前差距表。
- 交接：明确下一步T01-U的版本选择、字段、来源/限制呈现与浏览器验收；区分风险/因子已支持v2与验证接口版本机制仍待T02；补准因子数据版本及请求/实际检验数的DTO字段路径。
- 验证与范围：只改docs/spec，检查相对链接、Markdown表格和git diff范围；未重跑功能测试、训练或浏览器检查，测试数量只引用原提交证据。不改代码、默认版本、存储或历史产物，不提升完整A30/A34及M0—M5状态；其余统计缺陷、价格/PIT与真实研究验收保留。

## 2026-09-27 — T01-F因子/NW后端纠正

- 来源：用户要求继续按小里程碑实施。先在FACTOR_ANALYSIS冻结版本2响应、日期对齐、检验窗口及FDR计数，再修改实现；涉及U19、METRIC06、A34与A30统计子项。代码基线3a8f52b8，当前条目与实现同提交。
- 决定与实现：API/CLI提供analysis_version=2，默认1不变；NW协方差统一除N，移除人为方差地板，输出nw_se_mean与显著性可用原因；常数/短样本/缺IC不生成显著性。面板按摘要已核验的快照日历恢复日期与标的轴，避免删缺口改变horizon；预算不放宽。新相似度/距离字段先对逐日相关平均再取绝对值，保留符号和有效日期数，不返回旧redundancy。
- 来源与限制：定义卡锁定panel/hash/dataset，保留来源，未知不猜，全部标探索性；删除v2中无证据的“未使用未来修订数据”声明。发现换手跨缺口、正交增量相关方法混用、留一组合样本不同仍待修，披露不代表A30通过；价格复权/PIT验证与数据目录仍未完成。UI仅增旧定义提示，实际v2切换/浏览器验收仍待T01-U。
- 验证：22项因子专项（新增12项）通过，包括h=1/h=2手算、常数/缺口、跨日抵消、FDR数量、列顺序、精确引用、预算、API/CLI兼容；全门禁141项Python（140通过、1项环境隔离跳过），17项JS通过，退出码0。有既有subprocess ResourceWarning及预期故障日志。没有训练、真实数据或真实因子新口径验收，不提升M0—M5或完整A30/A34状态。
- 兼容：v1字段/算法不改，CLI警告写stderr；不改历史panel、结果revision、存储schema或数据库。完整T01与后续任务保持开放。

## 2026-09-27 — T01-R风险后端纠正与版本兼容

- 来源：用户授权开始逐步实施，每个小里程碑回写刷新spec。先冻结RESULT_CONTRACT的T01-R/F/U拆分与风险DTO/输入映射，再实现；影响METRIC06、U22、A34/A33子项。此批包含代码及测试，不再是纯spec提交。
- 实现：风险API/CLI增加analysis_version=2与同频rf/T；默认仍v1，拒绝向v1传新增收益参数。v2新增Sortino目标下行偏差、Sharpe参数来源、所有风险项定义卡、精确revision/数据引用和原来源分类；未知现金流/定义、缺测、样本不足明确不可用，不删除点或改用备选序列掩盖问题。CVaR尾部不足2点时数值与不可用原因一致。旧UI/CLI提示旧定义限制。
- 证据：16项风险回归通过（11项新增测试，含4个手算子例）；全门禁129项Python：128通过、1项隔离跳过，17项JS通过。门禁有既有进程ResourceWarning和预期故障注入日志，未隐瞒告警；最后输入/数值保护修改后风险专项重新通过。git diff检查及spec相对链接核验见交付记录。
- 限制：T01-F因子/NW与T01-U显式v2界面/浏览器验收未完成，不提升A34或M0—M5状态。当前只拒绝显式缺测，尚未验证完整日历覆盖；非正财富、未登记超额收益定义不支持。其余风险估计量保留原口径并披露，没有作全面统计认证。未训练模型、调用研究Agent或接入真实行情/券商。
- 历史与存储：保留v1字段/数值及旧revision；v2分析不持久化，不迁移数据库、不补造历史snapshot或环境身份；代码基线2652e918，本条与实现同一commit发布。

## 2026-09-27 — 0.2.1执行交接复审与修订（只改spec，未改代码）

- 来源：用户要求复审本轮spec的信息清晰度、下一步可执行性和歧义/错误，并明确要求修改文件。复审基线 `14f0201a`；问题记录见 [review-20260927.md](archive/review-20260927.md)。
- 影响：核心0.2→0.2.1；结果/验证/因子/执行专题2→2.1；研究生命周期与交易边界1→1.1。涉及RUN01、EXEC02/04/06/13、LIFE01/05/06、VAL05/06、METRIC06、COMPARE01、A34—A42；既有要求ID保留，A39拆为F/R/L子项。
- 处置：①资源硬上限未支持不能通过准入或A41；分别定义并发、超时、调用预算、迟到终态证据。②明确Run/Attempt/Stage关联、失败重试与成功复跑、当前Run状态投影及输入变化规则。③验证采用独立状态维度，账本/报告锁定试验集合与revision；前瞻新快照不改训练历史。④分析增加显式版本选择，旧版默认不变，UI切新版本，新字段与定义卡及Sortino手算期望值齐备。⑤修正NW标准误术语歧义，固定相关相似度的聚合顺序。⑥两种比较模式不能绕过回测资金/现金流条件，给出反例。
- 执行交接：IMPLEMENTATION增加T01—T10依赖、交付物与验收出口，第一步T01；拆开事后诊断与依赖生命周期的实际训练验证。DEC01/DEC02仅阻塞真实数据/券商相关任务。未来交易保持架构合同，实施前需补具体状态机和账目设计；模拟、前瞻、真实券商分别验收。
- 验证：12份Markdown、120个相对链接、无新增表结构错误、T任务依赖无环及A39子项映射通过；4个Sortino与1个NW样例复算通过，并核对反例、Git文档范围及diff；没有运行训练或Python/JS功能套件。实际代码/DTO/测试未变，D01—09继续开放，未提升任何功能阶段。
- 兼容：不迁移数据库、不覆盖历史revision/数值；analysis_version与新增字段仅为待实施接口合同。本轮没有真实数据采购、模型调用、券商下单或部署。

## 2026-09-26 — 0.2个人量化工作台设计刷新（只改spec，未改代码）

- 来源：用户要求以设计师/reviewer角色评审个人训练、研究、回测及后续自动交易的设计；在评审后明确授权“刷新spec文档，然后commit push，commit说明只改spec、没改代码”。代码核对基线 `b0363f11`。
- 影响ID：GOV03、U18—U26、ARC10—12、DATA06、METRIC06、COMPARE01、EXEC06/12、AGENT04、RW03；新增LIFE01—07、VAL01—05、TRADE01—06，验收A34—A42。核心合同0.1→0.2，治理1→2；结果/因子/验证/执行专题升为版本2。
- 决定：保留模块化单体、本地SQLite/文件和外部引擎进程；新增 [研究生命周期](RESEARCH_LIFECYCLE.md) 与 [交易边界](TRADING_BOUNDARY.md)，明确实验定义、模型复用、策略版本、前瞻模拟、账户/订单/风控/对账；统一对象发现与专业页面共用身份，数据目录按快照身份解析，不依赖当前配置猜历史路径。
- 口径：Sortino改为相对目标的全样本下行均方根，明确Sharpe的rf假设；旧redundancy命名改由相关相似度/距离两个定义解释，后续以新字段发布；唯一性权重和不直接等同独立有效样本量。实际训练证据、完整试验范围与测试访问必须区别于收益序列上的事后诊断。
- 冲突处置：①RESULT_CONTRACT旧完整情景指纹/evaluation_id映射已被分层身份替代；equity/metric排名均要求三类身份匹配。②U18当前仅回测组可排名，训练/研究组并排；不把“组内”误读成充分条件。③IMPLEMENTATION旧“执行成功不自动入库”更新为Qlib自动、RD-Agent手动。④RW03仅禁止观察/读取入口启动研究，写命令服从EXECUTION。⑤AGENT04资源上限要求保留，明确当前下限检查不能满足，登记实现缺口。⑥自动入库不改执行事实，但允许更新Attempt入库投影并追加回执。
- 数据与排序：保留现有JSON入口限制，新增分块清单、分析预算与浏览器返回分离要求。先纠正定义/验证声明，再补限定真实数据研究和模型生命周期，随后前瞻模拟及独立实盘接入；没有删掉既有M0—M5未完成要求，也没有把多用户/第二数据库作为个人研究的前置条件。
- 实际范围：只修改 `docs/spec/` Markdown；代码、API、测试、配置、数据库与历史产物均未修改。IMPLEMENTATION顶部集中登记D01—09缺口，A34—A42全部待实施/验证；既有阶段状态不提升。
- 验证：14份变更Markdown结构与116个相对链接检查通过，U23—U26与A34—A42登记、旧冲突表述检索和Git差异范围核对通过，`git diff --check`通过；未运行与纯文档变更无关的功能套件，不将历史测试写成当前验收。
- 兼容：旧revision、旧公式数值和历史证据不覆盖；新公式/字段须在后续代码交付中版本化并同步契约与UI。新增实体仅定义语义，物理schema和迁移方案尚未实施；无数据迁移、供应商选择、券商下单或部署授权。

## 2026-09-26 — Spec 同步：布局偏差、审查状态与演示数据集说明

- 来源：用户确认 spec 是否与最新代码/数据同步；核对发现三处过期，全部补齐。
- 同步内容：①[核心规范](WORKBENCH_SPEC.md) §2 在推荐目录之后登记"当前实现与推荐目录的差异"——核心包为扁平模块 + `adapters/`/`ui/` 子包，未建 `domain/`、`migrations/`；存储已拆为 `storage_base.py` + 三个域 mixin 且对象存储可注入；并明确 **SQLite/本地对象存储仍在核心包**这一未消除偏差，禁止据此声称已支持第二数据库。②[第二轮审查记录](archive/review-20260926b.md) 顶部修复状态与建议顺序更新到第三轮（C1 撤回、C5/C6/C8 已修、C2 第一批/C3/C9/C4 已完成，仍开放 C2 剩余编排、C7、C10）。③[实施状态](IMPLEMENTATION.md) 批次表补"第三轮审查修复""第三轮重构"两行，并新增"本机演示数据集裁剪说明"（保留集合、删除范围、备份路径与再生方式）。④CHANGELOG 旧条目的"未处理"清单改为"当时的未处理项"并加后续指针，避免用今天的进展覆盖当时的历史。
- 影响：仅文档同步，无代码、无数据、无能力声明变化；不需要重跑测试（文档变更只做结构/链接核查）。
## 2026-09-26 — 第三轮重构（二）：存储拆分为基础层 + 三个域 mixin（C4）

- 来源：用户确认继续按审查顺序做代码优化，并强调测试同步。
- 实现：`storage.py`（630 行）拆成 `storage_base.py`（schema 常量与迁移、连接、`SqliteStore` 基类、`LocalObjectStore` 内容寻址对象存储、`_write_object`/`_read_object` 委托）与三个域 mixin——`storage_results.py`（runs/revisions 发布与读取）、`storage_attempts.py`（Attempt 生命周期、导入回执、Attempt 统计）、`storage_factors.py`（因子实体与面板）；`storage.py` 变成 18 行组合门面并再导出常量/错误/基类，`LocalResultRepository` 的公开面（`_connect`、`objects`、schema 常量、各域方法）保持不变。
- 对象存储可注入：构造器新增 `object_store=`，默认 `LocalObjectStore(root/objects)`；换云端对象存储只需实现 `write(content_hash, data)` 与 `read(key)`，`objects` 属性指向该存储根，现有调用与测试无需改动。
- 验证：Python 118项测试117通过、1项环境隔离跳过（新增 `test_shared_helpers.py::ObjectStoreTests` 2项：写入-读取往返与同内容复用、篡改检测与路径穿越拒绝、以及门面接受注入存储后仍能建库）；JS回归16项通过；门禁脚本通过。拆分前后全量测试结果一致。
- 限制：SQLite 侧仍共用同一连接助手（`_connect`），按域拆连接未做；`storage_*` 模块用 `import *` 继承原作用域（含一处显式私有导入），后续可改为显式导入清单。对象存储的清理/迁移工具未实现。

## 2026-09-26 — 第三轮重构：共享数值/DTO/序列视图（C2/C3/C9）

- 来源：用户确认"代码优化"并强调测试同步；按第三轮审查顺序处理 C2 第一批、C3、C9。
- 实现：新增 `numeric.py`（lazy numpy、`sharpe(values, periods_per_year=None)`、`moment_stats`、`RANK_TOLERANCE=1e-9`、`ZERO_TOLERANCE=1e-12`）、`dto.py`（唯一的 `json_safe`）与 `series_view.py`（`return_series()`：优先引擎日收益，缺失时按权益派生，并返回来源标签）。`factors.py`/`validation.py`/`risk.py` 改为复用这三处实现（各域只保留按自身错误类型的适配），`metrics.py` 的容差改为引用 `numeric`；`WorkbenchService.strategy_validation` 与 `risk_report` 的重复抽取合并为一次 `series_view.return_series()` 调用。
- 规范：`VALIDATION.md` 与 `RESULT_CONTRACT.md` 写明最小样本按估计量分别定义（PSR/DSR ≥10、PBO ≥2 配置且观测 ≥2 块、风险指标族 ≥20）以及容差只保留一份实现的理由——避免把"同一份口径"误读成"可以共用阈值"。
- 验证：Python 116项测试115通过、1项环境隔离跳过（新增 `test_shared_helpers.py` 8项：numpy 缺失时的错误类型透传、Sharpe 年化/非年化与退化、矩统计、容差同源、`json_safe` 递归与非有限值、`return_series` 三种来源与空序列）；JS回归16项通过；门禁脚本通过。重构前后全量测试结果一致（行为不变）。
- 限制：C2 只完成"序列抽取去重"这一批，`WorkbenchService` 仍包含比较与任务中心编排；C4（存储拆分）、C7（前端拆分）、C10（测试分层）按审查顺序保留。

## 2026-09-26 — 第三轮审查修复：验证/风险口径收敛与契约覆盖

- 来源：用户要求"去修 bug"；本轮按第三轮审查顺序处理可确认为缺陷或治理漏洞的条目。
- 修复：①**C1 撤回**——复核发现月度复利的 `bucket.get(month) or 0.0` 与显式判断逐位等价（累加值为 0.0 与"尚未累计"同义，四种序列实测相同），原判定为误报，已在审查记录中保留纠正而不是静默删除；②**C5 静默降级**——`risk_report` 读配置失败不再回退 238，改为报 `RiskError` 并在 basis/顶层记录 `periods_per_year_source`（`config:`/`caller`），越界值同样拒绝；③**C6 契约漏洞**——契约测试新增七个新接口的顶层键冻结（attention/factors/因子详情/factor-analysis/risk/validation/revisions）；④**C8 死代码**——删除未被调用的 `factors.panel_hash()`。
- 验证：Python 108项测试107通过、1项环境隔离跳过（`test_risk.py` 增至 5 项、`test_contracts.py` 增至 5 项）；JS回归16项通过；`scripts/workbench_gate.sh` 通过。
- 当时的未处理项（按审查建议顺序保留）：C2/C3 服务层膨胀与 `json_safe`/`_numpy`/Sharpe 重复、C4 `storage.py` 四职责、C7 前端 924 行单文件、C9 容差分散、C10 测试分层。
  > 后续进展：C3/C9 与 C2 第一批见「第三轮重构：共享数值/DTO/序列视图」（`b03ecb3a`）；C4 见「存储拆分为基础层 + 三个域 mixin」（`638dbcea`）。仍未处理：C2 剩余编排、C7 前端拆分、C10 测试分层。
- 兼容：只改服务端内部行为与测试；`/v1/risk` 在配置缺失时由"静默给 238"变为显式 400，属预期的 fail-closed 收紧。

## 2026-09-26 — 文档整理与第三轮代码审查

- 来源：用户要求 review spec（删除冗余、修正错误信息）并 review 代码（架构、质量、实现手段）。
- 文档整理：①把 `ui-reference-20260925.md` 的留存取舍合并进 [工作台交互参考](archive/UX_RESEARCH_20260926.md)（新增"沿用取舍"一节，含 FreqUI/MLflow/QuantStats/W&B 的采纳结论与"不引入 Vue/PrimeVue"的前端取舍），删除原文件并更新索引入口；②[实施状态](IMPLEMENTATION.md) 中 12 段按批次的历史叙述压缩为"最近批次摘要"表（一句话状态 + 缺口），细节唯一保留在 CHANGELOG，消除两处重复维护；③修正过期事实：[量化能力差距扫描](archive/QUANT_GAP_SCAN.md) 的 Q1/Q2 状态改为"已接入（U20/U22）"并改写结论与后续顺序，[工作台交互参考](archive/UX_RESEARCH_20260926.md) 的 X1/X3 标注为已接入、X2 标为下一步。
- 代码审查：在 [第二轮审查记录](archive/review-20260926b.md) 追加"第三轮：代码架构、质量与实现手段"，给出 10 项发现（1 高、5 中、4 低）：月度复利的 `or 0.0` 真 bug、`WorkbenchService` 膨胀与收益抽取重复、`json_safe`/`_numpy`/Sharpe 三处重复、`storage.py` 四职责合并、风险年化参数静默回退、契约测试未覆盖新接口、前端 924 行单文件、死代码与容差分散、测试耗时分层；同时明确列出值得保留的做法（fail-closed、显式迁移、契约先改、脱敏一致、每域回归）与建议处理顺序。
- 影响：本次只改文档（含删除一个已合并的参考文件）与追加审查记录，不改任何实现；代码问题按 C1→C10 顺序待用户确认后处理。文件数：spec 文档 20 → 19。

## 2026-09-26 — U22：风险与绩效指标族

- 来源：用户确认继续按扫描顺序推进，Q2（风险与绩效）为下一步。
- 合同：[结果合同](RESULT_CONTRACT.md)新增「绩效与风险指标族」（公式、边界、缺月 null）；[核心规范](WORKBENCH_SPEC.md)补 U22 需求行并把覆盖区间更新为 U01—U22。
- 实现：`risk.py` 提供服务端指标族——总收益与年化（ppy 取配置 238）、波动、Sharpe、Sortino（仅下行标准差）、Calmar、最大回撤、回撤期（开始/谷底/恢复/深度/长度/状态）、VaR/CVaR（历史法）、正收益比例、偏度、峰度、最好最差单日、月度与年度复利矩阵；退化情形（离散度 <1e-12、无负收益、无回撤、尾部样本不足）返回分项不可用并给出原因，非有限值转 null。入口 `/v1/risk` 与 CLI `risk`，回测页新增"风险与绩效"卡。
- 验证：Python 106项测试105通过、1项环境隔离跳过（新增 `test_risk.py` 4项：已知回撤、CVaR 尾部、缺月 null、退化边界、HTTP/服务共用）；JS回归16项通过；浏览器实测真实 Qlib 运行：Sharpe 0.865、Sortino 1.402、Calmar 1.782、最大回撤 −4.18%、VaR −0.91%、CVaR −1.09%、3 个回撤期（2 恢复 1 未恢复），并显示未接入项"分红再投资与真实成本细分"。
- 限制：分红再投资与真实成本细分未接入；比较表尚未并排展示风险指标（当前只在回测页）；年化交易日取配置值，不额外假设。
- 兼容：只新增只读接口与 CLI 命令，以及回测页增量卡片；未改既有 DTO 字段。

## 2026-09-26 — U20/U21：验证口径与任务中心/命令面板

- 来源：用户确认按建议顺序落地 P0——量化侧先做验证口径，交互侧先做任务中心与全局搜索。
- 合同：新增专题 [验证口径](VALIDATION.md)（purged/embargo 折、唯一性权重、PSR、DSR、PBO 的公式与边界，A31/A32）；[核心规范](WORKBENCH_SPEC.md)补 U20/U21 需求行与 UI07（任务中心、统一对象表与保存视图、命令面板、索引边界）。
- 实现：①`validation.py` 提供 `purged_folds`（返回每折训练/测试索引与剔除占比）、`uniqueness_weights`（并发度倒数均值，输出有效样本数）、`probabilistic_sharpe`（偏度/峰度修正闭式）、`deflated_sharpe`（以试验次数估计期望最大 Sharpe）与 `pbo`（CSCV；完全相同的配置标记 `degenerate` 并提示不可区分）；收益优先取 `native.qlib.return`，缺失时按 `platform.equity` 日收益推导并标注来源。②`GET /v1/validation` 与 CLI `validate` 共用同一服务；比较页新增验证卡。③`GET /v1/attention` 汇总失败/中断执行、未入库结果、探针结果与取消请求中；顶栏"待处理 N（高 M）"胶囊与总览待处理卡。④`Ctrl/⌘ + K` 命令面板：索引命令、最多 100 个运行、最多 50 条研究与全部已入库因子，命中标签优先排序，并披露索引覆盖范围。
- 验证：Python 102项测试101通过、1项环境隔离跳过（新增 `test_validation.py` 8项：purge 不重叠与 embargo、并发度权重、PSR 闭式一致、DSR 更保守、PBO 三种构造与退化、单配置无 PBO、HTTP/服务共用）；JS回归16项通过（新增注意力胶囊/命令面板/验证卡用例）；浏览器实测：待处理 3 项（1 高 2 低）、命令面板打开与检索、验证卡显示两次真实 Qlib 运行的 Sharpe 0.056、PSR/DSR 0.731、purge 1.3%、有效样本 61.8/123，并提示同情景重复运行 PBO 不具区分意义。
- 限制：仍保留"缺少前瞻/实盘样本"的未接入项；命令面板为有界索引而非全库检索；风险指标族（Sharpe/Sortino/Calmar/VaR/CVaR 全量）、统一对象表与保存视图（UI07 其余部分）尚未实现。
- 兼容：只新增只读接口与 CLI 命令，以及比较页/顶栏/总览的增量元素；未改既有 DTO 字段与数据语义。

## 2026-09-26 — Spec 刷新与外部参考扫描（量化能力、工作台交互）

- 来源：用户要求「刷新 spec」，并分别检索"量化"与"工作台"两个方向看还缺什么、参考他人做法（GitHub 为主要入口）。
- 规范刷新：核心规范目标覆盖区间更新为 U01—U19（U18/U19 已在前一批落地）；README 运行证据行补入比较分组与因子层，并把"验证口径与风险指标族"列为未接入；专题索引新增两份参考文档。
- 新增参考（研究输入，非合同）：[量化能力差距扫描](archive/QUANT_GAP_SCAN.md) 与 [工作台交互参考](archive/UX_RESEARCH_20260926.md)。两份文档都注明 star/推送时间快照、只引用可核对的项目结构、不复制代码、不据此声称能力已实现。
- 量化侧结论（除数据外）：P0 是先补**验证口径**（purged/embargo 交叉验证、样本权重、deflated Sharpe、回测过拟合概率）与**风险绩效指标族**（Sharpe/Sortino/Calmar、VaR/CVaR、回撤期、月度热力图）；P1 是行业中性 IC 与因子自相关、分位多空净值、组合约束优化、参数扫描；P2 是超参搜索、归因、特征注册与数据校验规则库、容量与拥挤度。依据来自 alphalens-reloaded（IC/换手/分组三块）、mlfinlab（`cross_validation`/`sample_weights`/`backtest_statistics` 目录）、quantstats 与 pyfolio（绩效与风险）、Riskfolio-Lib、vectorbt、optuna、pandera/feast/lakeFS。
- 工作台侧结论：P0 是**任务中心（待处理事项）+ 统一对象表（运行/执行/研究/因子同一张可过滤表 + 标签 + 保存视图）+ 全局搜索/命令面板**；P1 是对比增强（散点/平行坐标）、URL 状态可分享、全局任务条、报告导出；P2 是密度切换与键盘导航、页面引导、颜色语义 token 化。依据来自 MLflow 运行表与比较、W&B workspaces/保存视图/sweep、Grafana 与 Superset 的 dashboard 组合、FreqUI 的前后端边界、QuantStats tear sheet 与 alphalens 报告结构。
- 影响：本次仅新增参考文档与规范索引/覆盖区间修正，不改需求、不改实现、不新增能力声明；候选能力等用户确认后再进入需求表与验收。

## 2026-09-26 — U18/U19：比较分组与因子层（面板入库、统计、重叠性、增量）

- 来源：用户明确「训练/研究/回测三类数据不能做全量比较，跨组只并排；因子层要做；因子面板要作为一类数据入库」，并确认"重叠性"指相关性/共线性/冗余度、正交性、IC 序列相关、持仓重叠与拥挤度这一族。
- 合同：新增专题 [因子层：因子实体、面板与分析](FACTOR_ANALYSIS.md)（分组规则、面板格式与边界、平台计算收益标签、单因子统计、重叠家族、未接入项、A28—A30）；[核心规范](WORKBENCH_SPEC.md)补 U18/U19 需求行与 README 索引入口；[结果合同](RESULT_CONTRACT.md)加入分组与身份分层衔接。
- 实现：①`metrics.metric_group()` 登记回测白名单，训练/研究/其他只降级不升级；`assess()` 对非回测组追加 `group_only_side_by_side:<组>` 且不排名，比较表行首显示组标签与"只并排"原因。②平台库 schema 3→4 新增 `factors`/`factor_panels`，面板按内容哈希不可变存入对象库，边界 dates≤2000 / instruments≤2000 / cells≤400000 / 16MB，重复导入复用、内容变化产生新面板。③`factors.py` 实现横截面 IC 与 RankIC、Newey-West t、双侧 p、BH-FDR、分位差与单调性、秩换手、因子值相关矩阵、VIF 共线（含完全共线标志）、IC 序列相关、正交 IC 与等权组合增量；非有限值在 DTO 中转 `null`。④收益标签由平台按 `close*factor` 从同一内容版本快照计算（`r=close_{t+h}/close_t-1`）。⑤RD-Agent 导出自动发布会话因子面板。⑥新增 `/v1/factors`、`/v1/factors/{id}`、`POST /v1/factors`、`/v1/factor-analysis` 与 CLI `factors`/`factor`/`import-factor-panel`/`factor-analysis`，界面新增"因子"页。
- 验证：Python 94项测试93通过、1项环境隔离跳过（新增 `test_factors.py` 10项：面板校验/边界/缺测不填0、幂等与内容敏感、快照校验失败即拒、收益与 IC 的已知答案、相关与 VIF、正交与增量、FDR 单调、JSON 合规、HTTP 同源与 CLI/HTTP 共用服务）；JS回归15项通过（新增因子页与分组用例）；真实数据：RD-Agent 导出发布10个因子面板，5因子统计与相关矩阵合理（mom_5d↔mom_20d +0.47、ret_1d_reversal↔mom_5d −0.41、vol_ratio_5d 换手1.059），跨会话重复因子被识别（vol_10d↔Vol10 1.00、mom_20d↔Rev20 −1.00），持仓重叠与拥挤度返回 `not_available`。
- 限制：因子集合默认取同一数据集版本下的全部因子（按实验挑选集合待补）；持仓重叠、拥挤度与因子衰减的完整换手成本模型未接入；`numpy` 已声明为可选依赖 `analysis`，缺失时分析返回明确错误而不是静默降级。
- 兼容：schema 3→4 只新增因子表，历史 runs/revisions/attempts/imports 不改写；比较响应新增 `group`/`group_label` 与 `group_only_side_by_side:*` 原因属增量；训练类指标的排名行为由"可排名"变为"只并排"（既有回归 R05 已按新语义更新）。

## 2026-09-26 — 第二轮审查修复：身份分层、逻辑内容摘要与跨引擎比较

- 来源：用户要求按[第二轮审查](archive/review-20260926b.md)的建议顺序修复，并"以稳为主"。审查发现 2 项严重（身份模型、数据集身份链）、2 项高（UI 引擎分支、比较页结论）、5 项中、6 项低。
- 合同：[结果合同](RESULT_CONTRACT.md)新增「身份分层」：数据内容身份、执行口径身份（`execution_id`）、评估口径身份（`evaluation_id`）与**研究实验身份**（`experiment_id`，允许不同并作为实验变量列出）；[核心规范](WORKBENCH_SPEC.md)COMPARE01 指向该分层，UI06 增加配色共存规则，API02 补齐比较/执行/观测接口枚举，需求表补记 U16 并把覆盖区间改为 U01—U17；[执行层规范](EXECUTION.md)§5 补 EXEC09/EXEC11 验收行；IMPLEMENTATION 的 M0 交付改为"键集合冻结 + 路由覆盖已落地、完整 JSON Schema 仍是缺口"；CN 审计补记数据身份机制。
- 实现（按 B 组顺序）：①`scenario_identities()` 拆分身份，`comparison_context()` 对历史记录现算拆分身份（记录不完整则身份留空而非编造），比较与比较表用 `assess()` 共用同一口径且不再逐行重读 revision；②快照摘要改为**逻辑内容摘要**（只覆盖数据文件），RD-Agent 导出写入同一摘要（本机与容器快照均为 `eb27e8cc…`），并由 `rdagent_snapshot_path()` 统一路径；③执行目录新增 `result_destination`、运行展示标题在服务端合成、Qlib 导入日历改用情景日历、金额序列补 `currency`；④比较页顶部改为"N/M 行可排名"并显示实验变量；⑤`/v1/runs/{id}/revisions` 有界分页、widget 已注册未实现返回 `unsupported`；⑥UI 测试新增 strict DOM 模式（缺元素即失败）、stub 进程按进程组清理。
- 验证：Python 83项测试82通过、1项环境隔离跳过（新增`test_review2_fixes.py` 5项覆盖分页、展示标题、widget 语义、结果去向、单次加载）；JS回归14项通过；`scripts/workbench_gate.sh`通过。**跨引擎比较实测**：Qlib 运行`7fa46b8f`与 RD-Agent 运行`d6c0c4b2`（同一情景、同一内容摘要）在比较表得到4行可排名——期末权益/首末变化/最大回撤（越高越好）与累计成本（越低越好）各标注最优/最劣，界面显示4个最优、4个最劣单元与文字标记，顶部显示"4/9 行可按统一口径排名"，换手率与额外行保持中性。
- 限制：跨实验变量的费用情景排名口径未定义（当前作为实验变量并排展示）；正式数据目录接入后由供应商版本或内容摘要替代本地摘要机制；完整 JSON Schema、外部 CI、实时回放与第二真实引擎仍未实现。
- 兼容：新增派生身份字段与 `experiment_variables`/`result_destination`/`display_title` 均为增量；历史 revision 与旧证据不改写，缺少内容版本或身份的旧对象继续保持不可排名；`/v1/runs/{id}/revisions` 响应新增 `next_cursor`（由 `{"items"}` 扩展），CLI `revisions` 新增 `--limit/--cursor`。

## 2026-09-26 — U17：比较表（一行一指标、列内配色）与数据集内容身份

- 来源：用户反馈比较页数据分散在不同卡片、不直观，要求一行一个指标、每列一个运行，并用颜色区分优劣（红=最优、绿=最劣）。
- 合同：[核心规范](WORKBENCH_SPEC.md)新增需求U17与UI06（结构、配色、非唯一载体、服务端计算、未知与缺失、并列与1e-9容差、与COMPARE01的关系）；[结果合同](RESULT_CONTRACT.md)新增“数据集内容版本与评估口径”：`dataset.version`记录物化快照的文件内容摘要，CN适配器把`evaluation_id`映射为情景指纹，并重申配置指纹不能代替数据内容版本。
- 实现：新增`/v1/compare/table`（服务端给出方向、最优/最劣、行级原因）与CLI `compare-table`；比较页新增表格卡（表头含运行标识与数据版本，单元格红=最优/绿=最劣并带文字标记，未通过行写明原因），逐运行明细与曲线折叠到表下。为使比较可用，补齐`dataset.version`（快照`content.json`内容摘要→编译`dataset.json`→导入记录）、CN `evaluation_id`，并修复金额类原生序列缺少`currency`导致成本行永远不可比的问题。
- 验证：Python 78项测试77通过、1项环境隔离跳过（新增`test_compare_table.py` 9项：最优/最劣、并列、浮点容差、未知方向、缺数据版本、缺评估口径、指标选择与聚合、内容摘要稳定性、导入器币种与评估口径）；JS回归13项通过；浏览器实测比较表11行、两次同情景运行的数据版本摘要一致（`58dfbf22…`）、未通过行原因可见、明细区默认折叠。
- 限制：同情景两次运行的数值差异落在容差内，因此当前真实数据不会出现着色（这是刻意的：把1e-10噪声标成“最优”会失真）；旧历史revision未记录数据版本，继续保持不可排名。跨引擎或跨研究参数的比较需要把执行/评估身份与研究实验身份拆分（见同批审查记录）。
- 兼容：新增只读接口与CLI命令，既有`/v1/compare`与单指标比较不变；`dataset.version`与`evaluation_id`只对新导入生效，历史revision不改写；`content.json`写入数据快照目录（本机数据，不入库）。

## 2026-09-26 — U16：历史面板与启动表单可用性修复（用户报告四项）

- 来源：用户逐条反馈——①侧栏“最近运行”展开与展开无差别；②研究中心历史记录的搜索栏在滚动区内被一起滚走；③看不懂三种执行入口分别做什么；④选择 RD-Agent 入口后页面自动刷新又跳回 Qlib。
- 合同：[核心规范](WORKBENCH_SPEC.md)UI05新增“固定操作栏、折叠可见性、状态保留”三行要求；[执行层规范](EXECUTION.md)EXEC09新增“逐入口说明用途/依赖/产出/结果去向/耗时”与“自动刷新不得重置选择或抢焦点”。
- 修复①：侧栏原本在100vh内被品牌与导航压缩到可见33px，展开只改DOM不改变可视区域。改为列表固定可视高度（折叠240px、展开62vh），侧栏自身滚动，展开后可见行数由3增到5，按钮显示“共17条，当前显示8条/17条”；导航与品牌间距同步收紧。
- 修复②：历史卡片改为“子tab → 固定操作栏（搜索/翻页/折叠）→ 面板内滚动区”，搜索与翻页不再位于滚动容器内；滚动位置在重渲染后恢复。
- 修复③：三种入口各自新增一句话用途与问号说明（`exec.kind.*`：做什么、需要什么、产出与去向、大致耗时、探针性质），表单下方按当前选择显示摘要。
- 修复④：入口选择写入`state.executionKind`并渲染`selected`；选择变化不再触发整页重渲染，5秒自动刷新也不会重置；备注输入框获得焦点时暂停自动刷新。
- 验证：Python 69项测试68通过、1项环境隔离跳过；JS回归12项通过（新增2项：入口说明齐全且选择跨重渲染保留、搜索与翻页位于滚动区之外）；`bash scripts/workbench_gate.sh`通过。浏览器实测：侧栏折叠240px/8条/可见3行→展开446px/17条/可见5行且页面不增高；研究tab搜索栏在面板`scrollTop=510`时仍可见；选择`rdagent.factor.loop`后经历两次5秒自动刷新与一次视图往返仍保持，反馈文案同步更新。
- 限制：折叠与滚动仍是纯前端展示控制，不放宽ARC07分页上限；入口耗时数字来自本机实测，其他机器可能不同，界面标注为“本机实测”。

## 2026-09-26 — API03：机器可读契约与一键交付门禁

- 来源：治理规范记录的M0缺口“完整JSON Schema/OpenAPI一致性”，以及用户要求继续补全缺口（行情真实接入除外）。
- 合同：[核心规范](WORKBENCH_SPEC.md)新增API03：`/v1`路由覆盖、核心只读DTO键集合冻结、Attempt DTO脱敏断言、门禁脚本，并明确本版不含完整JSON Schema校验器。
- 实现：新增`tests/test_contracts.py`（4项）与`scripts/workbench_gate.sh`（依次运行工作台Python与JS套件）。
- 验证：Python 69项测试68通过、1项Qlib环境隔离跳过；JS回归10项通过；`bash scripts/workbench_gate.sh`整体通过。契约测试在本轮自动入库DTO变更（`result_import`由字符串改为对象）后仍需显式更新，验证了“漂移即失败”的门槛作用。
- 限制：这是本地与代理执行的门禁，不是外部CI服务；字段级语义仍靠专题规范与回归测试；完整机器Schema校验器仍未实现。

## 2026-09-26 — U15：历史子tab内滚动与折叠、执行结果自动入库、Attempt 观测

- 来源：用户反馈历史数据过多导致整页下滚，要求页面内嵌子tab、在tab内滚动并折叠历史记录；同时要求继续补全缺口（行情数据真实接入除外）。
- 合同：[核心规范](WORKBENCH_SPEC.md)新增需求U15与UI05（子tab切换、面板内滚动、默认折叠、折叠不改事实、不放宽ARC07分页边界）；[执行层规范](EXECUTION.md)把结果自动入库纳入范围并新增EXEC12（触发条件、状态取值、不得降低校验、不得重复发布、显式重试），EXEC10细化为HTTP与Attempt两块及分母/窗口/单列语义，§4限制改为“只覆盖声明导入器的入口”；[结果合同](RESULT_CONTRACT.md)新增自动入库与ImportReceipt小节。
- 实现：平台数据库schema 2→3显式迁移新增`imports`回执表（迁移前备份本机库，历史runs/revisions/attempts不改写）；`ExecutionService`注入导入端口并在成功终态触发自动发布，新增重试与统计接口；`adapters/attempt_import.py`复用`qlib_mlflow_v2`校验（来源冲突拒绝、脱敏、情景指纹核验、只读源库）；CLI新增`import-attempt`与`attempt-stats`，HTTP新增`POST /v1/executions/{id}/import`与`/v1/observability.attempts`；界面新增历史子tab+面板内滚动+默认折叠（侧栏最近运行同样只在自身区域滚动）、执行记录入库状态与“重试入库”、系统页Attempt观测卡。
- 验证：Python 65项测试64通过、1项Qlib环境隔离跳过（新增：自动发布与回执、同内容复用、失败保留原因、无候选、RD-Agent导入缺口、重试幂等与来源403、统计单列与空窗口无样本、v2→v3迁移、观测双块）；JS回归10项通过（新增2项U15）；真实Qlib Attempt `74423ed7`退出码0后自动发布运行`1085b527`（revision`021705eb`、回执`568213c7`），重复`import-attempt`返回`already_imported`；浏览器实测面板内PageDown使`scrollTop`由0到618而`window.scrollY`保持569.5，研究子tab默认8行、展开20行并标注全库33条，系统页显示失败率0%（分母6）、已取消2、P95 209.2秒。
- 限制：自动入库只覆盖Qlib CN合成行情入口；RD-Agent结果为研究快照，仍需可信离线导出后才入库；CN数据集身份暂用常量`cn-current-synthetic`并在代码与文档标注，正式数据目录接入后替换；无调度、并发上限与资源硬限制；实时回放、机器Schema/OpenAPI一致性与第二真实引擎仍未接入。
- 兼容：`outcome.result_import`从字符串改为对象（状态、run/revision、回执、原因），历史Attempt保留原字符串投影不改写；`/v1/observability`保留既有HTTP字段并新增`attempts`块；新增`imports`表与同源校验的写接口；schema 3需要重启工作台服务加载。

## 2026-09-26 — U14：界面内说明（问号图标：悬浮摘要 + 点击弹窗）

- 来源：用户反馈按钮与数据已经变多、界面不易上手，要求补充说明；同时明确不要把这些解释铺在页面上，改用小问号图标，悬浮给解释、点击弹窗给解释。
- 合同：[核心规范](WORKBENCH_SPEC.md)新增需求U14与UI04：入口形态（问号图标，默认不展开、不改变版面）、悬浮/聚焦摘要与点击弹窗、内容来自受版本控制的说明注册表且键稳定、说明不得把未接入能力写成已实现或把未知写成0、可访问性与焦点回归。
- 实现：`ui/app.js`新增`HELP`说明注册表（32条，含标题、悬浮摘要、完整正文与规范依据）与`help()/openHelp()/closeHelp()/bindHelp()`；入口覆盖8个视图页头、来源标记图例、全部卡片（标题→说明键映射`cardHelp`）、执行记录的状态/结果/操作列、日志尾部与比较页单运行卡片；提示层用视口内定位，避免被表格滚动容器裁切；弹窗支持关闭按钮、点击遮罩与Esc关闭，并把焦点交还触发图标。
- 验证：JS回归8项全部通过（新增U14两项：说明键可解析、无孤儿卡片键、每条说明必须有标题/摘要/正文/规范依据；悬浮摘要与弹窗共用条目且开关与焦点回归正确）；Python 55项测试54通过、1项Qlib环境隔离跳过；浏览器实测8个视图页头与图例均出现问号、键盘Tab可达、聚焦即显示摘要、回车或点击打开弹窗、Esc/关闭按钮/遮罩点击均可关闭且焦点回到触发图标，控制台无错误。
- 限制：说明文案属于展示层，随UI资源版本发布（当前`app.js?v=15`、`style.css?v=8`）；未实现多语言、逐条隐藏或“不再提示”偏好；悬浮与聚焦共用同一条样式规则，自动化环境无法移动真实指针，悬浮路径由键盘聚焦等价验证。

## 2026-09-26 — U13：执行层（Attempt、隔离进程、取消与幂等）

- 来源：用户确认按优先级推进“执行层——Attempt 持久化 + 界面启动/停止研究 + 取消与幂等”，把工作台从只读看板变成可执行的研究平台。
- 合同：新增[执行层规范](EXECUTION.md)（EXEC01—EXEC11），明确Attempt状态机、执行器端口、独立进程、幂等键、取消确认语义、前置条件、写接口来源校验、DTO脱敏与CLI/UI共用服务；WORKBENCH_SPEC的RUN02/API02改为引用该专题。
- 实现：平台数据库schema 1→2显式迁移新增`attempts`表（保留既有runs/revisions）；`ExecutorPort`与`SubprocessExecutor`；`qlib.cn_synthetic_backtest`、`rdagent.factor.baseline`、`rdagent.factor.loop`三个入口；`/v1/executions`系列与CLI `execute/executions/execution/execution-log/cancel/execution-catalog`；研究中心提供启动、取消、逐项前置条件、结果摘要与脱敏日志尾部，并在启动成功后轮换幂等键，使同一条目可再次启动而不被上一次静默去重。
- 隔离：Qlib每次Attempt在新的工作目录运行并写入自己的`mlflow.db`；RD-Agent只写其Git忽略目录；工作台进程不导入Qlib/RD-Agent。前置条件覆盖运行时、聊天与embedding、数据快照指纹、日历、费用情景、容器资源与Attempt存储；缺任一项拒绝提交。
- 验证：工作台55项测试54通过、1项Qlib隔离跳过（新增17项执行层回归：幂等、崩溃interrupted、取消确认、取消竞争清除失败标签、终态优先、来源403、前置条件409、读取不启动、v1→v2迁移、DTO脱敏）；6项JS回归通过；两次真实Qlib合成行情Attempt退出码0（有效IC123天、交易122天）且第二次经显式导入成为平台运行；RD-Agent基线探针退出码0（19项指标、快照指纹一致）；单轮loop探针退出码0、耗时3分29秒、5个因子、因子值8832行、19项指标、质量检查`passed_checks`（有效IC123天、交易120天），并同步1个研究会话。
- 浏览器验证：研究中心经界面启动2次真实Qlib Attempt（均退出码0）并取消1次（确认落`cancelled`）；取消竞争修复前，确认取消会残留`process_lost_without_exit_evidence`标签，已修复并加回归；启动成功后界面轮换幂等键，同一条目可再次启动。
- 限制：结果不自动入库（`result_import=manual_import_required`）；无调度、并发上限与资源硬限制；日志为有界尾部；真实数据目录、A16/A17、Attempt级失败率统计与云数据库仍为缺口。
- 兼容：不迁移或覆盖历史revision/对象；写入`attempts`表与新增API，既有读取接口与DTO字段保持；工作台服务需重启以加载执行层。

## 2026-09-26 — R01—R12修复及S01—S06合同收敛

- 来源：用户明确要求修复上一轮审查。先补RESULT_CONTRACT与冲突条款，再落地实现；没有删除未实现阶段来制造全量合规。
- 修复：分实验导出、发布前脱敏、源模拟证据冲突拒绝、MLflow临时副本、严格比较、全量摘要/有界分页、查询错误与缺测、空序列、跨时区排序、闭合CN嵌套schema；旧请求不得覆盖新页面选择。
- 验证：工作台38项37通过1隔离跳过；根Qlib环境6项CN通过；较新MLflow真实导入1项通过且源库哈希不变；5项JS回归通过。浏览器检查首尾分页、缺测、研究详情与revision锁定跳转。
- 数据：先备份SQLite/研究快照，增量重建31条实验观察、5份报告；旧8个结果对象哈希不变。旧会话URL转分轮导航，旧v1平台revision标记归属未复核、禁止排名。已配置凭据匹配扫描为0，没有调用付费模型。
- 兼容：导入器v2、新结果时间UTC规范化、DTO新增摘要与中立比较证据；数据库schema不迁移，历史对象不覆盖。工作台服务已重启加载修复。
- 范围与限制：[修复记录及A01—A23](archive/FIXES_20260926.md)、[冻结验证摘要](evidence/20260926-fixes-validation.json)。完整机器Schema/CI、实时、执行器、第二真实引擎/数据库、布局持久化继续保留为缺口。
- Git：本批完整检查点按GOV02提交并push至origin当前分支，不合并主分支、不向上游推送。

## 2026-09-26 — 规范与实现一致性审查

- 来源：用户要求review现行spec的合理性/正确性及实现符合程度；审查代码基线为`89a3eb7`。
- 结论：架构方向合理；登记6类规范问题、6项P1及6项P2实现缺陷，全部保留待修复状态。涉及ARC02/06/07/08、METRIC、COMPARE01、AGENT/RW、CN04和GOV-STORAGE等要求。
- 交付：[完整审查](archive/review-20260926.md)、临时夹具复现程序、冻结JSON证据、入口及实施状态提醒。未改产品逻辑或通过降低spec门槛消除问题。
- 验证：原有工作台25项测试24通过1跳过；根Qlib环境6项CN测试通过。隔离反例复现跨轮混合、发布前脱敏缺口、模拟改标、比较错误、空态/时间/缺测/配置问题；JS VM验证吞错/分页/图表缺口。MLflow仅读取源库副本，较新客户端使副本schema变化，源库SHA256保持一致。
- 限制：没有证明真实凭据已经泄漏或所有历史结果均错误；未运行付费研究、外部规则复核和本轮浏览器视觉验收。历史6288项数值审计不覆盖上述边界。
- 兼容：不迁移数据库、不覆盖历史revision；按GOV02将审查资料提交推送至用户fork现有工作分支，后续修复单独形成检查点。

## 2026-09-26 — GOV02 / U12：重大修改必须提交并推送

- 来源：用户要求用Git管理每一步演进，每次重大修改commit并push一次。
- 决定：纳入AGENTS和治理规范，完成验证及spec同步后向用户fork的origin工作分支提交推送，不重复确认、不强推、不推上游。
- 本次检查点：将此前尚未提交的工作台、A股配置、RD-Agent适配、来源审计及spec治理保存为首个完整定制基线；不伪造分阶段历史。
- 验证：待提交74个新增文件约1.06MB，未发现已配置凭据或大文件；工作台25项测试24通过、1项隔离跳过，根Qlib环境6项CN测试全部通过；JavaScript语法检查通过。
- 兼容：不改变上游源码、原实验数据或工作台数据库，不代表自动合并或部署。

## 2026-09-26 — GOV01 / U11：确立spec最高项目优先级

- 来源：用户明确要求将spec作为长期演进核心锚点，并保护重要信息。
- 决定：新增SPEC_GOVERNANCE，根AGENTS强制先读spec、先更新变更语义、同步实现与验收；冲突不能通过放宽要求解决。
- 保护范围：来源分级、能力限制、历史证据、配置假设、引擎解耦、上游演进和数据库审计隔离。
- 验证：本轮为文档治理变更，仅核对内容一致性与本地链接；没有改运行逻辑，不增加能力完成声明。
- 限制：尚无自动CI治理门禁；本机Git忽略的运行日志不视为永久证据。脱敏摘要复制到evidence，原日志路径仅用于本机追溯。
- 兼容：不改API、结果schema、数据库或历史revision；不创建Git提交。

## 2026-09-26 — U10：来源与能力声明纠正（追溯登记）

- 来源：用户担心界面存在臆造数据或把新增能力误作上游原生能力。
- 决定：分开原生记录、工作台计算、定制检查、Agent意见、工作台规则、实测遥测和手写fixture；未接入/受限显式标记。手写fixture禁止研究排名。
- 证据：7条引擎运行6288项对照无不一致，另1条手写样本；25项测试24通过、1项环境隔离跳过。详见PROVENANCE_AUDIT及evidence/20260926-source-audit.json。
- 限制：所有行情均模拟；训练历史未完整逐值审计；结果指纹、规则指纹不证明真实市场有效性。
- 修复：较新MLflow读取引发实验库自动迁移；备份后在副本恢复兼容并逐表核对，随后审计仅读源库副本，源DB前后SHA256一致。
- 兼容：来源分类为读取投影，不覆盖历史revision；新回撤定义命名改为observed_equity，旧结果的真实计算范围用注解说明。

## 2026-09-26 — U09：研究结果与过程闭环（追溯登记）

- 来源：用户要求每次RD-Agent研究可查看结果和过程，并要求工作台可观测、可比较、辅助决策。
- 实现：27条历史会话导出，5条有报告并进入通用结果库；因子/代码/阶段/反馈详情、可比性检查、规则摘要、HTTP进程遥测。
- 限制：离线摘录非实时监控；无退出证据不推断成功；执行器/实盘/正式数据目录未接入。
- 合同与证据：RESEARCH_WORKBENCH、IMPLEMENTATION。不得把当时快照数量当作后续固定事实。
