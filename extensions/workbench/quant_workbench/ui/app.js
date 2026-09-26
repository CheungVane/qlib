const initialQuery = new URLSearchParams(location.search);
const hasCompareQuery = initialQuery.has('compare');
const HISTORY_PREVIEW = 8;
const historyTabParam = initialQuery.get('history');
const state = {renderGeneration:0, revision: initialQuery.get("revision"), seriesOffsets:{}, runs: [], selected: initialQuery.get('run'), compareIds: (initialQuery.get('compare') || '').split(',').filter(Boolean), researchId: initialQuery.get('research'), researchOffset:0, researchQuery:'', search: '', executionKey:null, executionKind:null, helpTrigger:null, helpBound:false, historyTab: historyTabParam==='research'?'research':'attempts', historyExpanded:false, historyScrollTop:0, attemptCursor:null, attemptCursors:[], runsExpanded:false, overviewExpanded:false, factorGroup:null, view: location.hash.slice(1) || 'overview'};
const titles = {overview:['总览','研究运行、数据状态与系统观察'],backtest:['回测','权益、回撤、费用与来源证据'],training:['训练','指标曲线、阶段状态与来源证据'],compare:['比较','并列查看运行，先核对数据与指标口径'],agent:['研究中心','研究结果、因子内容、过程追踪与下一步'],factors:['因子','单因子统计、重叠性与增量贡献'],live:['实时','行情连接与数据新鲜度'],data:['数据','数据集来源、覆盖与质量'],system:['系统','任务状态、请求与错误观察']};
const HELP = {
 'page.overview':{title:'总览怎么读',summary:'先看来源与能力边界，再看最近研究与已采集的观察指标。',ref:'UI01 / ARC08',
  body:['总览把最近运行、研究记录和当前真正采集到的指标放在同一页。','未接入的指标显示“未接入/未记录”，不用 0 代替；模拟行情始终带标记。'],
  points:['左侧“最近运行”可直接跳到回测或训练详情。','每个卡片右上角的问号给出该卡片的口径与限制。']},
 'page.backtest':{title:'回测页怎么读',summary:'权益、回撤、费用按来源分别标注，先核对口径再看数值。',ref:'UI01 / COMPARE01',
  body:['页面按“运行概况 → 来源核查 → 规则摘要 → 权益曲线 → 成本与换手 → 原始证据”的顺序排列，逐层深入。','曲线按原始时间轴绘制，缺测处断线而不是补零；分页显示当前点位区间与是否降采样。'],
  points:['权益、回撤等派生指标标注“工作台计算”，引擎原始值标注“引擎原始记录”。','费用与换手请回到原运行配置核对撮合口径。']},
 'page.training':{title:'训练页怎么读',summary:'这里只显示已记录的指标与阶段状态，单点 loss 不等于完整学习曲线。',ref:'UI01 / ARC06',
  body:['训练页展示引擎记录的训练/验证指标与阶段状态。','指标只有单点记录时会标注“能力受限”，不能据此判断完整学习过程。']},
 'page.compare':{title:'比较页怎么读',summary:'并排查看总是允许；叠图与排名要通过口径检查。',ref:'COMPARE01',
  body:['比较分三级：①并排查看；②叠图需要单位与轴一致；③排名需要口径检查通过。','检查不通过时只做并列查看，并列出原因，例如日期窗口、初始资金或数据版本不同。'],
  points:['模拟与真实结果不会静默混入同一排名。','每个运行单独绘图，保留各自时间轴，不按点位硬叠加。']},
 'page.agent':{title:'研究中心怎么读',summary:'上半区是执行（真实进程），下半区是研究记录与过程快照。',ref:'EXECUTION.md / RESEARCH_WORKBENCH.md',
  body:['研究中心可以启动、取消隔离进程执行；“历史记录”里用子tab切换执行记录与研究记录，列表在面板内滚动并默认折叠。','执行记录含状态、退出码、入库结果与脱敏日志尾部；研究记录来自已导出的过程快照。'],
  points:['Qlib 回测成功后平台会自动发布结果并写回执；没有导入器的入口显示“结果需显式导入”。','标记“集成探针”的入口用于验证链路，不代表研究成果。']},
 'page.factors':{title:'因子页怎么读',summary:'按因子（而不是按运行）看预测力、显著性与重叠性。',ref:'FACTOR_ANALYSIS.md',
  body:['因子页回答“这个因子有没有用、和别的因子有多像”，与“某个回测跑出什么组合结果”是两个层次的问题。','只有同一数据集内容版本、同一日历的因子才能一起分析；不同版本需要分别查看。','所有数字都是工作台计算，附公式、样本区间与数据版本；未接入的指标会写明缺什么数据，不用 0 代替。']},
 'factor.stats':{title:'单因子统计口径',summary:'Rank IC、t 值、p 值、FDR、分位差与换手，都是平台计算。',ref:'FACTOR_ANALYSIS.md §4.1',
  body:['Rank IC：每个交易日横截面秩相关（因子 vs 未来收益）的均值；IC 为 Pearson 版本。','显著性：t = 均值 /（Newey-West 标准误 / √N），滞后取 h−1；p 为双侧正态近似。因子同时检验很多个时看 FDR q 值，只用 p 值容易“试出显著”。','分位差：按因子分 5 组的平均未来收益 Q5−Q1，并判断分组收益是否单调；单调性比单点数字更能说明方向是否稳定。','换手：相邻交易日横截面秩的变动；换手接近 1 表示因子排序几乎每天翻转，交易成本会很敏感。','收益标签由平台按 close（含复权因子）计算 r=close_{t+h}/close_t−1，只用同一数据内容版本的快照。']},
 'factor.overlap':{title:'重叠性怎么读',summary:'相关、共线性、冗余、正交与增量；持仓重叠和拥挤度当前未接入。',ref:'FACTOR_ANALYSIS.md §4.2',
  body:['因子值相关性：逐日横截面秩相关的均值，回答“两个因子是不是在排同一批股票”；|相关| ≥ 0.7 标记为高重叠。','共线性：由相关矩阵算 VIF，>10 说明该因子与其它因子高度共线（冗余），不构成独立信息；完全共线会单独标明。','正交增量：把新因子对已有因子横截面回归后取残差再算 IC，回答“去掉已有因子能解释的部分，还剩多少信息”。','组合增量：等权合成（横截面标准化后取均值）中加入/去掉该因子的 IC 变化；接近 0 说明被已有因子解释。','未接入：持仓重叠需要逐日持仓明细，拥挤度需要市场层面的因子使用数据；两者都显式标注而不是填 0。']},
 'page.live':{title:'实时页为什么是空的',summary:'行情流尚未接入，没有连接记录时不显示 0。',ref:'LIVE01 / UI01',
  body:['实时行情、延迟与缺口能力属于后续阶段；当前没有数据流会话或采集记录。','按规范，无采集样本时不显示 0%，而是明确说明未接入。']},
 'page.data':{title:'数据页怎么读',summary:'这里展示当前结果的来源与情景证据，不是供应商数据目录。',ref:'ARC06 / DATA01—05',
  body:['数据页显示选中运行的数据集身份、内容版本、日历与执行情景指纹。','情景指纹描述配置，不能代替行情内容版本；供应商数据目录与真实 PIT 校验尚未接入。']},
 'page.system':{title:'系统页怎么读',summary:'这里只有工作台 HTTP 服务的实测遥测，不代表引擎错误率。',ref:'OBS01 / OBS02',
  body:['系统页展示本工作台服务的请求错误率、请求数量与响应耗时，并给出分母、窗口与采集覆盖。','任务失败率、引擎错误率与 Attempt 失败率是不同指标；本页不代替它们。']},
 'source.legend':{title:'来源标记怎么读',summary:'来源回答“数值从哪来”，与行情是否真实、能力是否具备是三件事。',ref:'PROVENANCE_AUDIT.md / ARC04 / ARC08',
  body:['引擎原始记录：数值来自引擎产物；工作台计算：由平台按明示公式派生；定制检查：本项目的规则检查结果；Agent生成意见：模型文本，非平台结论；手写演示样本：人工整理，禁止用于研究排名。','能力受限与未接入表示该项能力或数据通道当前不具备，界面保留位置但不造假数据。','未记录与真实零值必须区分：未记录显示为“未记录/未获取”，不补 0。']},
 'provenance.panel':{title:'来源核查怎么看',summary:'逐字段列出依据与限制，原始记录不等于行情真实。',ref:'ARC04 / ARC06',
  body:['面板把每个字段的来源类型、依据与限制列出来，用来判断一个数值能不能用于决策。','“引擎原始记录”只说明数值来自引擎产物，不说明行情真实，也不说明使用了未修改的上游执行器。']},
 'review.panel':{title:'规则摘要与待验证事项',summary:'这是工作台固定规则提示，不是引擎结论，也没有额外调用模型。',ref:'RESEARCH_WORKBENCH.md',
  body:['结论、数据依据与缺口、规则建议都由固定规则生成，可复现且不发聊天请求。','“规则建议（需自行验证）”是提示项，不是平台给出的投资建议。']},
 'metric.overview':{title:'运行概况里的指标',summary:'四个指标分别来自何方、各自的边界在哪里。',ref:'RESULT_CONTRACT.md',
  body:['期末权益：报告区间最后一个有效观测点的权益，不推算缺失区间；币种未记录时显示“币种未记录”，不默认人民币。','首末观测权益变化：（末点 − 首点）/ 首点，由工作台派生，只覆盖首末之间的观测，不等于完整区间收益。','最大观测权益回撤：在已记录观测点上取值，命名强调“观测”；观测间距越大越可能低估真实回撤。','引擎：显示引擎标识，运行时版本缺失就显示未知，不用当前环境版本回填。']},
 'metric.engine':{title:'引擎与运行时版本',summary:'引擎标识与版本分开显示；版本未知即显示未知。',ref:'ARC06',
  body:['不同引擎的结果可以并排查看，但含义、阶段与指标定义各自保留。','缺失的运行时版本不会用当前环境版本回填。']},
 'metric.table.native':{title:'原生指标表怎么读',summary:'保留引擎自己的定义与单位，空值不填零。',ref:'RESULT_CONTRACT.md',
  body:['原生指标按引擎命名与单位展示，平台不强行统一口径。','跨运行比较这些指标前，先到比较页做口径检查。']},
 'series.coverage':{title:'曲线覆盖与分页',summary:'显示当前点位区间、总点数与是否降采样。',ref:'ARC07',
  body:['大序列分页返回，每页有点数上限，界面显示当前区间与总量。','缺测点断线显示并列出原因；降采样会显式标注。']},
 'cost.turnover':{title:'费用与换手',summary:'费用按分项口径记录；换手序列不可用时会说明原因。',ref:'CN01—CN03',
  body:['佣金、最低佣金、过户费、卖出税与滑点按当前生效情景分项计算。','费用序列缺失时显示“未记录/不支持”，不以 0 表示免费。']},
 'compare.rules':{title:'比较口径检查',summary:'能不能排名由检查结果决定，不由界面外观决定。',ref:'COMPARE01',
  body:['检查输出 comparable / partial / incompatible 及原因，例如数据版本、日历、初始资金或费用情景不同。','模拟与真实结果、手写样本不参与排名。']},
 'compare.table':{title:'比较表怎么读',summary:'一行一个指标、一列一个运行；红=最优、绿=最劣，仅在该行允许比较时着色。',ref:'UI06 / COMPARE01',
  body:['每行是一个指标（含单位与方向：越高越好／越低越好／方向未登记），每列是一个运行；同一行内才比较，不跨行换算。','红=最优、绿=最劣（A股习惯），同时有“最优/最劣”文字标记；颜色不是唯一信息。','只有该行口径检查通过且方向已登记才着色：数据版本、日历、单位、初始资金、评估口径任一不一致时保持中性并写明原因。','并列极值会标“并列”，不虚构唯一最优；方向未登记的指标（例如换手率）不做优劣判断。','单元格数值来自该指标的全量 revision 摘要（末值、最小值或首末变化），未知与缺测显示原因，不填零。']},
 'exec.launch':{title:'启动研究（隔离进程）',summary:'每次启动都是一次独立进程，有独立工作目录与日志。',ref:'EXECUTION.md EXEC03 / EXEC04',
  body:['执行入口按 kind 选择；提交前会逐项检查前置条件，缺任一项就拒绝启动且不产生 Attempt。','同一提交期间复用同一幂等键以吸收重复点击；启动成功或去重后自动换新键，可以再次启动。']},
 'exec.kind.qlib.cn_synthetic_backtest':{title:'Qlib CN 合成行情训练+回测',summary:'训练 LightGBM 并在合成行情上回测，结果会自动入库。',ref:'EXEC12 / CN01—03 / UI05',
  body:['做什么：按 configs/cn/profile.json 编译独立工作流，在模拟 A 股行情上训练并回测，产出权益、回撤、费用台账与质量检查。','需要什么：本机 Qlib 虚拟环境与该情景的数据快照；不需要聊天模型。','产出与去向：本次运行在自己的 MLflow 库里生成记录，成功后平台自动导入结果库，可在“历史记录 → 执行记录”看到“已入库 · 运行 xxxx”。','大致耗时：本机合成数据实测约 10—20 秒。','数据性质：模拟行情、当前规则回放；通过质量检查不等于真实市场有效。']},
 'exec.kind.rdagent.factor.baseline':{title:'RD-Agent 因子基线（集成探针）',summary:'只跑基线因子回测，不发聊天请求，用来确认链路可用。',ref:'RDAGENT_INTEGRATION.md / EXEC12',
  body:['做什么：在 RD-Agent 因子模板上跑一次基线回测，验证容器、模板、数据与回测链路是否打通。','需要什么：Linux Docker（本机 Colima）与已构建的因子镜像、情景数据快照；不需要聊天模型。','产出与去向：产出研究会话快照与少量指标；结果不自动入库，需要可信离线导出后再走导入流程。','大致耗时：本机实测约 19 秒。','这是集成探针：通过只说明链路可用，不代表研究成果或因子有效。']},
 'exec.kind.rdagent.factor.loop':{title:'RD-Agent 单轮因子循环（集成探针）',summary:'让 Agent 生成并回测新因子，耗时几分钟，结果是研究快照。',ref:'RDAGENT_INTEGRATION.md / EXEC12',
  body:['做什么：跑一轮“假设 → 生成因子代码 → 回测 → 评审”的演化循环，使用本机 .env 中的聊天与 embedding 配置。','需要什么：聊天模型与 embedding 服务可用、Linux Docker 与因子镜像就绪；缺任一项会被前置条件挡下。','产出与去向：产出研究会话、因子定义与代码、回测指标；结果不自动入库，需可信离线导出后发布。','大致耗时：本机实测一轮 3 分 29 秒，通常 3—10 分钟。','这是集成探针：Agent 生成的内容属于意见类证据，不等于已验证的因子。']},
 'exec.preconditions':{title:'前置条件怎么读',summary:'每项检查都给出状态与依据；阻塞项会阻止启动。',ref:'EXECUTION.md EXEC06',
  body:['检查覆盖引擎运行时、聊天与 embedding 可达性、数据快照指纹、日历、费用情景、容器资源与 Attempt 存储。','标“该入口非必需”的项目不影响这个入口；标“阻塞启动”的必须解决。']},
 'exec.attempts':{title:'执行记录怎么读',summary:'一行是一次真实进程；执行状态与是否入库是两件事。',ref:'EXECUTION.md EXEC02 / EXEC08',
  body:['状态为平台执行状态：排队、运行中、成功、失败、已取消、中断。','“结果需显式导入”表示执行成功但结果还没进入结果库；退出码未知表示没有退出证据，不推断成功。']},
 'exec.status':{title:'执行状态含义',summary:'只有执行器证据能让 Attempt 落终态。',ref:'EXECUTION.md EXEC02',
  body:['成功：退出码为 0；失败：退出码非 0；已取消：用户请求且确认进程结束；中断：进程失联且没有退出证据。','取消请求中表示已记录请求但尚未确认进程结束，与已取消不同。']},
 'exec.cancel':{title:'取消为什么需要确认',summary:'只有确认进程结束才落“已取消”，否则保持运行中。',ref:'EXECUTION.md EXEC05',
  body:['取消先记录请求，再终止进程组（先 SIGTERM，超时后 SIGKILL）。','若进程已产生真实终态证据（例如退出码 0），保留真实终态并说明取消未被采纳。']},
 'exec.log':{title:'日志尾部读取',summary:'有界尾部，不是实时流；内容已脱敏。',ref:'EXECUTION.md EXEC07 / EXEC08',
  body:['接口有行数与字节上限，只读取尾部，因此不能当作完整日志或实时进度。','返回内容会替换密钥与服务端绝对路径；工作目录只以标签显示。']},
 'exec.outcome':{title:'结果与证据摘要',summary:'终态后核对的产物摘要，不是研究结论。',ref:'EXECUTION.md',
  body:['摘要包含质量检查、指标数量、MLflow run id、研究会话数量等可核对信息。','摘要收集失败时显示“摘要收集受限”，不清理已有执行结果。']},
 'research.list':{title:'研究记录怎么读',summary:'一行一次研究过程；过程不完整不等于研究失败。',ref:'RESEARCH_WORKBENCH.md',
  body:['研究记录来自已导出的快照，包含结果状态、因子数量与部分原生指标。','点击研究标题可查看结果、假设、生成代码与阶段过程。']},
 'history.panel':{title:'历史记录怎么用',summary:'子tab切换执行/研究；列表在面板内滚动，默认只展开最近记录。',ref:'UI05 / ARC07',
  body:['执行记录与研究记录放在同一张卡片的两个子tab里，切换只改变显示内容，不改变数据、排序与来源标记。','列表在面板内滚动（鼠标滚轮不会推动整页）；当前显示条数与总数一并标注。','默认折叠为最近若干条，展开与收起只影响展示，筛选与统计分母不受影响；侧栏“最近运行”同样只在自身区域滚动。']},
 'research.detail.metrics':{title:'研究指标',summary:'原生指标保留源口径，未记录不填零。',ref:'RESEARCH_WORKBENCH.md',
  body:['指标直接来自研究产物，未做平台归一化。','与平台标准指标的名称、单位不同，跨运行比较请使用比较页。']},
 'research.detail.factors':{title:'因子与实现',summary:'Agent 生成的定义与代码；可执行不等于因子有效。',ref:'RDAGENT_INTEGRATION.md / ARC09',
  body:['因子公式、变量与代码由 Agent 生成，属于意见类内容，不是平台结论。','未独立验证前，不能声称因子无未来信息或具备超额收益。']},
 'research.detail.feedback':{title:'Agent 评审意见',summary:'模型原文，可能包含错误解释，与数值记录分开看。',ref:'ARC09',
  body:['这里展示模型的研究反馈原文，用于理解它的推理过程。','它不构成平台的实盘建议，也不代表已核对的数值事实。']},
 'research.detail.timeline':{title:'过程时间线',summary:'离线历史摘录，不是实时进度；长内容可能截断。',ref:'RESEARCH_WORKBENCH.md',
  body:['阶段按快照记录展示，最多 300 条；长日志与代码可能被截断，未展示完整提示词。','缺失阶段保留为未记录，界面不伪造进度。']},
 'system.observability':{title:'API 运行观测',summary:'只有本工作台 HTTP 服务的实测，包含分母与窗口。',ref:'OBS01 / OBS02',
  body:['错误率定义为窗口内 HTTP 5xx / 已完成请求，4xx 单列；静态资源与健康轮询默认排除。','无样本时显示“无样本”，不显示 0%；采集覆盖不足会明确标注。']},
 'system.storage':{title:'存储与任务',summary:'健康接口区分进程存活与存储可用。',ref:'OBS02 / EXEC01',
  body:['健康状态只反映本地结果库可用性与数据库 schema 版本。','执行任务的真实状态请到研究中心“历史记录 → 执行记录”查看；本页的请求统计与任务观测是两套分母。']},
 'system.attempts':{title:'任务观测（Attempt）',summary:'失败率只看成功与失败，已取消和中断单列。',ref:'EXEC10 / OBS01',
  body:['失败率 = failed /（succeeded + failed），窗口按 Attempt 创建时间；没有样本时显示“无样本”，不显示 0%。','已取消与中断单独计数，不并入失败率；未结束的运行只出现在“未结束”列。','耗时 P95 基于有开始与结束时间的终态 Attempt；与上方 HTTP 指标是两套不同分母的观测。']},
 'data.evidence':{title:'数据证据怎么读',summary:'展示结果对应的数据集身份与执行情景，不是数据目录。',ref:'ARC06 / DATA01—05',
  body:['数据集身份、内容版本、日历与情景指纹共同描述这次结果用了什么输入。','供应商目录、覆盖报告与真实 PIT 校验接入后，本页才会显示这些内容。']},
};
const helpKeys = Object.keys(HELP);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n, digits=2) => typeof n === 'number' ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:digits}).format(n) : '未知';
const sample = run => (run?.synthetic && run?.provenance?.kind!=='fixture' ? '<span class="sample">模拟行情</span>' : '') + (run?.provenance?originBadge(run.provenance):'');

const originLabels={native:'引擎原始记录',derived:'工作台计算',custom:'定制检查',opinion:'Agent生成意见',rule:'工作台规则提示',fixture:'手写演示样本',measured:'工作台实测',unknown:'来源未核实',unsupported:'未接入',limited:'能力受限',missing:'未记录'};
function originBadge(p){if(!p)return '';return `<span class="origin origin-${esc(p.kind)}" title="${esc([p.source,...(p.limitations||[])].join('；'))}">${esc(p.label||originLabels[p.kind]||p.kind)}</span>`;}
function badge(kind){return originBadge({kind});}
function help(key,label=''){
 const item=HELP[key];
 if(!item)return '';
 const name=label||item.title;
 return `<span class="help-wrap"><button type="button" class="help" data-help="${esc(key)}" aria-haspopup="dialog" aria-expanded="false" aria-label="说明：${esc(name)}${item.summary?'。'+esc(item.summary):''}">?</button><span class="help-tip" role="tooltip">${esc(item.summary)}<small>点击查看完整说明</small></span></span>`;
}
function openHelp(key,trigger){
 const item=HELP[key];
 const modal=document.getElementById('help-modal');
 if(!item||!modal)return false;
 state.helpTrigger=trigger||null;
 document.getElementById('help-modal-title').textContent=item.title;
 const points=(item.points||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 document.getElementById('help-modal-body').innerHTML=`${(item.body||[]).map(x=>`<p>${esc(x)}</p>`).join('')}${points?`<ul>${points}</ul>`:''}${item.ref?`<p class="panel-note">规范依据：${esc(item.ref)}</p>`:''}`;
 modal.hidden=false;
 if(trigger&&trigger.setAttribute)trigger.setAttribute('aria-expanded','true');
 const close=document.getElementById('help-modal-close');
 if(close&&close.focus)close.focus();
 return true;
}
function closeHelp(){
 const modal=document.getElementById('help-modal');
 const trigger=state.helpTrigger;
 if(modal)modal.hidden=true;
 if(trigger&&trigger.setAttribute)trigger.setAttribute('aria-expanded','false');
 if(trigger&&trigger.focus)trigger.focus();
 state.helpTrigger=null;
}
function placeHelpTip(button){
 const wrap=button.parentElement;
 const tip=wrap&&wrap.querySelector?wrap.querySelector('.help-tip'):null;
 if(!tip||!tip.style||typeof button.getBoundingClientRect!=='function')return;
 const rect=button.getBoundingClientRect();
 const width=252;
 const viewport=(typeof window!=='undefined'&&window.innerWidth)?window.innerWidth:rect.left+width+16;
 tip.style.top=`${Math.round(rect.bottom+8)}px`;
 tip.style.left=`${Math.round(Math.max(8,Math.min(rect.left,viewport-width-12)))}px`;
}
function bindHelp(){
 document.querySelectorAll('[data-help]').forEach(button=>{
  button.onclick=event=>{event.preventDefault();openHelp(button.dataset.help,button);};
  button.onmouseenter=()=>placeHelpTip(button);
  button.onfocus=()=>placeHelpTip(button);
 });
 if(state.helpBound)return;
 state.helpBound=true;
 const modal=document.getElementById('help-modal');
 const close=document.getElementById('help-modal-close');
 if(close)close.onclick=()=>closeHelp();
 if(modal)modal.onclick=event=>{const target=event.target;const inCard=target&&target.closest&&target.closest('.modal-card');if(!inCard)closeHelp();};
 if(document.addEventListener)document.addEventListener('keydown',event=>{const target=document.getElementById('help-modal');if(event.key==='Escape'&&target&&!target.hidden)closeHelp();});
}
function provenancePanel(detail){
 const audit=detail.provenance;if(!audit)return card('来源核查',badge('unknown')+' 当前结果未登记来源映射');
 return card('数据来源与能力标记',`${originBadge(audit.run)} ${audit.data_nature==='synthetic'?'<span class="sample">模拟行情</span>':''}<p class="panel-note">原始记录只表示数值来自引擎产物，不表示行情真实，也不表示使用未经修改的上游执行器。下表区分字段来源与计算范围。</p><details><summary>逐项查看字段来源、公式与限制</summary><div class="table-scroll"><table class="table"><thead><tr><th>字段</th><th>来源类型</th><th>依据与限制</th></tr></thead><tbody>${audit.fields.map(x=>`<tr><td>${esc(x.field)}</td><td>${originBadge(x)}</td><td>${esc(x.source)}<br><span class="warning">${esc(x.limitations.join('；'))}</span></td></tr>`).join('')}</tbody></table></div></details>`);
}
async function capabilityPanel(){
 const data=await api('/v1/provenance/capabilities');
 return card('能力边界与来源审计',`<p class="panel-note">这里描述当前工作台接入程度，不代表上游框架的全部能力。标记不以有数字或绿灯代替验收。</p><div class="table-scroll"><table class="table"><thead><tr><th>功能 / 信息</th><th>标记</th><th>依据与限制</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.name)}</td><td>${originBadge(x)}</td><td>${esc(x.source)}<br>${esc(x.limitations.join('；'))}</td></tr>`).join('')}</tbody></table></div>`);
}
async function api(path) {
  const generation=state.renderGeneration;
  const response=await fetch(path,{headers:{'Accept':'application/json'}});
  const body=await response.json().catch(error=>{if(response.ok)throw error;return {};});
  if(generation!==state.renderGeneration){const error=new Error('页面已切换');error.name='StaleRender';throw error;}
  if(!response.ok){
    const error=new Error(`${body.message||'请求失败 '+response.status}${body.request_id?' · request_id: '+body.request_id:''}`);
    error.status=response.status;error.code=body.code;throw error;
  }
  return body;
}
function empty(message){return `<div class="empty">${esc(message)}</div>`;}
function foldRows(items,expanded,preview){return expanded?items:items.slice(0,preview);}
function foldToggle(id,total,shown,expanded,preview=HISTORY_PREVIEW,note=''){
 if(total<=preview)return '';
 return `<p class="fold-row"><button type="button" class="fold-toggle" data-fold="${esc(id)}">${expanded?'收起，只看最近 '+preview+' 条':'展开全部（共 '+total+' 条）'}</button><small>当前显示 ${shown} / ${total} 条${note?' · '+esc(note):''}</small></p>`;
}
const cardHelp = {
 '最近研究与待检查事项':'research.list','研究记录':'research.list','会话内实验':'research.list','研究结果':'research.list','产物缺口':'research.list',
 '运行概况':'metric.overview','权益曲线':'series.coverage','成本与换手':'cost.turnover',
 '来源证据':'provenance.panel','来源核查':'provenance.panel','数据来源与能力标记':'provenance.panel','能力边界与来源审计':'provenance.panel','来源与限制':'provenance.panel',
 '规则摘要与待验证事项':'review.panel','训练运行':'metric.engine','训练与信号指标':'metric.table.native',
 '选择运行':'compare.rules','口径检查':'compare.rules','比较结果':'compare.rules',
 '比较表（一行一指标）':'compare.table',
 '启动研究（隔离进程）':'exec.launch','执行记录':'exec.attempts','运行环境':'exec.preconditions',
 '结果指标':'research.detail.metrics','因子与实现':'research.detail.factors','Agent 评审意见':'research.detail.feedback','过程时间线':'research.detail.timeline',
 'API 运行观测':'system.observability','存储与任务':'system.storage','当前研究的数据证据':'data.evidence',
 '任务观测（Attempt）':'system.attempts','历史记录':'history.panel',
 '因子面板':'factor.stats','单因子统计':'factor.stats','重叠性：相关性、共线性与冗余':'factor.overlap',
 '增量贡献（相对等权组合）':'factor.overlap','因子分析':'factor.stats',
};
function card(title,body,meta='',helpKey=''){const key=helpKey||cardHelp[title]||'';return `<section class="card"><div class="card-head"><div class="card-title"><h2>${esc(title)}</h2>${key?help(key,title):''}</div><small>${esc(meta)}</small></div>${body}</section>`;}
function statusLabel(status){const text={succeeded:'成功',failed:'失败',running:'运行中',queued:'排队中',cancelled:'已取消',interrupted:'中断',unknown:'未知'}[status]||status;return `<span class="status ${status==='failed'?'failed':status==='unknown'?'unknown':''}">${esc(text)}</span>`;}
function setNotice(message=''){document.getElementById('notice').textContent=message;}
function setView(view){
  state.view=titles[view]?view:'overview';location.hash=state.view;
  document.querySelectorAll('.nav').forEach(button=>button.classList.toggle('active',button.dataset.view===state.view));
  document.getElementById('page-title').textContent=titles[state.view][0];
  document.getElementById('page-subtitle').textContent=titles[state.view][1];
  document.getElementById('page-help').innerHTML=help(`page.${state.view}`);
  render();
}
function selectRun(id,revision=null){state.selected=id;state.revision=revision;const url=new URL(location.href);url.searchParams.set('run',id);if(revision)url.searchParams.set('revision',revision);else url.searchParams.delete('revision');history.replaceState(null,'',url);renderRuns();render();}
function renderRuns(){
  const box=document.getElementById('run-list');
  const visible=state.runs.filter(item=>`${item.run.title} ${item.run.engine.id} ${item.external_id}`.toLocaleLowerCase().includes(state.search));
  const shown=foldRows(visible,state.runsExpanded,HISTORY_PREVIEW);
  box.innerHTML=visible.length?shown.map(item=>`<button class="run-item ${item.run_id===state.selected?'selected':''}" data-run="${esc(item.run_id)}"><b>${esc(item.display_title||item.run.title)}</b><small>${sample(item.run)}${esc(item.run.engine.id)} · ${esc(item.run.status)}</small></button>`).join(''):empty(state.runs.length?'没有匹配的运行':'还没有导入运行结果');
  box.querySelectorAll('[data-run]').forEach(button=>button.onclick=()=>selectRun(button.dataset.run));
  const toggle=document.getElementById('run-list-toggle');
  if(toggle){
    toggle.hidden=visible.length<=HISTORY_PREVIEW;
    toggle.textContent=state.runsExpanded?`收起（当前显示 ${visible.length} 条）`:`展开全部（共 ${visible.length} 条，当前显示 ${shown.length} 条）`;
    toggle.onclick=()=>{state.runsExpanded=!state.runsExpanded;renderRuns();};
  }
  const sidebar=document.querySelector?document.querySelector('.sidebar'):null;
  if(sidebar&&sidebar.classList)sidebar.classList.toggle('expanded',state.runsExpanded);
}
function renderWidget(widget,payload){
  let body;
  if(payload.availability==='not_recorded'||payload.availability==='unsupported') body=empty(payload.reason||'尚未接入');
  else if(payload.availability==='empty') body=empty('暂无记录');
  else if(widget.query.id==='runs.latest'){
    const rows=payload.data.items.map(item=>`<tr><td><button class="link-button" data-open-run="${esc(item.run_id)}">${esc(item.display_title||item.run.title)}</button> ${sample(item.run)}</td><td>${esc(item.run.engine.id)}</td><td>${statusLabel(item.run.status)}</td><td>${esc(item.run.created_at.slice(0,10))}</td></tr>`).join('');
    body=`<table class="table"><thead><tr><th>运行</th><th>引擎</th><th>状态</th><th>日期</th></tr></thead><tbody>${rows}</tbody></table>`;
  }else if(widget.query.id==='api.error_rate.5m'){body=`<div class="kpi">${payload.data.error_rate===null?'无样本':fmt(payload.data.error_rate*100)+'%'}<small> 5xx / 已完成请求</small></div><p class="panel-note">${payload.data.server_errors} / ${payload.data.completed_requests} 请求 · 覆盖 ${fmt(payload.data.coverage_seconds,0)} 秒（窗口300秒）</p>`;}else body=empty('暂无数据');
  const widgetHelp=widget.query.id==='api.error_rate.5m'?'system.observability':widget.query.id==='runs.latest'?'research.list':'';
  return `<section class="card" style="grid-column:span ${widget.layout.w}"><div class="card-head"><div class="card-title"><h2>${esc(widget.title)}</h2>${widgetHelp?help(widgetHelp,widget.title):''}</div><small>${esc(payload.availability)}</small></div>${body}</section>`;
}
async function renderOverview(){
  const manifest=await api('/v1/dashboards/overview');
  const research=await api('/v1/research?limit=5');
  const payloads=await Promise.all(manifest.widgets.map(w=>api(`/v1/widgets/${encodeURIComponent(w.query.id)}`)));
  const overviewPreview=5;
  const shown=foldRows(research.items,state.overviewExpanded,overviewPreview);
  const overviewCard=card('最近研究与待检查事项',
    researchTable(shown)+foldToggle('overview',research.items.length,shown.length,state.overviewExpanded,overviewPreview));
  document.getElementById('content').innerHTML=`<div class="stack">${await capabilityPanel()}${overviewCard}<div class="grid">${manifest.widgets.map((w,i)=>renderWidget(w,payloads[i])).join('')}</div></div>`;
  document.querySelectorAll('[data-open-run]').forEach(button=>button.onclick=()=>{selectRun(button.dataset.openRun);setView('backtest');});
  bindResearch();bindHistory();
}
function chart(points,unit='CNY',axis='trading_date'){
  const valid=points.filter(p=>typeof p.value==='number');
  if(!valid.length)return empty('没有有效观测；缺测不填零');
  const values=valid.map(p=>p.value),lo=Math.min(...values),hi=Math.max(...values),range=hi-lo||1;
  const position=p=>axis==='step'?Number(p.x):axis==='scalar'?0:Date.parse(p.x);
  const start=position(points[0]),end=position(points.at(-1));
  const xy=p=>[48+(position(p)-start)/(end-start||1)*732,235-(p.value-lo)/range*185];
  let segments=[],segment=[];
  for(const p of points){if(typeof p.value==='number')segment.push(xy(p));else if(segment.length){segments.push(segment);segment=[];}}
  if(segment.length)segments.push(segment);
  const lines=segments.map(seg=>seg.length===1?`<circle cx="${seg[0][0]}" cy="${seg[0][1]}" r="3" fill="currentColor"/>`:`<polyline points="${seg.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join(' ')}" class="chart-line"/>`).join('');
  const gaps=points.filter(p=>p.value===null);
  return `<svg class="chart" viewBox="0 0 820 270" role="img" aria-label="${esc(unit)} ${esc(axis)}序列，${valid.length}个有效点、${gaps.length}个缺测点"><line x1="48" y1="235" x2="780" y2="235" class="chart-grid"/>${lines}<text x="48" y="42" class="chart-label">${esc(fmt(hi))} ${esc(unit)}</text><text x="48" y="255" class="chart-label">${esc(points[0].x)}</text><text x="665" y="255" class="chart-label">${esc(points.at(-1).x)}</text></svg>${gaps.length?`<p class="warning">缺测 ${gaps.length} 点，已断线：${esc([...new Set(gaps.map(p=>p.reason))].join('；'))}</p>`:''}`;
}
function seriesKey(id,metric,revision){return JSON.stringify([id,metric,revision]);}
function availabilityLabel(value){return {available:'已记录',empty:'暂无观测',not_recorded:'未记录',unsupported:'不支持',error:'读取失败'}[value]||'未记录';}
function seriesPanel(payload){
  if(!payload)return empty('未记录：该结果没有此序列');
  const entry=payload.series;
  const availability={empty:'暂无观测',not_recorded:'未记录',unsupported:'引擎不支持',error:'源序列读取失败'};
  if(entry.availability!=='available')return empty(availability[entry.availability]||entry.availability);
  const offset=payload.offset,total=payload.total_points;
  const button=(label,target,disabled)=>`<button class="action secondary" data-series-page="${target}" data-series-run="${esc(payload.run_id)}" data-series-metric="${esc(entry.metric_id)}" data-series-revision="${esc(payload.revision_id)}" ${disabled?'disabled':''}>${label}</button>`;
  return chart(entry.points,entry.unit,entry.axis)+`<p class="panel-note">当前第 ${offset+1}—${offset+entry.points.length} 点 / 共 ${total} 点；${payload.downsampled?'已降采样':'原始观测，未降采样'}。摘要按完整结果计算。</p><div class="toolbar">${button('上一页',Math.max(0,offset-payload.limit),offset===0)}${button('下一页',payload.next_offset??offset,payload.next_offset===null)}</div>`;
}
function bindSeriesPages(){document.querySelectorAll('[data-series-page]').forEach(b=>b.onclick=()=>{
  state.seriesOffsets[seriesKey(b.dataset.seriesRun,b.dataset.seriesMetric,b.dataset.seriesRevision)]=Number(b.dataset.seriesPage);render();
});}
async function selectedRevision(){
  const id=state.selected;
  if(!id)return null;
  const summary=state.runs.find(x=>x.run_id===id)||await api(`/v1/runs/${encodeURIComponent(id)}`);
  const detail=await api(`/v1/runs/${encodeURIComponent(id)}/revisions/${encodeURIComponent(state.revision||summary.revision_id)}`);
  return {summary:{...summary,display_title:detail.display_title||summary.display_title,
                   revision_id:detail.revision_id,run:{...detail.run,provenance:detail.provenance?.run}},detail};
}
async function series(id,metric,revisionId=state.runs.find(x=>x.run_id===id)?.revision_id){
  const offset=state.seriesOffsets[seriesKey(id,metric,revisionId)]||0;
  try{return await api(`/v1/runs/${encodeURIComponent(id)}/series?metric_id=${encodeURIComponent(metric)}&offset=${offset}${revisionId?'&revision_id='+encodeURIComponent(revisionId):''}`);}
  catch(error){if(error.status===404&&error.code==='not_found')return null;throw error;}
}
async function renderBacktest(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先在左侧选择一个运行');return;}
  const {summary,detail}=selected, id=summary.run_id;
  const review=await api(`/v1/runs/${id}/review?revision_id=${summary.revision_id}`);
  const [equity,drawdown,cost,turnover]=await Promise.all(['platform.equity','platform.drawdown','native.qlib.total_cost','native.qlib.turnover'].map(x=>series(id,x,summary.revision_id)));
  const points=equity?.series.points||[];
  const last=review.facts.ending_equity;
  const dd=review.facts.max_observed_drawdown;
  const totalCost=review.facts.total_cost;
  const kpis=`<div class="metric-row"><div class="metric-box"><small>期末权益 ${originBadge(equity?.series?.provenance)}</small><strong>${fmt(last)} <small>${esc(equity?.series?.unit||'币种未记录')}</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof review.facts.observed_equity_change==='number'?fmt(review.facts.observed_equity_change*100)+'%':'未知'}</strong></div><div class="metric-box"><small>最大观测权益回撤 ${badge('derived')}</small><strong>${typeof dd==='number'?fmt(dd*100)+'%':'未知'}</strong></div><div class="metric-box"><small>引擎</small><strong>${esc(summary.run.engine.id)}</strong></div></div>`;
  const heading=`<div class="heading-row"><div><h2>${esc(summary.display_title||summary.run.title)}</h2><p class="panel-note">${statusLabel(summary.run.status)} ${sample(summary.run)} · 结果版本 ${esc(summary.revision_id.slice(0,12))} · 数据版本 ${esc(summary.run.dataset.version||'未知')}</p></div></div>`;
  const misc=`<p class="panel-note">${originBadge(cost?.series?.provenance)} 累计费用（源报告末点）：${fmt(totalCost)} ${esc(cost?.series?.unit||'币种未记录')}（${availabilityLabel(cost?.series.availability)}）<br>换手序列：${availabilityLabel(turnover?.series.availability)} · 撮合与费用口径请查原运行配置。</p>`;
  document.getElementById('content').innerHTML=`<div class="stack">${card('运行概况',heading+kpis)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('权益曲线',seriesPanel(equity),equity?.series?.provenance?.source||'来源未核实')}${card('成本与换手',misc)}${card('来源证据',`<details><summary>展开原始证据</summary><pre class="panel-note">${esc(JSON.stringify(detail.evidence,null,2))}</pre></details>`,'未知事实保留为空')}</div>`;
}
async function renderTraining(){
  const selected=await selectedRevision();if(!selected){document.getElementById('content').innerHTML=empty('请先选择一个运行');return;}
  const {summary,detail}=selected;
  const review=await api(`/v1/runs/${summary.run_id}/review?revision_id=${summary.revision_id}`);
  const metrics=detail.series.filter(x=>x.axis==='step'||x.metric_id.toLowerCase().includes('ic')||x.metric_id.includes('l2'));
  let rows=[];
  for(const metric of metrics.slice(0,30)){
    const value=metric.summary?.last;
    rows.push(`<tr><td>${esc(metric.metric_id)} ${originBadge(metric.provenance)}${metric.axis==='step'&&metric.point_count<2?badge('limited'):''}</td><td>${esc(metric.axis)}</td><td>${esc(fmt(value,5))}</td><td>${esc(metric.unit)}</td><td>${availabilityLabel(metric.availability)}${metric.summary?.last_reason?' · '+esc(metric.summary.last_reason):''}</td></tr>`);
  }
  const stageText=summary.run.stages?.map(x=>`${esc(x.kind)}：${esc(x.status)}`).join(' · ')||'阶段信息未知';
  document.getElementById('content').innerHTML=`<div class="stack">${card('训练运行',`<div class="heading-row"><h2>${esc(summary.display_title||summary.run.title)}</h2>${sample(summary.run)}</div><p class="panel-note">${stageText}<br>引擎运行时版本：${esc(summary.run.engine.version||'未知')} · 数据版本：${esc(summary.run.dataset.version||'未知')}</p>`)}${provenancePanel(detail)}${reviewPanel(review,detail.evidence)}${card('训练与信号指标',rows.length?`<table class="table"><thead><tr><th>指标</th><th>轴</th><th>末点</th><th>单位</th><th>记录状态</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:empty('该运行没有可显示的训练指标'))}</div>`;
}
const compareReasons = {legacy_experiment_attribution_unverified:'旧版导出实验归属未复核',dataset_id_differs:'数据集身份不同',coverage_axis_differs:'有效观测坐标不同',missing_observations:'序列有缺测',step_kind_differs:'训练步定义未知或不同',evaluation_unknown_or_differs:'评估口径未知或不同',initial_equity_unknown_or_differs:'初始资金未知或不同',initial_equity_invalid:'缺少有效初始资金',cashflow_policy_unknown_or_differs:'现金流口径未知或不同',cashflow_not_supported:'尚不支持该现金流口径',price_basis_unknown_or_differs:'价格口径未知或不同',benchmark_id_unknown_or_differs:'基准未知或不同',handwritten_fixture_present:'包含手写演示样本，不支持研究排名',date_window_differs:'回测日期窗口不同',first_equity_differs:'首个观测权益不同',execution_scenario_unknown_or_differs:'执行/费用情景未知或不同',unit_differs:'单位不同',axis_differs:'序列轴不同',definition_id_differs:'指标定义不同',calendar_id_differs:'交易日历不同',currency_differs:'币种不同',synthetic_and_real_mixed:'模拟与真实数据混用',dataset_version_unknown_or_differs:'数据版本未知或不同',direction_not_registered:'该指标方向未登记，不做优劣判断',values_equal_or_incomplete:'数值相同或不全，无法判断优劣',values_within_tolerance:'极值差异在1e-9相对容差内，可能是数值噪声，标注优劣会失真',metric_unavailable:'该运行没有这个指标'};
const compareGroupLabels={training:'训练',research:'研究',backtest:'回测',other:'其他/未登记'};
function compareReasonLabel(reason){
 const [code,suffix]=String(reason).split(':');
 if(code==='group_only_side_by_side')return `${compareGroupLabels[suffix]||suffix}组只并排，不做排名`;
 return compareReasons[code]||compareReasons[reason]||reason;
}
function compareCell(cell,row){
 if(typeof cell.value!=='number'){
  const label=cell.availability==='available'?'未知':availabilityLabel(cell.availability);
  return `<td class="cell-missing"><strong>未知</strong><br><small class="muted">${esc(label)}${cell.reason?' · '+esc(compareReasons[cell.reason]||cell.reason):''}</small></td>`;
 }
 const ratio=row.unit==='ratio';
 const mark=cell.mark?`<span class="rank-mark rank-${cell.mark}">${cell.mark==='best'?'最优':'最劣'}${cell.tied?'·并列':''}</span>`:'';
 return `<td class="${cell.mark?'cell-'+cell.mark:''}"><strong>${fmt(cell.value,ratio?4:2)}</strong> <small>${esc(row.unit||cell.unit||'')}</small>${ratio?`<br><small class="muted">${fmt(cell.value*100,2)}%</small>`:''}${mark?`<br>${mark}`:''}</td>`;
}
function compareTableHtml(table){
 if(!table.rows||!table.rows.length)return empty('没有可比较的指标');
 const head=`<tr><th>指标</th>${table.runs.map(r=>`<th>${esc(r.title)} ${r.synthetic?'<span class="sample">模拟</span>':''}<small class="block muted">${esc(r.engine_id)} · 数据版本 ${esc(r.dataset_version?String(r.dataset_version).slice(0,10):'未记录')}</small></th>`).join('')}</tr>`;
 const body=table.rows.map(row=>{
  const note=row.ranking_allowed?'':`<small class="block warning">本行不做优劣判断：${esc(row.reasons.map(compareReasonLabel).join(' · '))}</small>`;
  const group=row.group_label?`<span class="group-tag">${esc(row.group_label)}组</span>`:'';
  return `<tr><th class="compare-row-title">${esc(row.label)} ${group}<small class="block muted">${esc(row.unit||'单位未记录')} · ${esc(row.direction_label)}</small>${note}</th>${row.cells.map(cell=>compareCell(cell,row)).join('')}</tr>`;
 }).join('');
 return `<div class="table-scroll"><table class="table compare-table"><thead>${head}</thead><tbody>${body}</tbody></table></div><p class="panel-note">红=最优、绿=最劣（A股习惯），只在整行口径检查通过且方向已登记时着色；未着色的行写明原因，最优/最劣同时有文字标记，颜色不是唯一信息。</p>`;
}
async function renderCompare(){
  const choices=state.runs.map(item=>`<label class="compare-choice"><input type="checkbox" data-compare-run="${esc(item.run_id)}" ${state.compareIds.includes(item.run_id)?'checked':''}><span><strong>${esc(item.display_title||item.run.title)}</strong><small>${esc(item.run.engine.id)} · ${esc(item.run.dataset.id)} · ${esc(item.run.dataset.version||'版本未知')} ${sample(item.run)}</small></span></label>`).join('');
  const picker=card('选择运行',`<p class="panel-note">选择 2 至 10 个运行。比较依据为平台标准指标，原生指标保留各自定义。</p><div class="compare-choices">${choices||empty('还没有导入运行')}</div>`);
  if(state.compareIds.length<2){document.getElementById('content').innerHTML=`<div class="stack">${picker}${card('比较结果',empty('请选择至少两个运行'))}</div>`;bindCompare();return;}
  const query=new URLSearchParams({metric_id:'platform.equity'});
  state.compareIds.forEach(id=>query.append('run_id',id));
  const assessment=await api(`/v1/compare?${query}`);
  const tableQuery=new URLSearchParams();
  state.compareIds.forEach(id=>tableQuery.append('run_id',id));
  const table=await api(`/v1/compare/table?${tableQuery}`);
  const reasons=assessment.reasons.map(compareReasonLabel);
  const rankable=table.rows.filter(row=>row.ranking_allowed).length;
  const tone=rankable?'assessment-ok':'assessment-caution';
  const variables=table.experiment_variables||[];
  const variableNote=variables.includes('experiment_id_differs')?'实验变量：研究配置不同（允许并已列出）':
    variables.includes('experiment_id_unknown')?'研究配置身份未记录，无法确认实验变量':null;
  const assessmentBody=`<div class="assessment ${tone}"><strong>${rankable} / ${table.rows.length} 行可按统一口径排名</strong><p>${esc(rankable?'逐行结果见下表；未着色的行在行内写明原因':'暂不能排名：'+(reasons.join(' · ')||'原因见下表各行'))}</p></div><p class="panel-note">表格逐行判定口径；顶部结论只是汇总。${variableNote?esc(variableNote)+'。':''}每个运行单独绘图，保留原始时间轴与数值。不同时间窗口或起始资金不自动归一化。</p>`;
  const panels=await Promise.all(state.compareIds.map(async id=>{
    const item=state.runs.find(x=>x.run_id===id);
    if(!item)return card('运行不存在',empty(id));
    const revisionId=assessment.revisions?.[id]||item.revision_id;
    const result=await series(id,'platform.equity',revisionId);
    const review=await api(`/v1/runs/${id}/review?revision_id=${revisionId}`);
    const detail=await api(`/v1/runs/${id}/revisions/${revisionId}`);
    const scenario=detail.evidence?.cn_scenario;
    const selectedRun={...detail.run,provenance:detail.provenance?.run,display_title:detail.display_title};
    const first=review.facts.first_observed_equity,last=review.facts.ending_equity;
    const bounds=review.facts.equity_coverage;
    const heading=`<div class="heading-row"><p class="panel-note">${esc(selectedRun.engine.id)} · ${esc(selectedRun.dataset.id)} · ${sample(selectedRun)}</p><button class="link-button" data-open-run="${esc(id)}">查看详情</button></div>`;
    const facts=`<div class="metric-row"><div class="metric-box"><small>期末权益</small><strong>${fmt(last)} <small>${esc(result?.series.unit||'')}</small></strong></div><div class="metric-box"><small>首末观测权益变化 ${badge('derived')}</small><strong>${typeof review.facts.observed_equity_change==='number'?fmt(review.facts.observed_equity_change*100)+'%':'未知'}</strong></div><div class="metric-box"><small>数据版本</small><strong>${esc(selectedRun.dataset.version||'未知')}</strong></div></div>`;
    const context=`<dl class="context-grid"><dt>报告区间</dt><dd>${esc(bounds?.start||'未记录')} → ${esc(bounds?.end||'未记录')}</dd><dt>最大观测回撤 ${badge('derived')}</dt><dd>${typeof review.facts.max_observed_drawdown==='number'?fmt(review.facts.max_observed_drawdown*100)+'%':'未知'}</dd><dt>累计成本</dt><dd>${fmt(review.facts.total_cost)} CNY</dd><dt>质量</dt><dd>${badge(review.quality?'custom':'missing')} ${esc(review.quality?.status||'未记录')}</dd><dt>执行情景</dt><dd>${esc(scenario?.fingerprint?.slice(0,12)||'未知')}</dd><dt>佣金 / 最低费</dt><dd>${esc(scenario?.commission_both??'未知')} / ${esc(scenario?.minimum_commission??'未知')}</dd><dt>结果版本</dt><dd>${esc(revisionId.slice(0,12))}</dd></dl>`;
    return card(selectedRun.display_title||selectedRun.title,heading+facts+context+seriesPanel(result),esc(selectedRun.created_at.slice(0,10)),'page.compare');
  }));
  const tableCard=card('比较表（一行一指标）',compareTableHtml(table),'红=最优，绿=最劣；只在该行口径允许时着色','compare.table');
  document.getElementById('content').innerHTML=`<div class="stack">${picker}${card('口径检查',assessmentBody)}${tableCard}<details class="compare-details"><summary>逐运行明细与曲线（${state.compareIds.length} 个运行）</summary><div class="compare-grid">${panels.join('')}</div></details></div>`;
  bindCompare();
  document.querySelectorAll('[data-open-run]').forEach(button=>button.onclick=()=>{selectRun(button.dataset.openRun);setView('backtest');});
  bindResearch();
}
function bindCompare(){
  document.querySelectorAll('[data-compare-run]').forEach(input=>input.onchange=()=>{
    const id=input.dataset.compareRun;
    if(input.checked&&state.compareIds.length>=10){input.checked=false;setNotice('最多比较 10 个运行');return;}
    state.compareIds=input.checked?[...state.compareIds,id]:state.compareIds.filter(x=>x!==id);
    const url=new URL(location.href);
    url.searchParams.set('compare',state.compareIds.join(','));
    history.replaceState(null,'',url);render();
  });
}
const agentReason = {chat_not_configured:'聊天模型或密钥未配置',embedding_not_configured:'Embedding 模型或对应密钥未配置',embedding_service_unavailable:'本地 Embedding 服务或模型暂不可用',native_runtime_unverified:'RD-Agent 官方仅支持 Linux；当前系统的原生因子流程尚未验证',docker_not_available:'Linux Docker 引擎当前不可用',factor_image_unverified:'因子执行所需的 CPU/arm64 镜像尚未验证',factor_scenario_not_aligned:'因子模板的数据区间与万二费用情景尚未对齐',checkout_missing:'RD-Agent checkout 不存在',checkout_not_configured:'未指定 RD-Agent checkout'};
const executionReasonLabels = {rdagent_checkout:'RD-Agent checkout 不存在',rdagent_venv:'RD-Agent 虚拟环境缺失','rdagent.checkout':'RD-Agent checkout 不存在','rdagent.venv':'RD-Agent 虚拟环境缺失','rdagent.chat':'聊天模型或密钥未配置（loop 必需）','rdagent.embedding':'本地 Embedding 服务或模型不可用（loop 必需）','rdagent.docker':'Linux Docker 引擎不可用','rdagent.image':'因子执行镜像未构建','rdagent.resources':'Docker 资源低于下限（需至少 2 CPU、4GiB）','rdagent.data_snapshot':'该情景指纹的容器数据快照尚未物化','rdagent.template':'模板与当前情景指纹不一致','rdagent.profile':'CN 情景配置不可用','platform.attempt_store':'平台 Attempt 存储不可用','cn.profile':'CN 情景配置不可用','cn.data_snapshot':'本机数据快照尚未物化','cn.calendar':'交易日历未覆盖研究区间','cn.fee_scenario':'费用情景缺失','cn.engine_env':'Qlib 虚拟环境缺失','cn.attempt_workspace':'执行工作目录不可写'};
function newIdempotencyKey(){return (crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(16).slice(2)}`);}
function reasonLabel(id){return executionReasonLabels[id]||agentReason[id]||id;}
function outcomeSummary(outcome){
 if(!outcome)return '未记录';
 const parts=[];
 const quality=outcome.quality;
 if(quality)parts.push(`质量 ${quality.status||'未知'} · 有效IC ${quality.valid_ic_days??'未知'}天 · 交易 ${quality.trade_days??'未知'}天`);
 if(outcome.evidence)parts.push(`指标 ${outcome.evidence.metric_count??'未知'}项`);
 if(outcome.artifacts?.mlflow_runs?.length)parts.push(`MLflow run ${outcome.artifacts.mlflow_runs.map(x=>x.slice(0,8)).join('、')}`);
 if(outcome.research_sessions_synced?.length)parts.push(`研究会话 ${outcome.research_sessions_synced.length}个`);
 if(outcome.collection_error)parts.push('摘要收集受限');
 const imported=outcome.result_import;
 if(imported&&typeof imported==='object'){
  const labels={imported:`已入库 · 运行 ${String(imported.run_id||'').slice(0,8)}`,
                reused:'已入库（复用同内容 revision）',
                failed:`入库失败 · ${imported.reason||'原因未记录'}`,
                manual_import_required:'结果需显式导入'};
  parts.push(labels[imported.status]||`入库状态 ${imported.status||'未知'}`);
 }else if(imported==='manual_import_required'){parts.push('结果需显式导入');}
 return parts.join(' · ')||'已记录';
}
function needsImportRetry(outcome){
 const state=outcome&&outcome.result_import;
 return !!(state&&typeof state==='object'&&['failed','manual_import_required'].includes(state.status));
}
function executionChecks(entry){
 const required=entry.reasons||[];
 return `<ul class="checklist">${entry.checks.map(c=>{const blocking=required.includes(c.id);const informational=!(c.required_for||[]).includes(entry.kind);return `<li class="${c.status==='ok'?'ok':'warn'}">${c.status==='ok'?'✓':'!'} ${esc(reasonLabel(c.id))}${informational?' <small>（该入口非必需）</small>':(blocking?' <small class="warning">（阻塞启动）</small>':'')}<br><small>${esc(c.detail||'')}</small></li>`;}).join('')}</ul>`;
}
function executionPanel(catalog,attempts){
 const available=catalog.items.filter(x=>x.available);
 const fallback=(catalog.items.find(x=>x.available)||catalog.items[0]||{}).kind;
 const remembered=catalog.items.some(x=>x.kind===state.executionKind)?state.executionKind:fallback;
 state.executionKind=remembered;
 const options=catalog.items.map(x=>`<option value="${esc(x.kind)}" ${x.kind===remembered?'selected':''} ${x.available?'':'disabled'}>${esc(x.label)}${x.available?'':'（前置条件未满足）'}</option>`).join('');
 const form=`<form id="execution-form" class="toolbar"><label class="sr-only" for="execution-kind">执行入口</label><select id="execution-kind" aria-label="执行入口" ${available.length?'':'disabled'}>${options}</select><input id="execution-note" aria-label="备注" placeholder="可选备注（随 Attempt 保存）"><button class="action" id="execution-submit" ${available.length?'':'disabled'}>启动研究</button><small>启动请求期间复用同一幂等键（重复点击不会产生第二个进程）；启动成功或去重后自动换用新键，可再次启动新 Attempt。</small></form><p id="execution-feedback" class="panel-note">${entryFeedback(remembered)}</p>`;
 const entries=catalog.items.map(x=>{
  const meta=execEntryMeta(x.kind)||{};
  const importer={auto_import:'成功后自动入库',manual_export_required:'需可信离线导出后入库',
                  unknown:'结果去向未登记'}[x.result_destination]||'结果去向未登记';
  return `<details class="execution-entry" ${x.available?'':'open'}><summary><span class="entry-title">${esc(x.label)} ${x.probe?badge('limited'):''} ${x.available?badge('measured'):badge('unsupported')}${help('exec.kind.'+x.kind,x.label)}</span><small class="block muted">${esc(meta.summary||x.description||'')}</small></summary><p class="panel-note">执行器 <code>${esc(x.executor_id)}</code> · 数据性质 ${esc(x.data_nature||'未记录')} · 结果去向 ${esc(importer)}<br>${esc(x.description||'')}</p>${executionChecks(x)}</details>`;
 }).join('');
 return card('启动研究（隔离进程）',form+entries,'三种入口的用途、数据性质与结果去向都写在下面；点问号看完整说明');
}
function entryFeedback(kind){
 const item=execEntryMeta(kind);
 const head=item?esc(item.summary):'当前没有可用执行入口；下方逐项列出缺失条件，不会提供假启动。';
 return `${help('exec.kind.'+kind,item?item.title:kind)} ${head}`;
}
function execEntryMeta(kind){
 const item=HELP['exec.kind.'+kind];
 return item?{title:item.title,summary:item.summary}:null;
}
function attemptTable(attempts){
 if(!attempts.length)return empty('还没有执行记录。启动一次研究后，这里会显示状态、退出码、结果摘要与日志入口。');
 const rows=attempts.map(a=>{
  const actions=[];
  if(a.has_log)actions.push(`<button class="link-button" data-attempt-log="${esc(a.attempt_id)}">日志尾部</button>`);
  if(['queued','running'].includes(a.status))actions.push(`<button class="link-button" data-attempt-cancel="${esc(a.attempt_id)}">${a.cancel_pending?'取消请求中…':'取消'}</button>`);
  if(a.status==='succeeded'&&needsImportRetry(a.outcome))actions.push(`<button class="link-button" data-attempt-import="${esc(a.attempt_id)}">重试入库</button>`);
  const started=(a.started_at||a.created_at||'').replace('T',' ').slice(0,19);
  const ended=a.ended_at?('→ '+a.ended_at.replace('T',' ').slice(0,19)):'进行中';
  const exitCode=(a.exit_code===null||a.exit_code===undefined)?'未知':esc(a.exit_code);
  return `<tr><td><code>${esc(a.attempt_id.slice(0,8))}</code><br><small>${esc(a.label)}${a.probe?' · 集成探针':''}</small></td><td>${statusLabel(a.status)}${a.cancel_pending?'<br><small class="warning">取消请求中</small>':''}</td><td><small>${esc(started)}<br>${esc(ended)}</small></td><td>${exitCode}${a.error_code?`<br><small class="warning">${esc(a.error_code)}</small>`:''}</td><td>${esc(outcomeSummary(a.outcome))}${a.error_message?`<br><small class="warning">${esc(a.error_message)}</small>`:''}<br><small>指纹 ${esc((a.config_fingerprint||'未知').slice(0,10))} · 工作目录 ${esc(a.workspace_label||'未记录')}</small></td><td>${actions.join(' ')||'—'}</td></tr>`;
 }).join('');
 return `<div class="table-scroll"><table class="table"><thead><tr><th>Attempt</th><th>状态 ${help('exec.status')}</th><th>时间</th><th>退出码</th><th>结果与证据 ${help('exec.outcome')}</th><th>操作 ${help('exec.cancel',"执行操作")}</th></tr></thead><tbody>${rows}</tbody></table></div><div id="attempt-log"></div>`;
}
function bindExecution(catalog){
 const form=document.getElementById('execution-form');
 if(form)form.onsubmit=async event=>{
  event.preventDefault();
  const kind=document.getElementById('execution-kind').value;
  const note=document.getElementById('execution-note').value.trim();
  const button=document.getElementById('execution-submit');
  state.executionKind=kind;
  button.disabled=true;
  try{
   const response=await fetch('/v1/executions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,params:note?{note}:{},idempotency_key:state.executionKey})});
   const body=await response.json().catch(()=>({}));
   if(!response.ok){
    const detail=(body.details?.reasons||[]).map(reasonLabel).join('；');
    throw new Error(`${body.message||'启动失败'}${detail?'：'+detail:''}${body.request_id?' · request_id: '+body.request_id:''}`);
   }
   state.executionKey=newIdempotencyKey();
   setNotice(body.created?`已启动 ${body.attempt.label}（${body.attempt.attempt_id.slice(0,8)}）`:`已存在同一幂等键的 Attempt，未重复启动（${body.attempt.status}）`);
   render();
  }catch(error){setNotice(error.message);button.disabled=false;}
 };
 const select=document.getElementById('execution-kind');
 if(select)select.onchange=()=>{
  // keep the choice and the pane in place: re-rendering here used to reset the dropdown
  state.executionKind=select.value;
  state.executionKey=newIdempotencyKey();
  const feedback=document.getElementById('execution-feedback');
  if(feedback)feedback.innerHTML=entryFeedback(state.executionKind);
 };
 document.querySelectorAll('[data-attempt-cancel]').forEach(button=>button.onclick=async()=>{
  if(!window.confirm('取消需要执行器确认进程结束后才落终态；确认请求取消？'))return;
  button.disabled=true;
  try{
   const response=await fetch(`/v1/executions/${encodeURIComponent(button.dataset.attemptCancel)}/cancel`,{method:'POST'});
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.message||'取消失败');
   setNotice(body.cancel_confirmed?`已确认进程结束，终态 ${body.attempt.status}`:`未确认取消（${body.reason||'未知'}），当前状态 ${body.attempt.status}`);
  }catch(error){setNotice(error.message);}
  render();
 });
 document.querySelectorAll('[data-attempt-log]').forEach(button=>button.onclick=async()=>{
  const target=document.getElementById('attempt-log');
  target.innerHTML='正在读取日志尾部…';
  try{
   const response=await fetch(`/v1/executions/${encodeURIComponent(button.dataset.attemptLog)}/log?tail=80`);
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.message||'日志读取失败');
   target.innerHTML=`<details open><summary>日志尾部 ${help('exec.log')}（脱敏；最多80行，${body.truncated?'已截断':'未截断'}）</summary><pre>${esc((body.lines||[]).join('\n'))}</pre></details>`;
  }catch(error){target.innerHTML=`<p class="warning">${esc(error.message)}</p>`;}
 });
 document.querySelectorAll('[data-attempt-import]').forEach(button=>button.onclick=async()=>{
  button.disabled=true;
  try{
   const response=await fetch(`/v1/executions/${encodeURIComponent(button.dataset.attemptImport)}/import`,{method:'POST'});
   const body=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(body.message||'入库失败');
   setNotice(body.imported?`已入库，运行 ${String((body.receipt&&body.receipt.run_id)||'').slice(0,8)}`:`未入库（${body.reason||'原因未记录'}）`);
  }catch(error){setNotice(error.message);}
  render();
 });
}
const researchMetricNames = {'IC':'IC（相关系数）','Rank IC':'Rank IC','ICIR':'ICIR','Rank ICIR':'Rank ICIR','1day.excess_return_with_cost.annualized_return':'成本后年化超额收益（原生口径）','1day.excess_return_with_cost.max_drawdown':'成本后超额最大回撤','1day.excess_return_with_cost.information_ratio':'成本后信息比率','l2.train':'训练 L2','l2.valid':'验证 L2'};
function reviewPanel(review,evidence={}){
  if(!review)return '';
  const q=review.quality, scenario=evidence.cn_scenario;
  const quality=q?`定制质量检查（非上游原生）：${q.status==='passed_checks'?'通过':'未通过'} · 有效 IC ${q.valid_ic_days} 天 · 交易 ${q.trade_days} 天`:'质量检查未记录';
  const fees=scenario?`佣金 ${esc(scenario.commission_both)} · 最低佣金 ${esc(scenario.minimum_commission)} 元 · 规则核查 ${esc(scenario.rules_as_of)} · ${esc(scenario.mode)}`:'执行情景未记录';
  return card('规则摘要与待验证事项',`${badge('rule')}<p class="panel-note">以下为工作台固定规则提示；不是引擎原始结论，也没有额外调用模型分析。</p><div class="assessment assessment-caution"><strong>${esc(review.conclusion)}</strong><p>${badge(q?'custom':'missing')} ${esc(quality)}</p></div><p class="panel-note">${badge(scenario?'custom':'missing')} ${fees}</p>${(review.findings||[]).map(x=>`<p class="warning">${esc(x)}</p>`).join('')}<div class="compare-grid"><div><h3>数据依据与缺口</h3><ul>${review.gaps.map(x=>`<li>${esc(x)}</li>`).join('')||'<li>没有额外缺口记录</li>'}</ul></div><div><h3>规则建议（需自行验证）</h3><ol>${review.next_steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div></div><p class="panel-note">${esc(review.basis)}</p>`);
}
function researchTable(items){
 return items.length?`<div class="table-scroll"><table class="table research-table"><thead><tr><th>研究 / 点击查看结果与过程</th><th>产物状态 ${badge('limited')}</th><th>已恢复因子 ${badge('derived')}</th><th>期末权益 ${badge('native')}</th><th>IC ${badge('native')}</th><th>成本后年化超额 ${badge('native')}</th><th>操作</th></tr></thead><tbody>${items.map(r=>`<tr><td><button class="link-button" data-research="${r.id}">${esc(r.title)}</button> ${r.synthetic?'<span class="sample">模拟行情</span>':''}<small class="block muted">${esc(r.session)}</small></td><td>${r.status==='result_available'?'已有结果':'过程不完整'}</td><td>${r.factor_count===0?'未恢复 / 不适用':r.factor_count}</td><td>${fmt(r.facts?.ending_equity)} CNY</td><td>${fmt(r.metrics?.IC,4)}</td><td>${typeof r.metrics?.['1day.excess_return_with_cost.annualized_return']==='number'?fmt(r.metrics['1day.excess_return_with_cost.annualized_return']*100)+'%':'未记录'}</td><td>${r.platform_run_id?`<button class="link-button" data-research-compare="${r.platform_run_id}">加入比较</button>`:'可查看过程'}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无研究快照。请运行研究记录同步命令，已有产物不会自动被推断为成功。');
}
function openResearch(id){state.researchId=id;const u=new URL(location.href);u.searchParams.set('research',id);history.replaceState(null,'',u);setView('agent');}
function bindResearch(){
 document.querySelectorAll('[data-research]').forEach(b=>b.onclick=()=>openResearch(b.dataset.research));
 document.querySelectorAll('[data-research-compare]').forEach(b=>b.onclick=()=>{
   const id=b.dataset.researchCompare;
   if(!state.compareIds.includes(id))state.compareIds=[...state.compareIds,id].slice(-10);
   const u=new URL(location.href);u.searchParams.set('compare',state.compareIds.join(','));history.replaceState(null,'',u);setView('compare');
 });
}
function bindHistory(){
 document.querySelectorAll('[data-history-tab]').forEach(button=>button.onclick=()=>{
  const tab=button.dataset.historyTab==='research'?'research':'attempts';
  if(state.historyTab===tab)return;
  state.historyTab=tab;state.historyExpanded=false;
  const u=new URL(location.href);u.searchParams.set('history',tab);history.replaceState(null,'',u);
  render();
 });
 document.querySelectorAll('[data-fold]').forEach(button=>button.onclick=()=>{
  const target=button.dataset.fold;
  if(target==='overview')state.overviewExpanded=!state.overviewExpanded;
  else if(target==='history')state.historyExpanded=!state.historyExpanded;
  else if(target==='runs'){state.runsExpanded=!state.runsExpanded;renderRuns();return;}
  else return;
  render();
 });
}
function readableFields(value){
 const labels={decision:'Agent 是否采纳',reason:'原因',observations:'观察结果',hypothesis_evaluation:'假设评估',new_hypothesis:'后续研究方向',acceptable:'是否可接受',exception:'异常',hypothesis:'研究假设',concise_observation:'观察',concise_justification:'依据',start_time:'阶段开始',end_time:'阶段结束',feedback:'执行反馈',log:'执行日志',report:'报告',rows:'行数',result:'结果',factor_count:'因子数',metric_count:'指标数'};
 return Object.entries(value).map(([k,v])=>`<div class="evidence-field"><h3>${esc(labels[k]||k)}</h3>${k==='decision'?`<p>${v==='False'?'未采纳候选':v==='True'?'采纳候选':esc(v)}</p>`:`<pre>${esc(typeof v==='object'?JSON.stringify(v,null,2):v)}</pre>`}</div>`).join('');
}
function stageLabel(stage){return stage.replaceAll('direct_exp_gen','研究假设').replaceAll('hypothesis generation','假设生成').replaceAll('coding','因子编码').replaceAll('running','回测执行').replaceAll('feedback','评审反馈').replaceAll('record','记录归档').replaceAll('time_info','阶段耗时').replaceAll('Quantitative Backtesting Chart','回测报告').replaceAll('Qlib_execute_log','执行日志').replaceAll('runner result','研究产物');}
async function renderResearchDetail(){
 const r=await api(`/v1/research/${encodeURIComponent(state.researchId)}`);
 if(r.status==='session_index'){document.getElementById('content').innerHTML=card('会话内实验',`<button class="action secondary" id="research-index-back">返回研究列表</button><p>按实验查看结果，旧会话合并结果已停止作为当前证据。</p>${(r.iterations||[]).map(x=>`<p><button class="link-button" data-research="${esc(x.id)}">${esc(x.title)}</button> ${esc(x.status)}</p>`).join('')||empty('尚未恢复实验')}`);bindResearch();document.getElementById('research-index-back').onclick=()=>{state.researchId=null;const u=new URL(location.href);u.searchParams.delete('research');history.replaceState(null,'',u);render();};return;}
 if(r.platform_run_id){r.review=await api(`/v1/runs/${r.platform_run_id}/review?revision_id=${r.revision_id}`);r.resultDetail=await api(`/v1/runs/${r.platform_run_id}/revisions/${r.revision_id}`);r.evidence=r.resultDetail.evidence;}
 const facts=`<div class="heading-row"><div><h2>${esc(r.title)}</h2><p class="panel-note">${r.synthetic?'<span class="sample">模拟数据</span>':''} ${esc(r.session)}<br>源事件更新 ${esc(r.updated_at)} · 快照采集 ${esc(r.observed_at)}</p></div><button class="link-button" id="research-back">返回研究列表</button></div><p>${r.status==='result_available'?'已找到回测报告。进程退出状态未记录。':'未找到完整回测结果；可查看已经记录的过程。'}</p>${r.platform_run_id?`<button class="action" id="research-result">打开统一回测详情</button> <button class="action secondary" data-research-compare="${r.platform_run_id}">加入比较</button>`:''}`;
 const metricTop=`<div class="metric-row"><div class="metric-box"><small>IC ${badge('native')}</small><strong>${fmt(r.metrics?.IC,4)}</strong></div><div class="metric-box"><small>成本后年化超额（源口径） ${badge('native')}</small><strong>${typeof r.metrics?.['1day.excess_return_with_cost.annualized_return']==='number'?fmt(r.metrics['1day.excess_return_with_cost.annualized_return']*100)+'%':'未记录'}</strong></div><div class="metric-box"><small>因子数</small><strong>${r.factor_count??'未记录'}</strong></div></div>`;
 const metrics=Object.entries(r.metrics||{}).map(([k,v])=>`<tr><td>${esc(researchMetricNames[k]||k)}</td><td>${fmt(v,6)}</td></tr>`).join('');
 const factors=(r.factors||[]).map(f=>`<details class="factor"><summary>${esc(f.factor_name||'因子')} — ${esc(f.description||'暂无说明')}</summary><p>公式</p><pre>${esc(f.factor_formulation)}</pre><p>变量</p><pre>${esc(f.variables)}</pre><details><summary>查看生成代码</summary><pre>${esc(f.code||'代码未记录')}</pre></details></details>`).join('');
 const steps=(r.events||[]).map(e=>`<details class="timeline-step"><summary><span>${esc(stageLabel(e.stage))}</span><small>${esc(e.at)}</small></summary>${typeof e.content==='string'?`<pre>${esc(e.content)}</pre>`:readableFields(e.content)}</details>`).join('');
 document.getElementById('content').innerHTML=`<div class="stack">${card('研究结果',facts)}${r.resultDetail?provenancePanel(r.resultDetail):card('来源与限制',badge('limited')+' 仅历史日志摘录；没有完整结果，不等于研究失败。')}${r.review?reviewPanel(r.review,r.evidence):''}${r.warnings?.length?card('产物缺口',r.warnings.map(x=>`<p>${esc(x)}</p>`).join('')):''}${card('结果指标',metrics?`${metricTop}<details><summary>原生指标（保留源口径，空值不填零）</summary><table class="table"><tbody>${metrics}</tbody></table></details>`:empty('没有标量指标；若已生成报告，可在统一回测详情查看权益与费用'))}${card('因子与实现',badge('opinion')+'<p class="panel-note">Agent生成的定义和代码；可执行不等于因子有效，文字声称无未来信息未被独立认证。</p>'+(factors||empty('未记录因子定义；基线回测可能只使用基础特征')))}${card('Agent 评审意见',r.feedback?`${badge('opinion')}<p class="panel-note">模型原文，可能包含错误解释；与已记录数值分开看待。</p>${readableFields(r.feedback)}<p class="panel-note">这是 Agent 的研究反馈，不是平台的实盘建议。</p>`:empty('评审反馈未记录'))}${card('过程时间线',badge('limited')+'<p class="panel-note">离线历史摘录，非实时进度；最多300条，长日志/代码可能截断，未展示完整提示词。标题与结果条目数由工作台编排。</p>'+(steps||empty('没有可恢复的研究阶段')),'点击阶段展开日志 / 耗时 / 反馈')}</div>`;
 document.getElementById('research-back').onclick=()=>{state.researchId=null;const u=new URL(location.href);u.searchParams.delete('research');history.replaceState(null,'',u);render();};
 const result=document.getElementById('research-result');if(result)result.onclick=()=>{selectRun(r.platform_run_id,r.revision_id);setView('backtest');};bindResearch();
}
async function renderAgent(){
 if(state.researchId){await renderResearchDetail();return;}
 const attemptPage=`/v1/executions?limit=20${state.attemptCursor?'&cursor='+encodeURIComponent(state.attemptCursor):''}`;
 const [list,runtime,catalog,attempts]=await Promise.all([api(`/v1/research?limit=20&offset=${state.researchOffset}&query=${encodeURIComponent(state.researchQuery)}`),api('/v1/agents/rdagent'),api('/v1/executions/catalog'),api(attemptPage)]);
 if(catalog.items.length&&!state.executionKey)state.executionKey=newIdempotencyKey();
 const toolbar=`<form id="research-search" class="toolbar"><input aria-label="搜索研究" id="research-query" placeholder="搜索因子名、日期、状态" value="${esc(state.researchQuery)}"><button class="action">搜索</button><button type="button" id="research-refresh" class="action secondary">刷新记录</button><small>共 ${list.total} 条</small></form><p class="panel-note">每条研究可查看结果、假设、生成代码和阶段记录。历史缺失信息会保留为未记录；完整指标可在统一比较页并列查看。</p>`;
 const pager=`<div class="toolbar"><button class="action secondary" id="research-prev" ${state.researchOffset===0?'disabled':''}>上一页</button><button class="action secondary" id="research-next" ${list.next_offset===null?'disabled':''}>下一页</button></div>`;
 const reasons=(runtime.execution?.reasons||[]).map(reasonLabel);
 const ready=`<details><summary>环境与执行能力</summary><p>聊天模型：${esc(runtime.chat?.model||'未连接')}；Embedding：${esc(runtime.embedding?.model||'未连接')}；Linux Docker：${runtime.runtime?.linux_container_available?'可用':'不可用'}。</p><p>界面可启动/取消隔离进程执行；被阻塞的入口会列出缺失条件${reasons.length?'（当前：'+esc(reasons.join('；'))+')':''}。取消需执行器确认进程结束后才落终态。</p><p class="panel-note">同步已有历史产物：在 RD-Agent 目录执行 .venv/bin/python ../qlib/scripts/export_rdagent_research.py --trust-local-artifacts --synthetic；历史刷新只重新读取已导出的快照，不执行研究。</p></details>`;
 const tab=state.historyTab==='research'?'research':'attempts';
 const shownAttempts=foldRows(attempts.items,state.historyExpanded,HISTORY_PREVIEW);
 const shownResearch=foldRows(list.items,state.historyExpanded,HISTORY_PREVIEW);
 const tabs=`<div class="subtabs" role="tablist" aria-label="历史记录"><button type="button" role="tab" class="subtab ${tab==='attempts'?'active':''}" data-history-tab="attempts" aria-selected="${tab==='attempts'}">执行记录 <small>${attempts.items.length}</small></button><button type="button" role="tab" class="subtab ${tab==='research'?'active':''}" data-history-tab="research" aria-selected="${tab==='research'}">研究记录 <small>${list.total}</small></button></div>`;
 const attemptPager=`<div class="toolbar"><button class="action secondary" id="attempt-prev" ${state.attemptCursors.length?'':'disabled'}>较新一页</button><button class="action secondary" id="attempt-next" ${attempts.next_cursor?'':'disabled'}>更早的记录</button><small>每页 20 条；翻页不改变排序与筛选。</small></div>`;
 // controls stay outside the scroller so searching and paging never scroll away
 const paneRows=tab==='attempts'?attemptTable(shownAttempts):researchTable(shownResearch);
 const paneControls=tab==='attempts'
  ? foldToggle('history',attempts.items.length,shownAttempts.length,state.historyExpanded)+attemptPager
  : foldToggle('history',list.items.length,shownResearch.length,state.historyExpanded,'',`全库 ${list.total} 条`)+pager;
 const paneToolbar=tab==='research'?toolbar:'';
 const historyCard=card('历史记录',`${tabs}${paneToolbar}<div class="history-scroll" id="history-scroll">${paneRows}</div>${paneControls}`,'子tab切换；操作栏固定，列表在面板内滚动，默认折叠为最近记录');
 document.getElementById('content').innerHTML=`<div class="stack">${executionPanel(catalog,attempts.items)}${historyCard}${card('运行环境',ready)}</div>`;
 const scroller=document.getElementById('history-scroll');
 if(scroller&&state.historyScrollTop)scroller.scrollTop=state.historyScrollTop;
 const search=document.getElementById('research-search');
 if(search)search.onsubmit=e=>{e.preventDefault();state.researchQuery=document.getElementById('research-query').value;state.researchOffset=0;render();};
 const prev=document.getElementById('research-prev');
 if(prev)prev.onclick=()=>{state.researchOffset=Math.max(0,state.researchOffset-20);render();};
 const next=document.getElementById('research-next');
 if(next)next.onclick=()=>{state.researchOffset=list.next_offset;render();};
 const refresh=document.getElementById('research-refresh');
 if(refresh)refresh.onclick=async()=>{await refreshRuns();render();};
 const attemptPrev=document.getElementById('attempt-prev');
 if(attemptPrev)attemptPrev.onclick=()=>{
   const cursors=[...state.attemptCursors];
   state.attemptCursor=cursors.pop()||null;
   state.attemptCursors=cursors;
   state.historyExpanded=false;
   render();
 };
 const attemptNext=document.getElementById('attempt-next');
 if(attemptNext)attemptNext.onclick=()=>{
   if(!attempts.next_cursor)return;
   state.attemptCursors=[...state.attemptCursors,state.attemptCursor].filter(Boolean);
   state.attemptCursor=attempts.next_cursor;
   state.historyExpanded=false;
   render();
 };
 bindExecution(catalog);bindResearch();bindHistory();
 if(attempts.items.some(x=>['queued','running'].includes(x.status)))setTimeout(()=>{
  const active=document.activeElement;
  const typing=active&&active.id==='execution-note';
  if(state.view==='agent'&&!state.researchId&&!typing)render();
 },5000);
}
async function refreshRuns(){
 let items=[],cursor=null;
 do{const page=await api('/v1/runs?limit=100'+(cursor?'&cursor='+encodeURIComponent(cursor):''));items.push(...page.items);cursor=page.next_cursor;}while(cursor&&items.length<1000);
 state.runs=items;renderRuns();
}

function factorStatsRow(row){
 const rank=row.rank_ic||{}, spread=row.quantile_spread||{}, turn=row.turnover||{};
 const pct=value=>typeof value==='number'?fmt(value,4):'未记录';
 return `<tr><td><strong>${esc(row.name)}</strong>${row.coverage!==null&&row.coverage!==undefined?`<small class="block muted">覆盖 ${fmt(row.coverage*100,1)}%</small>`:''}</td><td>${pct(rank.ic_mean)}</td><td>${pct(rank.t_stat)}</td><td>${pct(rank.p_value)}</td><td>${pct(row.fdr_q)}</td><td>${pct(rank.icir)}</td><td>${typeof spread.top_minus_bottom==='number'?fmt(spread.top_minus_bottom*100,3)+'%':'未记录'}</td><td>${spread.monotonic===true?'单调':spread.monotonic===false?'非单调':'未知'}</td><td>${typeof turn.turnover==='number'?fmt(turn.turnover,3):'未记录'}</td><td>${rank.days??'未记录'}</td></tr>`;
}
function factorCorrelationTable(correlation,redundancy){
 if(!correlation||!correlation.labels?.length)return empty('没有可计算的重叠：至少需要两个因子面板');
 const head=`<tr><th>因子</th>${correlation.labels.map(name=>`<th>${esc(name)}</th>`).join('')}</tr>`;
 const body=correlation.labels.map((name,row)=>`<tr><th class="compare-row-title">${esc(name)}</th>${correlation.matrix[row].map(value=>{
   if(value===null||value===undefined)return '<td class="cell-missing">未记录</td>';
   const strong=Math.abs(value)>=0.7?'cell-warn':'';
   return `<td class="${strong}">${value.toFixed(2)}</td>`;
 }).join('')}</tr>`).join('');
 const pairs=(redundancy?.pairs||[]).filter(pair=>typeof pair.correlation==='number')
   .sort((a,b)=>Math.abs(b.correlation)-Math.abs(a.correlation)).slice(0,5)
   .map(pair=>`<li>${esc(pair.left)} ↔ ${esc(pair.right)}：相关 ${pair.correlation.toFixed(3)} · 冗余度 ${pair.redundancy.toFixed(3)}</li>`).join('');
 return `<div class="table-scroll"><table class="table compare-table"><thead>${head}</thead><tbody>${body}</tbody></table></div><p class="panel-note">逐日横截面秩相关的均值；|相关| ≥ 0.7 标记为高重叠（中性色，不代表优劣）。</p>${pairs?`<p class="panel-note">最重叠的因子对：</p><ul class="stack li">${pairs}</ul>`:''}`;
}
function factorIncrementTable(incremental,combined){
 if(!incremental||!incremental.length)return empty('至少需要两个因子才能计算增量贡献');
 const rows=incremental.map(item=>`<tr><td>${esc(item.factor)}</td><td>${item.without_ic===null?'未记录':fmt(item.without_ic,4)}</td><td>${item.delta===null?'未记录':fmt(item.delta,4)}</td></tr>`).join('');
 return `<div class="table-scroll"><table class="table"><thead><tr><th>因子</th><th>去掉它后的组合 IC</th><th>加入后的增量</th></tr></thead><tbody>${rows}</tbody></table></div><p class="panel-note">等权合成（横截面标准化后取均值）；组合 IC 全量 ${combined?.ic_mean===undefined||combined?.ic_mean===null?'未记录':fmt(combined.ic_mean,4)}，天数 ${combined?.days??'未记录'}。增量接近 0 说明该因子被已有因子解释。</p>`;
}
async function renderFactors(){
 const list=await api('/v1/factors');
 const items=list.items||[];
 if(!items.length){
  document.getElementById('content').innerHTML=`<div class="stack">${card('因子库',`${badge('missing')}<p class="panel-note">还没有入库的因子面板。RD-Agent 研究会话导出时会自动发布因子面板；也可以用手工导入命令写入手工面板（会标为人工来源）。</p>`, '因子面板是一类独立数据', 'factor.stats')}</div>`;
  return;
 }
 const groups={};
 items.forEach(item=>{
  const dataset=item.dataset||{};
  const key=`${dataset.id||'未知数据集'} · ${(dataset.version||'未记录版本').slice(0,10)}`;
  (groups[key]=groups[key]||[]).push(item);
 });
 const keys=Object.keys(groups);
 if(!keys.includes(state.factorGroup))state.factorGroup=keys[0];
 const members=groups[state.factorGroup].slice(0,12);
 const query=members.map(item=>'factor_id='+encodeURIComponent(item.factor_id)).join('&');
 let report=null,error=null;
 try{report=await api(`/v1/factor-analysis?${query}&horizon=1&horizon=5&horizon=10`);}catch(problem){error=problem.message;}
 const tabs=`<div class="subtabs" role="tablist" aria-label="因子数据集">${keys.map(key=>`<button type="button" role="tab" class="subtab ${key===state.factorGroup?'active':''}" data-factor-group="${esc(key)}">${esc(key)} <small>${groups[key].length}</small></button>`).join('')}</div>`;
 const membersCard=card('因子面板',`${tabs}<div class="history-scroll">${items.slice(0,40).map(item=>`<p><strong>${esc(item.name)}</strong> <small class="muted">${esc(item.source_instance_id)} · 面板 ${item.panel_count} 个 · ${esc((item.provenance?.experiment_key||'').slice(0,48))}</small>${item.definition?.formulation?`<br><small class="muted">${esc(String(item.definition.formulation).slice(0,90))}</small>`:''}</p>`).join('')}</div>`, '已入库的因子面板；同一数据集版本才能一起分析','factor.stats');
 if(error){
  document.getElementById('content').innerHTML=`<div class="stack">${membersCard}${card('因子分析',`<p class="warning">无法计算：${esc(error)}</p>`,'必须满足同一数据集内容版本与同一日历','factor.stats')}</div>`;
  bindFactorGroups();
  return;
 }
 const stats=card('单因子统计',`<div class="table-scroll"><table class="table"><thead><tr><th>因子</th><th>Rank IC</th><th>t（NW）</th><th>p</th><th>FDR q</th><th>ICIR</th><th>分位差 Q5−Q1</th><th>单调性</th><th>换手</th><th>有效天数</th></tr></thead><tbody>${report.factors.map(factorStatsRow).join('')}</tbody></table></div><p class="panel-note">样本 ${esc(report.basis.sample.start)} → ${esc(report.basis.sample.end)}（${report.basis.sample.dates} 个交易日 × ${report.basis.sample.instruments} 个标的）；收益标签由平台按 close 前复权计算，h=1 为主口径；显著性用 Newey-West 调整并做 BH-FDR（参与检验 ${report.basis.factor_count} 个因子）。</p>`, '工作台计算；不是引擎原生指标', 'factor.stats');
 const overlap=card('重叠性：相关性、共线性与冗余',factorCorrelationTable(report.overlap.value_correlation,report.overlap.redundancy)+`<p class="panel-note">共线性：最大 VIF ${report.overlap.collinearity?.max_vif===null||report.overlap.collinearity?.max_vif===undefined?'未记录':fmt(report.overlap.collinearity.max_vif,2)}${report.overlap.collinearity?.high_collinearity?' · 存在高共线因子':''}${report.overlap.collinearity?.perfect_collinearity?' · 存在完全共线因子':''}。${esc(report.overlap.collinearity?.note||'')}</p>`+`<p class="panel-note">未接入：${(report.overlap.not_available||[]).map(item=>`${esc(item.metric)}（${esc(item.reason)}）`).join('；')||'无'}</p>`, '重叠越高，越不构成独立信息', 'factor.overlap');
 const increment=card('增量贡献（相对等权组合）',factorIncrementTable(report.overlap.incremental_ic,report.overlap.combined_ic),'组合口径为工作台计算', 'factor.overlap');
 document.getElementById('content').innerHTML=`<div class="stack">${membersCard}${stats}${overlap}${increment}</div>`;
 bindFactorGroups();
}
function bindFactorGroups(){
 document.querySelectorAll('[data-factor-group]').forEach(button=>button.onclick=()=>{
  state.factorGroup=button.dataset.factorGroup;render();
 });
}
async function renderSystem(){
 const [stats,health]=await Promise.all([api('/v1/observability'),api('/v1/health')]);
 const attempts=stats.attempts||{};
 const rate=attempts.failure_rate;
 const duration=attempts.terminal_p95_seconds;
 const attemptRows=(attempts.by_kind||[]).map(row=>`<tr><td>${esc(row.kind)}</td><td>${row.total}</td><td>${row.succeeded}</td><td>${row.failed}</td><td>${row.cancelled}</td><td>${row.interrupted}</td><td>${row.running+row.queued}</td></tr>`).join('');
 const attemptsCard=card('任务观测（Attempt）',`${badge('measured')}${attempts.availability==='empty'?badge('missing'):''}<p class="panel-note">${esc(attempts.scope||'窗口内没有任务观测')}</p><div class="metric-row"><div class="metric-box"><small>Attempt 失败率</small><strong>${rate===null||rate===undefined?'无样本':fmt(rate*100)+'%'}</strong></div><div class="metric-box"><small>分母（成功+失败）</small><strong>${attempts.failure_denominator??0}</strong></div><div class="metric-box"><small>已取消 / 中断</small><strong>${attempts.cancelled??0} / ${attempts.interrupted??0}</strong></div><div class="metric-box"><small>终态耗时 P95</small><strong>${duration===null||duration===undefined?'无样本':fmt(duration,1)+' 秒'}</strong></div></div><p class="panel-note">窗口 ${fmt(attempts.window_seconds,0)} 秒 · 覆盖 ${fmt(attempts.coverage_seconds,0)} 秒 · 总数 ${attempts.total??0} · 采集开始 ${esc(attempts.collection_started_at||'无记录')}</p>${attemptRows?`<div class="table-scroll"><table class="table"><thead><tr><th>入口</th><th>总数</th><th>成功</th><th>失败</th><th>已取消</th><th>中断</th><th>未结束</th></tr></thead><tbody>${attemptRows}</tbody></table></div>`:empty('该窗口内还没有执行记录')}`,'窗口内按 Attempt 状态统计；与上方 HTTP 指标分开');
 document.getElementById('content').innerHTML=`<div class="stack">${card('API 运行观测',`${badge('measured')}${badge('limited')}<p class="panel-note">仅本工作台HTTP服务的实测，非Qlib或RD-Agent错误率。</p><div class="metric-row"><div class="metric-box"><small>5xx 错误率</small><strong>${stats.error_rate===null?'无样本':fmt(stats.error_rate*100)+'%'}</strong></div><div class="metric-box"><small>已完成请求</small><strong>${stats.completed_requests}</strong></div><div class="metric-box"><small>4xx / 5xx</small><strong>${stats.client_errors} / ${stats.server_errors}</strong></div><div class="metric-box"><small>P95 响应耗时</small><strong>${fmt(stats.p95_ms)} ms</strong></div></div><p class="panel-note">覆盖 ${fmt(stats.coverage_seconds,0)} / 300 秒；${stats.truncated?'达到容量上限，统计覆盖不完整':'未截断'}。${esc(stats.scope)}<br>采集开始 ${esc(stats.collection_started_at)}</p><button id="system-refresh" class="action secondary">刷新观测</button>`)}${attemptsCard}${await capabilityPanel()}${card('存储与任务',`${badge('measured')}<p>本地结果库：${esc(health.status)}（schema ${esc(health.schema_version)}）。</p><p class="panel-note">执行 Attempt 在“研究中心 → 历史记录”查看，含状态、退出码、入库结果与日志尾部；历史过程不完整不等同于失败。</p>`)}</div>`;
 document.getElementById('system-refresh').onclick=()=>render();
}
async function renderDataEvidence(){
 const selected=await selectedRevision();
 if(!selected){document.getElementById('content').innerHTML=empty('选择研究以查看其数据与执行证据');return;}
 const {summary,detail}=selected, e=detail.evidence, scenario=e.cn_scenario;
 document.getElementById('content').innerHTML=`<div class="stack">${card('当前研究的数据证据',`${badge('limited')}<h3>${esc(summary.run.title)}</h3><p>${sample(summary.run)}</p><dl class="context-grid"><dt>数据集</dt><dd>${esc(summary.run.dataset.id)}</dd><dt>内容版本</dt><dd>${esc(summary.run.dataset.version||'未记录')}</dd><dt>日历</dt><dd>${esc(scenario?.calendar_id||'未记录')}</dd><dt>执行情景指纹</dt><dd>${esc(scenario?.fingerprint||'未记录')}</dd><dt>研究模式</dt><dd>${esc(scenario?.mode||'未记录')}</dd></dl><p class="panel-note">情景指纹描述配置，不能代替行情内容版本。此页展示已有结果证据，供应商数据目录和真实PIT校验尚未接入。</p>`)}${reviewPanel(await api(`/v1/runs/${summary.run_id}/review`),e)}</div>`;
}
function renderUnavailable(view){
  const info={live:['实时数据尚未接入','目前没有行情流会话或延迟记录。上线前需要数据供应商、交易日历、重连与缺口策略。'],data:['数据目录尚未接入','当前运行可查看结果来源，数据快照与质量报告将在数据层实施后出现。'],system:['系统遥测尚未接入','API和任务错误率没有采集样本，当前不显示0%。健康接口仅反映本地结果库可用性。']}[view];
  document.getElementById('content').innerHTML=`<div class="grid">${card(info[0],badge('unsupported')+empty(info[1]),'',`page.${view}`)}</div>`;
}
async function render(){
  const generation=++state.renderGeneration;
  const scroller=document.getElementById('history-scroll');
  if(scroller)state.historyScrollTop=scroller.scrollTop;
  setNotice();document.getElementById('content').innerHTML='<div class="loading">加载中…</div>';
  try{
    if(state.view==='overview')await renderOverview();
    else if(state.view==='backtest')await renderBacktest();
    else if(state.view==='training')await renderTraining();
    else if(state.view==='compare')await renderCompare();
    else if(state.view==='agent')await renderAgent();
    else if(state.view==='factors')await renderFactors();
    else if(state.view==='system')await renderSystem();
    else if(state.view==='data')await renderDataEvidence();
    else renderUnavailable(state.view);
    bindSeriesPages();
    bindHelp();
  }catch(error){if(generation!==state.renderGeneration||error.name==='StaleRender')return;setNotice(error.message);document.getElementById('content').innerHTML=empty('页面加载失败，请重试。')+'<button class="action" id="retry-page">重试</button>';document.getElementById('retry-page').onclick=()=>render();}
}
async function init(){
  document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>setView(button.dataset.view));
  document.getElementById('source-legend-help').innerHTML=help('source.legend');
  document.getElementById('run-search').oninput=event=>{state.search=event.target.value.toLocaleLowerCase().trim();renderRuns();};
  window.addEventListener('hashchange',()=>{const view=location.hash.slice(1)||'overview';if(view!==state.view)setView(view);});
  try{
    const [runs,health]=await Promise.all([api('/v1/runs?limit=30'),api('/v1/health')]);
    state.runs=runs.items;await refreshRuns();
    if(!state.selected||!state.runs.some(x=>x.run_id===state.selected))state.selected=state.runs[0]?.run_id||null;
    state.compareIds=state.compareIds.filter(id=>state.runs.some(x=>x.run_id===id));
    if(!hasCompareQuery)state.compareIds=state.runs.slice(0,2).map(x=>x.run_id);
    document.getElementById('health-label').textContent=health.status==='ok'?'正常':'异常';
    renderRuns();setView(state.view);
  }catch(error){if(error.name==='StaleRender')return;setNotice(error.message);document.getElementById('content').innerHTML=empty('无法连接本地结果服务');}
}
init();
