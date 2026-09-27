# 执行层：Attempt、执行器与取消语义

状态：生效。版本：2.1（执行交接复审，新增合同待实现）。修订日期：2026-09-27（初始生效2026-09-26）。
关联需求：U03、U04、U09、U11、U12、U13、U23；上游要求 ID：ARC02、ARC04、ARC05、RUN01—RUN03、API02、AGENT04、OPS01、OBS01—OBS02。验收：IMPLEMENTATION阶段M3的A18/A19/A24/A25及新增A41（政策与预算）；Run关联及重试身份另验A35。

本文是"工作台从只读看板变成研究平台"的执行合同。它不改变结果语义专题（[RESULT_CONTRACT.md](RESULT_CONTRACT.md)）与来源专题（[PROVENANCE_AUDIT.md](PROVENANCE_AUDIT.md)）；执行成功不等于研究有效，Attempt 成功也不自动等于结果已可信入库。

## 1. 范围与边界

范围内的研究入口（execution kind）：

| kind | 执行器 | 说明 | 数据性质 |
| --- | --- | --- | --- |
| `qlib.cn_synthetic_backtest` | `qlib_subprocess` | 用 `configs/cn/profile.json` 编译独立工作目录后运行 Qlib 训练+回测工作流 | 合成行情、当前规则回放 |
| `rdagent.factor.baseline` | `rdagent_subprocess` | RD-Agent 因子基线（本地执行，不发聊天请求） | 合成情景、集成探针 |
| `rdagent.factor.loop` | `rdagent_subprocess` | RD-Agent 单轮因子演化循环（使用本地 `.env` 的聊天与 embedding 配置） | 合成情景、集成探针 |

范围内：执行入口与 Attempt 生命周期，以及**由执行结果触发的自动入库**（EXEC12）：执行器声明导入候选、平台按导入适配器发布结果并记录 ImportReceipt。

当前实现未覆盖：任务队列与调度、远程或云执行器、日志流式推送。并发上限、超时终止、Agent试验/调用预算与内存/CPU硬上限已按 EXEC13 落地（两条入口都走容器，见 §4 与 [IMPLEMENTATION](IMPLEMENTATION.md) 的 A41）；资源下限检查仍然不构成上限验收——本机可强制不等于其它环境可强制，缺 Docker 的环境按设计拒绝准入。券商下单属于独立交易领域（见TRADING_BOUNDARY），不复用研究Attempt状态机。以上缺口必须保持可见，不能以按钮存在代替能力。

执行产生的原始产物（MLflow 目录、RD-Agent 会话目录、费用台账、质量 JSON）保留在其工作目录；自动入库只发布执行器产出且通过校验的产物，无法导入时保留 `manual_import_required` 或 `failed` 并给出原因，且两者都继续遵循来源标记与手写样本规则。

## 2. Attempt 领域模型

Attempt 是平台对一次执行尝试的记录（包括未启动即取消或启动失败），不是研究结论，也不是结果版本。与实验定义/Run/Stage的关联及重试和修改参数的区别见LIFE01；当前字段尚未完整表达该关联，旧记录不补造。

| 字段 | 语义 |
| --- | --- |
| `attempt_id` | 平台不透明 ID（UUID），跨重启稳定 |
| `kind` / `executor_id` | 执行入口与执行器实现；写入后不可改写 |
| `status` | 平台执行状态：`queued` / `running` / `succeeded` / `failed` / `cancelled` / `interrupted` |
| `params` | 用户提交的非敏感参数；不保存密钥 |
| `idempotency_key` | 调用方提供的幂等键，平台库唯一 |
| `request_id` | 触发该 Attempt 的请求标识 |
| `config_fingerprint` | 生效情景指纹；无指纹的外部执行保留 unknown |
| `workspace` | 平台侧工作目录（服务端字段，不出现在浏览器 DTO） |
| `pid` / `exit_code` | 进程与退出证据；退出码缺失不推断成功 |
| `heartbeat_at` | 最近一次核对到进程存活的时间 |
| `cancel_requested_at` | 取消请求时间；与终态字段分开 |
| `outcome` | 终态后可核验产物摘要（MLflow run id、研究会话 id、质量 JSON 摘要等） |
| `error_code` / `error_message` | 失败或中断原因；原始长日志不入库 |

EXEC01：Attempt 必须持久化在平台数据库，跨服务重启保留；schema 升级必须显式迁移并保留既有 `runs`/`revisions`，未知版本拒绝启动。原生执行状态、平台执行状态与导入状态分别记录。

新增关联字段合同见LIFE01：run_id、attempt序号、definition_revision_id、execution_policy_revision及分阶段执行证据均需持久化；现有DTO/存储尚未具备完整字段，后续按显式迁移验收。

### 状态机

```
queued ──未启动且确认取消──▶ cancelled
   │   ──启动失败证据──▶ failed
   └──start──▶ running ──exit 0──▶ succeeded
                    │        ──exit!=0─▶ failed
                    │        ──确认取消─▶ cancelled
                    │        ──进程失联且无退出证据─▶ interrupted
```

EXEC02：
- 运行后的终态需要执行器证据（退出码、信号、确认结束）；未启动的queued可凭已持久化的取消确认或启动失败证据结束，此时started_at仍为空。已启动但pid不存在且无退出标记时落interrupted，不落succeeded。
- 已有确认退出/取消证据的终态不可被后续请求覆盖。interrupted是缺证据的失联判定；若之后取得属于同一Attempt/进程身份的迟到退出或取消确认，可追加状态纠正事件并更新投影，保留原判定与证据。不得仅凭复用的pid或用户取消请求改写。重跑另建Attempt（RUN01）。
- `cancel_requested_at` 非空而状态仍为 `running` 表示"取消请求中"，界面必须与终态区分（RUN02）。
- 平台不修改引擎自身记录的运行状态；导入状态仍由 ImportReceipt 表达。

## 3. 执行器端口

EXEC03（独立进程，ARC05）：执行器实现 `ExecutorPort`：`preflight()`、`describe(kind)`、`prepare(kind, params)`、`start(attempt_id, prepared)`、`poll(attempt)`、`cancel(attempt)`、`outcome(attempt)`、`log_tail(attempt, lines)`。

- 每次 Attempt 使用独立进程、独立 cwd 与输出目录；Qlib 每次在新的 `.data/cn_runs/<时间戳>-<指纹前缀>` 目录生成配置与产物。
- 工作台服务进程不得 `import qlib`、不得调用 `qlib.init`；Qlib 用其自身 `.venv` 启动，RD-Agent 用其自身 checkout 的 `.venv`，两者都不进入工作台进程。
- 子进程通过包装 shell 把退出码写入工作目录内的退出标记；退出标记缺失即无退出证据，不得推断成功。
- 外部引擎允许独立环境与独立依赖；执行器只传递路径、配置与环境变量，不复制上游源码。

EXEC04（幂等，RUN03/API02）：提交必须携带调用方生成的幂等键（非空字符串，长度上限 128）。
- 同一幂等键且有效载荷相同返回同一Attempt并标记created=false，不产生第二个进程；同键不同载荷返回409/idempotency_conflict（CLI非零退出），不启动进程。
- 幂等键在平台库唯一；并发竞争由数据库唯一约束裁决。
- 失败后重试必须使用新幂等键与新的 Attempt，不得改写旧 Attempt 的键。
- 界面与CLI在一次提交期间复用同一幂等键以吸收重复点击；成功启动或被去重后必须换用新键，使新的提交不被上一次的键静默挡住；这不允许绕过LIFE01的Run身份规则：失败后重试可保留Run，成功后独立复跑须新建Run，研究输入变化须新定义版本。当前完整Run关联仍待T06。

EXEC05（取消，RUN02）：
- 取消先持久化 `cancel_requested_at`；随后终止进程组（先 `SIGTERM`，超时后 `SIGKILL`），只有确认进程结束才落终态。
- 取消/完成竞争：若进程已产生真实终态证据（例如退出码 0），保留真实终态并返回 `cancel_confirmed=false` 与原因。
- 导入适配器没有取消执行能力；对导入记录调用取消必须返回明确的不可用原因，不伪造取消。
- 结果导入的失败、取消与引擎执行失败保持分离。
- 确认取消后必须清除执行期间由并发核对写入的失败标签：取消是用户请求的终态，不能同时携带`process_lost_without_exit_evidence`一类失败码。

EXEC06（前置条件，AGENT04）：提交前必须执行 `preflight()` 并逐项返回检查结果（`id`、`status`、`detail`）。任一项不满足即拒绝提交：不创建 Attempt、不返回假成功、不静默降级。检查项至少覆盖：

- 执行器运行时与其依赖（Qlib venv、RD-Agent checkout/venv）；
- 聊天与 embedding 服务可达（RD-Agent `loop` 模式必需；只检查可达性，不读取或返回密钥）；
- 数据快照与 `configs/cn/profile.json` 情景指纹一致；
- 交易日历与费用情景来自当前生效配置；
- 适用的容器/运行时、资源下限及EXEC13规定的上限/并发/超时/Agent预算。非Agent入口仅Agent预算可显式not_applicable；必须项不支持即拒绝，不能以“已披露未支持”作为通过；当前探针证据不满足完整合同；
- 平台侧 Attempt 持久化可用（数据库 schema 就绪）；
- 终态证据通道可用（工作目录可写、退出标记与日志路径可用）。

EXEC07（接口，API02/OPS01）：
- `GET /v1/executions/catalog`、`POST /v1/executions`、`GET /v1/executions`、`GET /v1/executions/{attempt_id}`、`POST /v1/executions/{attempt_id}/cancel`、`GET /v1/executions/{attempt_id}/log?tail=`。
- 读取接口只核对状态，绝不启动训练；只有写接口能创建进程。
- 写接口校验来源：`Origin` 必须同源，`Sec-Fetch-Site` 为 `cross-site` 时拒绝（403）。首版仍只绑定 loopback。
- 长操作不在请求线程里训练：请求只做 preflight、准备与进程启动，随后立即返回 Attempt；状态以核对为准。
- 前置条件失败返回 409 与逐项 `checks`；未知 kind 返回 404/400；幂等重放返回 200 与已有 Attempt。
- 日志尾部接口有行数与字节上限，返回内容经脱敏（不返回密钥、不返回服务端绝对路径）。

EXEC08（DTO 与脱敏）：浏览器/CLI 只接收版本化 DTO：
- 不返回服务端绝对路径、完整命令行与凭据；工作目录只以不含路径的标签出现；
- `params`、`outcome`、`error_message` 经脱敏后返回；
- 时间戳使用 UTC ISO-8601；缺失即 `null`，不补 0；
- DTO 明确区分 `probe`（集成探针）、`status`（平台执行）、`outcome.result_import`（是否已入结果库）。

EXEC09（CLI 与 UI 共用）：`qwb execution-catalog`、`qwb execute`、`qwb executions`、`qwb execution <id>`、`qwb cancel <id>` 与 HTTP 调用同一 `ExecutionService`，返回同一 DTO。研究中心的可见要求：

- 执行目录含入口标签、探针标记与逐项前置条件；
- 前置条件缺失时禁用启动并说明缺哪一项，不提供假启动；
- 执行记录含状态、创建/开始/结束时间、退出码、错误码、结果摘要与日志尾部；
- 运行中显示"取消请求中"与终态的区别；
- 无记录显示空态，不画示意进度或假成功率。
- 每个执行入口必须说明它是做什么的、需要什么（含是否依赖聊天/embedding 与容器）、产出什么、结果去向（自动入库或需离线导出）与大致耗时；探针入口必须标明“集成探针”。
- 启动表单的选择与备注在自动刷新、切换视图后再回到该页时必须保留；自动刷新不得把选择重置为目录中的第一个入口，也不得在用户输入备注时抢焦点。

EXEC10（观测，OBS01/OBS02）：Attempt 记录 `request_id`；平台读取操作不计入任务执行。

- `/v1/observability` 必须同时返回两部分：HTTP 进程自身（现有字段）与 `attempts` 任务块。两块的窗口、分母与排除项都必须披露，不能用一块代替另一块。
- `attempts` 块至少包含：窗口秒数与采集覆盖、总数、按状态计数、`failure_rate = failed/(succeeded+failed)`、单列 cancelled 与 interrupted、终态耗时 P95、按 kind 的分组计数。
- 没有样本时 `failure_rate` 为 `null`（显示“无样本”），不得显示 0%；分母为 0 与真实 0 失败必须分开；仅依赖 Attempt 状态，不从日志文本或退出码推断额外语义。

EXEC12（执行结果自动入库，U15）：自动入库是执行链路的一部分，不是对来源规则的豁免。

- 触发：Attempt 落 `succeeded` 终态后，由执行器给出导入候选（例如 Qlib 私有跟踪库中的 run id、数据集身份、配置路径、模拟/真实性质）；平台调用导入适配器发布结果，并写入 ImportReceipt。
- Attempt 的 `outcome.result_import` 状态取值：`imported`（含 `run_id`、`revision_id`、`receipt_id`、`adapter_version`、`imported_at`）、`reused`（同内容已有 revision）、`failed`（含原因）、`manual_import_required`（没有可用导入候选或该入口尚未提供导入器）。
- 只有引擎产出的产物可作为自动入库输入；导入必须复用显式导入的校验（来源冲突拒绝、脱敏、指纹核验、只读访问源库）。任何一项不通过即 `failed`，不得降低校验以让执行“看起来成功”。
- 自动入库不得改写历史revision或Attempt执行事实；可更新该Attempt的入库状态投影并追加ImportReceipt。重复核对同一Attempt不得重复发布（内容哈希相同即复用）。
- 提供显式重试入口（CLI 与 HTTP 写接口，走同一服务）：仅对没有 `imported/reused` 回执的 Attempt 执行；重试失败保留最后一次原因。
- 执行成功、结果入库与结果可信是三件事：`succeeded` 不保证 `imported`，`imported` 也不等于研究有效。

EXEC13（执行政策与预算，LIFE06/AGENT04；**已实现，2026-09-27**）：

- 提交前冻结execution_policy_revision：max_concurrent、timeout_seconds、terminate_grace_seconds、CPU/内存硬上限，以及Agent入口的max_trials/max_calls和各自计数范围。数值为显式配置的正数，不在spec中伪造账户/机器参数；缺失、无效或执行器不能强制实施必须项则拒绝。
- **预算作用域是 `policy_revision`**：账本按 (policy_revision, scope, kind) 记账，因此**修改政策数值即产生新作用域、额度从 0 重新计**（新政策视为一份新合同，这是有意的）。界面与接口必须同时给出 scope，避免把"额度重置"误读成"已用清零"。同作用域内取消/重启不清空。
- 首版本地采用有界准入，无调度队列：并发槽在持久化事务中预留；槽满返回409/capacity_exceeded且不创建新任务。queued仅表示已准入尚未启动，不承诺长期排队。读取不得触发启动；跨CLI/API/进程共享计数，确认未启动或已结束后释放；失联但不能确认结束的任务继续占槽并提示核对，重启先核对再开放槽。
- 任务超时从确认启动计时，持久化deadline；超时触发终止进程组，宽限期后升级终止，确认结束才记failed/timeout。用户取消记cancelled，两者不可混淆；若完成证据早于deadline则保留完成。无法确认结束时保留超时请求和interrupted，不能假报终止。
- Agent试验/调用次数在发起前原子预留；重试也计数，取消/重启不清空同一预算范围的账目。到限阻止下一次试验/调用，已获准调用可完成并保存产物（仍受任务超时约束），标记budget_exhausted及研究是否完整；不由预算到限推断研究成功。
- CPU/内存硬上限必须有执行器可核验机制，资源下限检查不构成上限。被上限终止记录failed/resource_limit及证据。若某环境尚不支持，上限能力与A41保持未完成，该环境不得通过完整EXEC06准入；本条不表示现有按钮已按此拒绝。
- **本机落地路径（2026-09-27）**：Qlib 入口在容器内运行（镜像 `qwb-qlib-cpu:local`，colima `rdagent` 池），内存用 `--memory/--memory-swap`（cgroup 硬上限，交换同时禁用）、CPU 用 `--ulimit cpu=`；被上限终止记 `failed/resource_limit`（退出码 137/152）。容器的挂载路径固定为 `/qwb/run`（工作目录）、`/qwb/data`（行情快照，只读）、`/qwb/src`（平台代码，只读），编译产物在进入容器前改写为这些路径，**残留任何宿主绝对路径即拒绝执行**；Attempt 自身跟踪库中记录的挂载路径在导入前归一化回宿主工作目录（只改路径字符串，不改指标、参数与产物字节）。
- **RD-Agent 入口容器化（2026-09-27）**：整个 Attempt（驱动与因子代码）在**同一个**容器内运行（镜像 `qwb-rdagent-cpu:local`，由 `scripts/build_rdagent_runner_image.sh` 从上游 `requirements.txt` 构建；RD-Agent 检出只挂载、不打包，上游代码变化无需重建镜像）。平台只注入挂载与执行开关：`/qwb/agent`(rw，检出与 `git_ignore_folder`)、`/qwb/repo`(ro)、`/qwb/hooks`(ro)、`/qwb/platform`(rw，研究快照与调用账本)、`~/.qlib`→`/root/.qlib`(ro)。探针在容器内把 `QTDockerEnv` 换成同容器的 `LocalEnv`（否则会去连嵌套 Docker：本机 `.env` 设了 `MODEL_COSTEER_ENV_TYPE=docker`），embedding 的 Ollama 地址由平台改写为宿主可达地址。**上游源码仍不改动**：替换只发生在平台自己的探针脚本里。
- **Agent 调用计数（2026-09-27 落地）**：计数单位是**一次 `litellm.completion` 调用**（RD-Agent 的 chat 生成请求；库内部自动重试不再细分），每次调用前在共享账本中原子预留；重试与重放各计一次，取消或重启不清空同一范围的账目；到限时该次调用被拒绝（不发出请求），Attempt 保留已有产物，并在 outcome 记 `agent_budget.calls.status=budget_exhausted` 与 used/limit，**不由此推断研究成功**。实现与上游解耦：**不修改 RD-Agent 源码**——执行器把仓库内 `hooks/agent_budget/` 前置到 `PYTHONPATH`，由 Python 标准启动钩子 `sitecustomize` 包装 `litellm` 入口；执行期计数写平台根下的文件账本（`flock` 原子），Attempt 终态由平台把用量核对进 V5 账本（DB 是持久事实，文件是执行期计数），`/v1/executions/catalog` 据此报 `calls_enforced`。embedding 调用不计入（不是生成式试验，避免同一语义出现两套口径）。
- **钩子失效即拒绝运行**：探针在导入 RD-Agent 后端后校验其 `completion` 已带包装标记；若上游改用别的客户端（或钩子未生效），配置了预算的 Attempt 直接报错退出，而不是"账本 0 次调用却在界面显示已强制"。钩子文件随包分发（`quant_workbench/hooks/agent_budget/`）。

EXEC11（演进，GOV-UPSTREAM）：Qlib 与 RD-Agent 保持外部引擎边界；执行器是适配层，不修改上游源码，不把 RD-Agent 代码复制进 Qlib。RD-Agent 探针脚本位于本仓库 `scripts/`，RD-Agent checkout 只写其被 Git 忽略的目录。上游更新后重验执行器命令、前置条件检查与适配器契约。

## 4. 已知限制（保持可见）

- 自动入库当前只覆盖声明了导入器的入口（Qlib CN 合成行情回测）。RD-Agent 入口仍为 `manual_import_required`：其结果需经可信离线导出后再进入结果库，平台不把研究会话快照当成回测结果。
- RD-Agent 内部工作目录由其自身分配（版本化模板目录按指纹隔离）；平台保证日志、退出证据与配置指纹隔离，不修改上游的目录分配逻辑。
- 无调度器与排队：并发上限是有界准入（槽满返回 409 且不创建 Attempt，槽位在写入事务内预留），失联但未确认结束的任务继续占槽并提示核对；界面不承诺排队。
- 日志查看为有界尾部读取，不是实时流；日志内容经脱敏后可能替换路径与密钥。
- 执行仅覆盖合成行情与已知情景；真实数据与远程执行器属于后续阶段。Qlib 与 RD-Agent 两条入口都已在容器内运行并受内存/CPU 硬上限约束。
- RD-Agent 的驱动与因子代码同容器运行，内存/CPU 上限对整个 Attempt 生效；调用计数见上条。容器未加 `--network` 限制（因子代码与 embedding 需要出网与宿主服务），这一点按当前用途保留。

## 5. 验收映射

### 5.1 容器路线运行手册（EXEC13 / A41）

前提：`colima` 的 `rdagent` profile 在运行（`bash scripts/start_research_runtime.sh`；池为 4 CPU / 6 GiB，`max_concurrent × memory_bytes` 必须留在池内）。

```bash
# 引擎镜像：Qlib 入口（本仓库 Qlib 源码 + qrun/tables/LightGBM）
scripts/build_rdagent_cpu_image.sh          # -> qwb-qlib-cpu:local
# RD-Agent 入口：只装上游 requirements.txt；检出运行时挂载，上游代码变化无需重建
QWB_RDAGENT_ROOT=../RD-Agent scripts/build_rdagent_runner_image.sh   # -> qwb-rdagent-cpu:local
```

验证上限确实生效（不是只看配置）：

```bash
# 运行中的 Attempt 容器：内存与 CPU 上限
docker ps --format '{{.Names}}' | grep qwb
docker inspect -f 'Memory={{.HostConfig.Memory}} Swap={{.HostConfig.MemorySwap}} Ulimits={{.HostConfig.Ulimits}}' <name>
# 强制与归类：门禁默认跑离线用例；带容器用例需显式开启
QWB_CONTAINER_TESTS=1 extensions/workbench/.venv/bin/python -m unittest \
  tests.test_container_route tests.test_agent_call_budget     # 在 extensions/workbench 下执行
```

入口前提由 `execution-catalog` 逐项给出（`cn.container`、`rdagent.limits`、`rdagent.call_budget`）；缺 Docker、缺镜像或池内存不足都会**拒绝准入**而不是无上限运行。RD-Agent 宿主 `.venv` 与 `agent_call_enforcement` 的钩子目录只影响本地调试与计数注入，不再作为执行前提。

| 验收 | 条件 | 证据位置 |
| --- | --- | --- |
| A18 | 两个不同 Qlib 配置进程互不污染；进程崩溃标 `interrupted`；重复提交不产生双任务；重试保留 Attempt | 单元/回归测试 + 本机真实 Attempt 记录 |
| A19 | 取消有确认状态；取消/完成竞争不覆盖已确认终态；失败任务保留日志与部分产物；读取接口不启动训练 | 单元/回归测试 + 浏览器检查 |
| EXEC06 | 缺前置条件时不产生 Attempt、不返回假成功 | 回归测试（缺 RD-Agent checkout/venv 时 catalog 与提交行为） |
| EXEC07 | 跨源写请求 403；幂等重放 200；未知 kind 拒绝 | 回归测试（TestClient） |
| EXEC10 | `/v1/observability` 同时返回 HTTP 与 Attempt 两块；无样本为 null；cancelled 单列；分母与窗口披露 | 回归测试 + 系统页 |
| EXEC12 | 成功 Attempt 自动发布结果并写 ImportReceipt；无候选保留 `manual_import_required`；导入失败保留原因；重复核对不重复发布；DTO 不泄漏跟踪库路径 | 回归测试 + 本机真实 Attempt 记录 |
| EXEC09 | 执行目录逐入口说明用途/依赖/产出/结果去向/耗时；前置条件缺失时不提供假启动；自动刷新不重置入口选择、不在备注输入时抢焦点 | `test_ui.cjs`（U16 回归）+ 浏览器检查 |
| EXEC11 | 执行器为适配层，不修改上游源码；上游更新后重验执行器命令、前置条件与适配器契约 | 上游合并检查清单（无自动门禁，见 IMPLEMENTATION） |
| EXEC13 / A41 | 并发准入、超时终止、试验/调用预算、内存/CPU硬上限与 `resource_limit` 归类；两条入口都在容器内运行 | [container-route](evidence/20260927-container-route.json)、[agent-call-budget](evidence/20260927-agent-call-budget.json)、§5.1 手册 |

完成状态与实测证据记录在 [IMPLEMENTATION.md](IMPLEMENTATION.md)，变更历史记录在 [CHANGELOG.md](CHANGELOG.md)。通过测试不等于执行器已覆盖真实数据或生产部署。
