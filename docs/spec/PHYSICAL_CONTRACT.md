# 共享物理合同：存储、事务与迁移

状态：G0设计版本1，2026-09-29；U29/U30/U31、ARC13、LIFE01、EXEC04/13、A43—45。基线7c4b8b2f，当前数据库schema6。本文与[命令合同](COMMAND_CONTRACT.md)、[产物合同](ARTIFACT_CONTRACT.md)共同细化[总架构](ARCHITECTURE.md)，只设计，不是已部署迁移。下面DDL以schema6为输入，目标schema7；实施前若实际最高schema已变化，必须先重基设计，禁止覆盖别人的迁移编号。

## 1. 存储分工与不变量

SQLite只存对象索引、版本关系、任务/事件、事务账本和发布回执；大面板、模型、原料及manifest放受控不可变对象存储。只有已提交的artifact索引可被下游解析。不存在“把整份研究状态塞进一个可变JSON”的第二事实源。

- entities.entity_kind仅允许experiment、research_input、research_definition、data_definition、research_workflow；Experiment名称/描述采用实体列，其他entity的description为空字符串。

`entities`是可变名称/当前编辑头，`artifacts`是不可变版本；定义/输入/工作流/政策也作为有明确类型的artifact。修改头用expected_revision比较交换，历史artifact不更新。Experiment是entity，不冒充一次Run。
- `runs`统一managed/imported；定义引用只对managed必需。旧Run ID和revision字节保留，旧外部身份迁到`external_run_bindings`。新结果revision继续使用原`revisions`，不是复制一份结果表。
- `attempts`仍是唯一执行状态表。schema6记录的新增字段保留null；即使旧imports碰巧可连到Run，也不补写“启动前已冻结定义”的历史证据。查询返回association=legacy_unknown。
- 自动边、准入幂等记录、Run/Attempt、槽、预算一起提交；进程启动/网络不得在事务内。Artifact父引用与定义必须已发布；临时文件不能成为父引用。
- SQL约束负责键、引用与基础范围；跨行的类型/同主题/有向无环/Run定义与Attempt一致性由应用事务端口验证。两者均属强制验收，不能只跑DDL就称全部不变量已保护。

## 2. schema6到7的DDL合同

以下SQL仅供迁移实现与隔离验证；不是让操作人员粘贴到用户数据库执行的命令。顺序严格按§6；迁移连接须先在事务外关闭foreign_keys，然后BEGIN IMMEDIATE。连接不得使用隐式提交拆开此事务。旧schema6的revisions/imports/factors/factor_panels/agent_budget保留。

```sql
CREATE TABLE entities (
 entity_id TEXT PRIMARY KEY, entity_kind TEXT NOT NULL,
 experiment_id TEXT REFERENCES entities(entity_id), display_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 head_artifact_id TEXT REFERENCES artifacts(artifact_id), row_version INTEGER NOT NULL DEFAULT 0 CHECK(row_version>=0),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version>0), content_digest TEXT NOT NULL,
 entity_id TEXT REFERENCES entities(entity_id), object_key TEXT NOT NULL,
 producer_run_id TEXT REFERENCES runs(run_id), producer_attempt_id TEXT REFERENCES attempts(attempt_id),
 created_at TEXT NOT NULL, UNIQUE(entity_id,artifact_type,content_digest)
);
CREATE INDEX artifacts_type_created ON artifacts(artifact_type,created_at,artifact_id);
CREATE TABLE artifact_parents (
 child_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 role TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 parent_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 PRIMARY KEY(child_id,role,ordinal), CHECK(child_id<>parent_id)
);
CREATE TABLE runs_new (
 run_id TEXT PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('managed','imported')),
 workflow_kind TEXT, experiment_id TEXT REFERENCES entities(entity_id),
 definition_id TEXT REFERENCES artifacts(artifact_id), plan_id TEXT REFERENCES artifacts(artifact_id),
 created_at TEXT NOT NULL, latest_revision_id TEXT,
 CHECK((origin='imported' AND definition_id IS NULL AND plan_id IS NULL AND workflow_kind IS NULL AND experiment_id IS NULL)
 OR (origin='managed' AND workflow_kind IS NOT NULL AND definition_id IS NOT NULL AND
 ((workflow_kind='data_prepare' AND experiment_id IS NULL AND plan_id IS NOT NULL)
 OR (workflow_kind<>'data_prepare' AND experiment_id IS NOT NULL AND plan_id IS NULL))))
);
INSERT INTO runs_new(run_id,origin,created_at,latest_revision_id)
 SELECT run_id,'imported',created_at,latest_revision_id FROM runs;
CREATE TABLE external_run_bindings (
 source_instance_id TEXT NOT NULL, external_id TEXT NOT NULL,
 run_id TEXT NOT NULL REFERENCES runs(run_id), bound_at TEXT NOT NULL,
 PRIMARY KEY(source_instance_id,external_id)
);
INSERT INTO external_run_bindings SELECT source_instance_id,external_id,run_id,created_at FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX bindings_run ON external_run_bindings(run_id);
CREATE INDEX runs_experiment ON runs(experiment_id,created_at,run_id);
ALTER TABLE attempts ADD COLUMN run_id TEXT REFERENCES runs(run_id);
ALTER TABLE attempts ADD COLUMN attempt_no INTEGER;
ALTER TABLE attempts ADD COLUMN definition_id TEXT REFERENCES artifacts(artifact_id);
ALTER TABLE attempts ADD COLUMN admission_digest TEXT;
ALTER TABLE attempts ADD COLUMN process_identity_json TEXT;
ALTER TABLE attempts ADD COLUMN end_confirmed_at TEXT;
ALTER TABLE attempts ADD COLUMN launch_token TEXT;
CREATE UNIQUE INDEX attempts_run_no ON attempts(run_id,attempt_no) WHERE run_id IS NOT NULL;
CREATE UNIQUE INDEX attempts_launch_token ON attempts(launch_token) WHERE launch_token IS NOT NULL;
CREATE TABLE commands (
 idempotency_key TEXT PRIMARY KEY, operation TEXT NOT NULL, payload_digest TEXT NOT NULL,
 response_json TEXT NOT NULL, committed_at TEXT NOT NULL
);
CREATE TABLE stages (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), stage_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','failed','skipped')),
 inputs_json TEXT NOT NULL, outputs_json TEXT NOT NULL, reason_code TEXT,
 started_at TEXT, ended_at TEXT, PRIMARY KEY(attempt_id,stage_id), UNIQUE(attempt_id,ordinal)
);
CREATE TABLE attempt_events (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), seq INTEGER NOT NULL CHECK(seq>0),
 event_type TEXT NOT NULL, evidence_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
 PRIMARY KEY(attempt_id,seq)
);
CREATE TABLE resource_leases (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), resource_scope TEXT NOT NULL,
 reserved_at TEXT NOT NULL, released_at TEXT, PRIMARY KEY(attempt_id,resource_scope)
);
CREATE INDEX resource_leases_open ON resource_leases(resource_scope) WHERE released_at IS NULL;
CREATE TABLE budget_scopes (
 scope_id TEXT NOT NULL, dimension TEXT NOT NULL,
 policy_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 limit_value INTEGER NOT NULL CHECK(limit_value>=0), used_value INTEGER NOT NULL CHECK(used_value>=0),
 PRIMARY KEY(scope_id,dimension)
);
CREATE TABLE budget_entries (
 entry_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, dimension TEXT NOT NULL,
 event_key TEXT NOT NULL, attempt_id TEXT REFERENCES attempts(attempt_id),
 amount INTEGER NOT NULL CHECK(amount>=0), kind TEXT NOT NULL CHECK(kind IN ('reserve','legacy_opening')),
 created_at TEXT NOT NULL, FOREIGN KEY(scope_id,dimension) REFERENCES budget_scopes(scope_id,dimension),
 UNIQUE(scope_id,dimension,event_key)
);
CREATE TABLE workflow_instances (
 workflow_id TEXT PRIMARY KEY REFERENCES entities(entity_id),
 workflow_revision_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), row_version INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE workflow_edges (
 workflow_id TEXT NOT NULL REFERENCES workflow_instances(workflow_id),
 workflow_revision_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 parent_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id), child_kind TEXT NOT NULL,
 child_run_id TEXT NOT NULL REFERENCES runs(run_id), created_at TEXT NOT NULL,
 PRIMARY KEY(parent_artifact_id,child_kind,workflow_revision_id), UNIQUE(child_run_id)
);
CREATE TABLE trial_events (
 event_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES entities(entity_id),
 workflow_id TEXT REFERENCES workflow_instances(workflow_id), candidate_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 run_id TEXT REFERENCES runs(run_id), attempt_id TEXT REFERENCES attempts(attempt_id),
 event_kind TEXT NOT NULL, details_json TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE INDEX trial_events_candidate ON trial_events(candidate_id,occurred_at,event_id);
CREATE TABLE publications (
 publication_id TEXT PRIMARY KEY, attempt_id TEXT REFERENCES attempts(attempt_id),
 stage_id TEXT, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 publication_key TEXT NOT NULL UNIQUE, committed_at TEXT NOT NULL
);
CREATE TABLE pointers (
 pointer_name TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 row_version INTEGER NOT NULL CHECK(row_version>=0), updated_at TEXT NOT NULL
);
CREATE TABLE legacy_artifact_bindings (
 legacy_kind TEXT NOT NULL, legacy_id TEXT NOT NULL,
 artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 PRIMARY KEY(legacy_kind,legacy_id)
);
CREATE TABLE source_checkpoints (
 plan_id TEXT NOT NULL REFERENCES artifacts(artifact_id), chunk_key TEXT NOT NULL,
 raw_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 completed_at TEXT NOT NULL, PRIMARY KEY(plan_id,chunk_key)
);
```

`PRAGMA user_version=7`只在回填核对、foreign_key_check及§6检查全通过后于同一事务末尾执行。JSON列必须由严格DTO序列化，拒绝NaN、Infinity、重复键和未知字段；不依赖SQLite扩展JSON函数，以免部署环境不一致。immutable表artifacts/artifact_parents/trial_events/attempt_events/budget_entries/publications由仓储拒绝UPDATE/DELETE；实体名、头、投影和恢复证据按对应命令更新，不提供通用表写入接口。

跨行强制约束：managed的workflow_kind在命令合同枚举内；definition/plan类型与Run匹配；attempt_no为同Run从1递增且非空，definition_id等于Run.definition_id；同Run不得有两个未确认结束的Attempt；producer_attempt必须属于producer_run；stage产物的producer归属与该Attempt一致；latest_revision_id必须属于本Run。SQL不能直接表达的这些约束在同一BEGIN IMMEDIATE事务重验，并提供非法输入反例。历史null不自动符合新对象要求。

## 3. 幂等、事务和端口职责

新增端口位于ports/research.py、ports/data_inputs.py和现有执行/结果端口扩展；持有事务的实现位于adapters/storage，服务不接收Connection。

| 端口命令 | 输入 → 返回 | 必须原子完成 |
| --- | --- | --- |
| save_revision | operation/key/规范载荷、entity/expected_revision、已核验对象引用 → SaveReceipt | 幂等比对、头CAS、artifact/parents登记、头更新、响应存根 |
| admit_run | operation/key、冻结定义/plan、政策、可选workflow边或retry_run_id → AdmissionReceipt | 幂等、输入版本/plan有效期、workflow enabled、资源槽、全部预算、Run/Attempt/Stage、自动边、事件和响应存根 |
| record_transition | attempt_id、预期事件seq、进程身份、状态/证据 → AttemptView | 合法转移、证据与投影；仅确认结束时释放lease |
| reserve_usage | event_key、attempt_id、多个scope/dimension增量 → UsageReceipt | 检查全部限额后一次扣量；任一不足全回滚；同event_key异增量冲突 |
| publish_artifacts | publication_key、已核验不可变对象bundle、父引用、producer → PublicationReceipt | artifact/parents/发布回执、stage outputs与完成事件；结果发布额外写revisions和外部绑定 |
| set_pointer | name、target_ref、expected_version → PointerView | 核验已发布目标、CAS并记录响应；不能替换Run定义 |

幂等键在所有新写命令及旧Attempt命令间平台库唯一。operation包括HTTP方法和规范路径；digest对规范有效载荷计算（不含key、request_id；包含expected_revision、全部版本、资源政策、明确展开后的默认值）。命中相同operation+digest先返回原响应身份，HTTP重放200、replayed=true；无论plan是否已过期或资源已满都不重新准入。不同返回409/idempotency_conflict。校验/预检拒绝不占key、不留半个Run、不扣预算；调用者可修正后重用未成功的key。已提交key无自动过期。

旧attempt.idempotency_key先核对：若无规范化原始请求证明，返回409/legacy_idempotency_unverifiable并带旧attempt_id，不猜测它与新载荷等价。该key不得转用于其他命令。未来旧API也须将新请求规范摘要及commands存根同事务写入；旧库无需从prepared.params猜原请求。

Run不持久化另一份执行状态。RunView从全部Attempt/已发布产物投影；展示latest_attempt_id但历史报告仍绑定生产Attempt。Stage状态只描述步骤，等待用户是workflow投影。工作流暂停后不接受自动边；取消已活动Attempt仍须确认结束，不能因enabled=0释放槽。

## 4. 预算、启动和恢复

budget维度首批为attempts、calls、numerical_evaluations、fetch_requests、download_bytes；均为整数非负。scope_id区分global政策、workflow固定ID与source固定ID。workflow改变政策仅增加/降低limit_value及政策引用，已用量不归零；低于已用量允许保存但阻断新消耗，不杀已准入工作。每次改额也生成不可变budget_policy artifact及HumanDecision。旧policy_revision级账本保留，迁移生成一次legacy_opening，不声称能还原过去每次调用。

Agent Attempt准入计attempts；数值评价准入计numerical_evaluations（含重试成本），统计族仍按唯一候选身份计，不拿预算数当独立试验数。每次外部调用前计calls/fetch_requests；不自动退还，未知结果也占用。新Agent适配器禁止不可见的内部重试，每次实际网络重试新event_key计量；旧RD-Agent的litellm调用单位保留历史解释，未能暴露重试的适配器声明计量粒度，不假称精确网络次数。下载按将读取的最大块预留download_bytes，尾块实际较小也不返还，报告reserved与actual分别显示；预留不足不得读取下一块。

source并发另使用resource_leases的source:<source_id>作用域，采集前BEGIN IMMEDIATE原子检查该源未释放租约数并占位，结束/确认未发送才释放；每Attempt每来源最多一个在途请求，多分块不额外开隐形并发。租约重新占用/释放均追加attempt_events，失联仍占位，不凭租约超时假设网络工作已结束。global:<deployment_id>的租约自准入一直保留到确认终止；同表不同scope不能混计。

每次admit预分配launch_token（UUID）及工作目录身份。独立监督通过持久化事件和执行器身份核对queued；相同token只能拥有一个引擎实例。启动前记录launch_requested，启动后写容器不可复用ID/启动时间/执行器版本；进程身份未知时保持interrupted且占槽。启动已发生而回执丢失，核对token找到原实例，禁止盲目再start。确认从未启动才可记failed/start_failed并释放槽；普通“找不到pid”不是该证据。deadline按确认启动时间+冻结timeout；无法重建可信启动时间时立即请求停止并标时间证据缺失，不改用恢复时间续命。

新自动链依靠监督循环读取已发布父产物、workflow enabled和唯一边，不依赖GET触发。候选事件和预算耗尽进入待处理投影，未准入边不插入workflow_edges。未知外部调用结果需人工决定新Attempt，禁止通过重启自动重放。重试始终整流程重跑，可复用已核验输入块，不宣称Stage断点续跑。

## 5. 对象发布与数据目录

对象写入staging→计算摘要/schema/传递依赖校验→fsync文件→同文件系统不可覆盖rename到按摘要定位的对象区→fsync目录→SQL事务登记artifact/parents/publication。文件已存在须逐字节摘要一致才复用。SQL失败留下不可见孤立对象；自动GC首版禁用，提供审计清单，不删除未知数据。

schema3的新发布事实以SQLite artifacts+publications为准；数据目录的JSON/文件索引是可重建投影，投影失败不能撤销发布。旧schema2外部registry保留原权威与只读解析，通过legacy_artifact_bindings建立有原摘要的引用桥；不搬数据、不改content_digest。统一目录服务合并两种已发布来源，重名不同内容冲突而非覆盖。本文具体化原“原子目录登记”，不再要求SQLite与JSON双写同时成功。

质量报告先引用candidate_data的摘要并独立发布，snapshot再引用它；摘要报告最后生成，避免循环。失败quality report也可发布，但不会生成可消费snapshot。取消与publication提交竞争时按提交事实：已提交快照保留，Attempt可cancelled且publication=published；未提交的不出现published。恢复重做索引/展示报告，不重采集或改质量结论。

## 6. 迁移、回滚与验收

1. 维护模式停止新写入/准入，暂停自动边与监督启动；确认所有资源lease对应进程已结束。schema6没有lease表时逐个核对非终态和未有结束证据的Attempt，不能仅看status。不能确认则迁移阻断，不自动杀用户未知进程。
2. 校验user_version=6与实际表/列/索引指纹；只读登记行数、主键集合及每个历史payload/object摘要。SQLite backup API创建一致性副本，记录备份摘要；同时登记对象存储和外部registry清单，不把WAL库主文件直接拷贝当备份。
3. 迁移连接独占写者，在事务外foreign_keys=OFF，BEGIN IMMEDIATE，执行§2。若任何一步失败ROLLBACK；若执行工具会隐式提交，禁止使用。表重建期间不运行应用。
4. 对每个旧Run建立完全一致external绑定；旧revision/run/Attempt ID与内容、factor/panel、imports及agent_budget逐项守恒。新旧Run行数相同，绑定数等于旧Run数。foreign_key_check无结果，integrity_check=ok，latest_revision归属有效；发现既有异常先阻断并报告，不删除坏行以通过。
5. 写user_version=7、COMMIT，重新打开连接并foreign_keys=ON复查。部署匹配schema7的仓储版本才恢复服务；schema6程序不能读写schema7。v1结果路由用external绑定投影保持原字段/ID；managed尚无结果时不混入旧结果列表，新Run目录使用新路由。
6. 尚未恢复写入时可停止服务、恢复schema6备份与旧程序。恢复写入后不得直接覆盖新库：冻结并保留schema7库及新增对象，优先前向修复；必须回退时恢复备份到独立路径，明确列出备份后待重放命令/产物，显式切换，禁止声称无损降级。旧库/对象均保留。

必须验证：空schema6/含所有历史表/失败注入/重复执行/未知schema/多连接竞争/重启；外键和唯一键反例；同key异载荷、同Run并发重试、跨预算同时抢最后额度、绑定冲突、发布前后崩溃。本文隔离DDL检查不替代这些未来实现测试。新服务启动拒绝未知schema，不自动运行迁移；迁移是独立维护命令。
