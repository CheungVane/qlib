# 执行层：Attempt、执行器与取消语义

状态：生效。版本：1。生效日期：2026-09-26。
关联需求：U03、U04、U09、U11、U12；上游要求 ID：ARC02、ARC04、ARC05、RUN01—RUN03、API02、AGENT04、OPS01、OBS01—OBS02。验收：IMPLEMENTATION 阶段 M3 的 A18、A19。

本文是"工作台从只读看板变成研究平台"的执行合同。它不改变结果语义专题（[RESULT_CONTRACT.md](RESULT_CONTRACT.md)）与来源专题（[PROVENANCE_AUDIT.md](PROVENANCE_AUDIT.md)）；执行成功不等于研究有效，Attempt 成功也不自动等于结果已可信入库。

## 1. 范围与边界

范围内的研究入口（execution kind）：

| kind | 执行器 | 说明 | 数据性质 |
| --- | --- | --- | --- |
| `qlib.cn_synthetic_backtest` | `qlib_subprocess` | 用 `configs/cn/profile.json` 编译独立工作目录后运行 Qlib 训练+回测工作流 | 合成行情、当前规则回放 |
| `rdagent.factor.baseline` | `rdagent_subprocess` | RD-Agent 因子基线（本地执行，不发聊天请求） | 合成情景、集成探针 |
| `rdagent.factor.loop` | `rdagent_subprocess` | RD-Agent 单轮因子演化循环（使用本地 `.env` 的聊天与 embedding 配置） | 合成情景、集成探针 |

不在范围内：结果自动入库、任务队列与调度、资源配额/并发上限、远程或云执行器、券商下单、子进程内存/CPU 硬限制、日志流式推送。以上缺口必须在 UI 与实施文档中保持可见，不能以按钮存在代替能力。

执行产生的原始产物（MLflow 目录、RD-Agent 会话目录、费用台账、质量 JSON）保留在其工作目录；进入结果库仍走显式导入，且遵循来源标记与手写样本规则。

## 2. Attempt 领域模型

Attempt 是平台对"某次真实进程执行"的记录，不是研究结论，也不是结果版本。

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

### 状态机

```
queued ──start──▶ running ──exit 0──▶ succeeded
                    │        ──exit!=0─▶ failed
                    │        ──确认取消─▶ cancelled
                    │        ──进程失联且无退出证据─▶ interrupted
```

EXEC02：
- 只有执行器证据（退出码、信号、确认的进程结束）能使 Attempt 落终态；`pid` 不存在且无退出标记时落 `interrupted`，不落 `succeeded`。
- 终态不可被后续取消或核对覆盖。需要重跑时创建新 Attempt，保留旧 Attempt 与其失败证据（RUN01）。
- `cancel_requested_at` 非空而状态仍为 `running` 表示"取消请求中"，界面必须与终态区分（RUN02）。
- 平台不修改引擎自身记录的运行状态；导入状态仍由 ImportReceipt 表达。

## 3. 执行器端口

EXEC03（独立进程，ARC05）：执行器实现 `ExecutorPort`：`preflight()`、`describe(kind)`、`prepare(kind, params)`、`start(attempt_id, prepared)`、`poll(attempt)`、`cancel(attempt)`、`outcome(attempt)`、`log_tail(attempt, lines)`。

- 每次 Attempt 使用独立进程、独立 cwd 与输出目录；Qlib 每次在新的 `.data/cn_runs/<时间戳>-<指纹前缀>` 目录生成配置与产物。
- 工作台服务进程不得 `import qlib`、不得调用 `qlib.init`；Qlib 用其自身 `.venv` 启动，RD-Agent 用其自身 checkout 的 `.venv`，两者都不进入工作台进程。
- 子进程通过包装 shell 把退出码写入工作目录内的退出标记；退出标记缺失即无退出证据，不得推断成功。
- 外部引擎允许独立环境与独立依赖；执行器只传递路径、配置与环境变量，不复制上游源码。

EXEC04（幂等，RUN03/API02）：提交必须携带调用方生成的幂等键（非空字符串，长度上限 128）。
- 同一幂等键的重复提交返回同一 Attempt，并标记 `created=false`，不产生第二个进程。
- 幂等键在平台库唯一；并发竞争由数据库唯一约束裁决。
- 失败后重试必须使用新幂等键与新的 Attempt，不得改写旧 Attempt 的键。
- 界面与CLI在一次提交期间复用同一幂等键以吸收重复点击；成功启动或被去重后必须换用新键，使用户能对同一条目再次启动新 Attempt，而不是被上一次的键静默挡住。

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
- 容器/运行时可用性与资源下限（Linux Docker 引擎、CPU/内存下限）；
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

EXEC10（观测，OBS01/OBS02）：Attempt 记录 `request_id`；平台读取操作不计入任务执行；`/v1/observability` 仍只表达工作台 HTTP 进程自身，不能代替任务失败率。失败率与耗时的分子分母在计算时必须以 Attempt 状态为准，并把 `unknown` 与 0 分开。

EXEC11（演进，GOV-UPSTREAM）：Qlib 与 RD-Agent 保持外部引擎边界；执行器是适配层，不修改上游源码，不把 RD-Agent 代码复制进 Qlib。RD-Agent 探针脚本位于本仓库 `scripts/`，RD-Agent checkout 只写其被 Git 忽略的目录。上游更新后重验执行器命令、前置条件检查与适配器契约。

## 4. 已知限制（保持可见）

- 结果自动入库未实现：执行成功后 `outcome.result_import = "manual_import_required"`，用户需按导入流程显式发布，来源标记与情景指纹照旧。
- RD-Agent 内部工作目录由其自身分配（版本化模板目录按指纹隔离）；平台保证日志、退出证据与配置指纹隔离，不修改上游的目录分配逻辑。
- 无调度器与并发上限；多次提交按机器资源自行竞争，界面不承诺排队。
- 日志查看为有界尾部读取，不是实时流；日志内容经脱敏后可能替换路径与密钥。
- 执行仅覆盖合成行情与已知情景；真实数据、远程执行器、资源硬限制属于后续阶段。

## 5. 验收映射

| 验收 | 条件 | 证据位置 |
| --- | --- | --- |
| A18 | 两个不同 Qlib 配置进程互不污染；进程崩溃标 `interrupted`；重复提交不产生双任务；重试保留 Attempt | 单元/回归测试 + 本机真实 Attempt 记录 |
| A19 | 取消有确认状态；取消/完成竞争不覆盖已确认终态；失败任务保留日志与部分产物；读取接口不启动训练 | 单元/回归测试 + 浏览器检查 |
| EXEC06 | 缺前置条件时不产生 Attempt、不返回假成功 | 回归测试（缺 RD-Agent checkout/venv 时 catalog 与提交行为） |
| EXEC07 | 跨源写请求 403；幂等重放 200；未知 kind 拒绝 | 回归测试（TestClient） |

完成状态与实测证据记录在 [IMPLEMENTATION.md](IMPLEMENTATION.md)，变更历史记录在 [CHANGELOG.md](CHANGELOG.md)。通过测试不等于执行器已覆盖真实数据或生产部署。
