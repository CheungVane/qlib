# 共享命令、查询与错误DTO

状态：G0设计版本1，2026-09-29；§1共享闭合校验器已由G1-1实现（`domain/contracts.py`），HTTP/CLI路由与写入仍按G1-2起实施。归属U29/U30/U31，和[物理合同](PHYSICAL_CONTRACT.md)、[产物合同](ARTIFACT_CONTRACT.md)一起使用。新路由均为目标，不能写入当前可用能力清单；已有/v1/research观察路由、/v1/runs结果路由及分析v1/v2保持兼容。

## 1. 类型、序列化与版本

本文件使用闭合记录类型：表列出所有字段，未写“可省略”即必填；`T|null`表示必须传字段但允许null。未知字段422，缺字段422；服务不靠默默丢字段实现前向兼容。JSON媒体类型application/json，UTF-8，禁止重复键/NaN/Infinity。所有新DTO含`schema_version:1`，不是数据库版本、快照版本或analysis_version；修改必填/含义需新DTO版本。

| 类型 | 精确定义 |
| --- | --- |
| Id | `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`，服务新建用UUID；不是路径 |
| Digest | `sha256:`加64个小写十六进制字符；摘要规则见ARTIFACT_CONTRACT |
| Time / Date | UTC RFC3339毫秒时间`YYYY-MM-DDTHH:mm:ss.sssZ` / 当地交易日`YYYY-MM-DD`；范围两端闭合 |
| Ref | `{artifact_id:Id,artifact_type:string,schema_version:positive_integer,content_digest:Digest}`；四字段全部比对，ID存在但其余不符409/reference_mismatch |
| SnapshotRef | Ref且type=dataset_snapshot，schema_version允许2/3；旧快照经显式引用桥解析，摘要算法不重解释 |
| Key | 1—128字符调用方字符串，不含控制字符；平台库全局唯一 |
| WriteMeta | 每个新写请求必含`schema_version:1,idempotency_key:Key`；request_id由服务生成或校验请求头，不入业务载荷 |
| Save | `{entity_id:Id|null,expected_revision:Ref|null,display_name:string,artifact_type:string,payload:object,parent_refs:Parent[]}`；新建两者null，更新两者非null；display_name 1—200字符；payload由产物类型完整定义 |
| Parent | `{role:string,ordinal:integer>=0,ref:Ref}`；同role内ordinal从0连续，顺序有语义；禁止自环/跨主题隐式引用 |
| Check | `{code:string,status:pass\|warn\|fail\|not_checked\|not_applicable,message:string,field_path:string|null,blocking:boolean}` |

所有Ref只能指已发布版本；禁止latest、当前路径或无摘要ID代替。entity_id用于草稿版本CAS，artifact_id用于不可变读取；expected_revision=null不是“忽略冲突”。display_name不进入内容摘要，但名称更新与保存版本同一命令、同一CAS。数值大面板不放请求体，默认新接口JSON上限1 MiB，字符串原文上限32,768 Unicode字符、parents最多64、候选选择最多3；超限413/payload_too_large。旧接口原有限制不因此改变。

## 2. 命令目录及完整入参

下表body均合并WriteMeta，除明确枚举外不接受附加参数。Save的payload见产物合同；只允许各行指定artifact_type。没有发布对应引擎载荷schema的能力必须拒绝，不能接一个任意config字典就运行。

| 方法 / 路由 | body（不重复列WriteMeta） | 返回 |
| --- | --- | --- |
| POST /v1/experiments | `display_name:string,description:string`（0—32768字符） | ExperimentView，201 |
| POST /v1/research-inputs | `experiment_id:Id` + Save，type=research_input | SaveReceipt，201/同内容200 |
| POST /v1/research-definitions | `experiment_id:Id` + Save，type=research_definition | SaveReceipt，201/200 |
| POST /v1/data-pipeline-definitions | Save，type=data_definition | SaveReceipt，201/200 |
| POST /v1/data-preparation-plans | `definition_ref:Ref,base_snapshot_ref:SnapshotRef|null` | SaveReceipt+`checks:Check[]`，201/200；无采集 |
| POST /v1/data-pipeline-runs | `plan_ref:Ref,execution_policy_ref:Ref` | AdmissionReceipt，202/重放200 |
| POST /v1/research-runs | `definition_ref:Ref,execution_policy_ref:Ref` | AdmissionReceipt，202/200 |
| POST /v1/research-runs/{run_id}/retry | `definition_ref:Ref,execution_policy_ref:Ref` | AdmissionReceipt，202/200；仅失败/取消/中断且结束已确认 |
| POST /v1/research-workflows | `experiment_id:Id` + Save，type=research_workflow | SaveReceipt，201/200 |
| POST /v1/research-workflows/{id}/start | `workflow_ref:Ref,execution_policy_ref:Ref` | AdmissionReceipt+`workflow_id:Id`，202/200 |
| POST /v1/research-workflows/{id}/stop | `workflow_ref:Ref,expected_version:integer>=0` | WorkflowView，200；先禁止新边，再对活动Attempt逐个请求取消 |
| POST /v1/research-handoffs | `experiment_id:Id,parent_artifact_ref:Ref,target_kind:direction\|hypothesis\|formula,selected_candidate_refs:Ref[],decision:accept\|revise\|explore_anyway,reason:string` | HandoffReceipt，201/200；只创建草稿，不执行 |
| POST /v1/research-decisions | `experiment_id:Id,subject_ref:Ref,decision:accept\|revise\|reject\|defer\|explore_anyway,reason:string` | SaveReceipt(type=human_decision)，201/200 |
| POST /v1/research-workflows/{id}/budget | `workflow_ref:Ref,expected_version:integer>=0,limits:BudgetLimits,reason:string` | WorkflowView，200；保留used，生成政策和决定版本 |
| POST /v1/data-default | `snapshot_ref:SnapshotRef,expected_version:integer>=0` | PointerView，200；不存在指针expected_version=0，新版本从1计 |
| POST /v1/research-runs/{run_id}/cancel | `attempt_id:Id` | AttemptView，202/已确认终态200；必须属于该Run |

工作流entity一次只start一个instance，重复启动用新key返回409/workflow_already_started；再次独立研究须复制为新工作流entity，来源关联和所见测试记录保留。start不能将旧已运行entity的head换成新版后清空账本。保存定义与启动分离；start冻结的数据引用从workflow_ref解析生成对应research_definition，不能在运行中补入。直接公式入口将已保存research_input.content按确定规则生成formula_proposal（hypothesis_ref=null，未知单位由编译诊断，禁止猜字段），随定义一起持久化；不用用户伪造已编译formula_ref。正式compute必须消费随后产生且通过校验的factor_definition；Stage输入中登记该确切引用，Run定义仍保留原提案不改写。

handoff只允许方向候选→假设、假设候选→公式；target_kind=direction仅用于同类型显式改写（selected为空，decision=revise），不得作为自动回边。同类假设/公式改写也只允许decision=revise且selected为空；其他交接必须1—3个候选、属于parent包且type匹配。多个选择各产生一个input草稿；reason在revise/explore_anyway时非空，普通accept允许空。跨主题复制通过先新建Experiment、再保存带`copied_from`父引用的新输入，并继承已见样本事件；不能使用handoff隐式改主题。

政策保存不开放通用HTTP任意写入；首版由部署配置经校验登记不可变policy Ref。预算修订是唯一用户可见额度修改命令，不能提高部署全局上限。预览plan只做目录能力检查，不调用付费Agent或下载；无法确定日期/范围不保存伪计划，409/precondition_failed。

### 返回类型

| 类型 | 全部字段（另统一含schema_version=1、request_id:string） |
| --- | --- |
| SaveReceipt | `entity_id:Id|null,artifact_ref:Ref,created:boolean,replayed:boolean` |
| ExperimentView | `experiment_id:Id,display_name:string,description:string,row_version:integer,created_at:Time` |
| AdmissionReceipt | `run_id:Id,attempt_id:Id,attempt_no:positive_integer,status:queued,definition_ref:Ref,plan_ref:Ref|null,execution_policy_ref:Ref,created:boolean,replayed:boolean`；重放保留准入时status，当前状态用Location查询 |
| HandoffReceipt | `inputs:Ref[],decision_ref:Ref,experiment_id:Id,created:boolean,replayed:boolean` |
| PointerView | `name:"default_research_snapshot",snapshot_ref:SnapshotRef,row_version:positive_integer,replayed:boolean` |
| AttemptView | `attempt_id:Id,run_id:Id|null,association:managed\|legacy_unknown,attempt_no:integer|null,status:EXEC02枚举,definition_ref:Ref|null,execution_policy_ref:Ref|null,stage_views:StageView[],cancel_requested_at:Time|null,deadline_at:Time|null,end_confirmed_at:Time|null,error:ErrorDetail|null,publication_refs:Ref[],created_at:Time` |
| StageView | `stage_id:string,ordinal:integer,state:pending\|running\|succeeded\|failed\|skipped,input_refs:Ref[],output_refs:Ref[],reason_code:string|null,started_at:Time|null,ended_at:Time|null` |
| RunView | `run_id:Id,origin:managed\|imported,workflow_kind:string|null,experiment_id:Id|null,definition_ref:Ref|null,plan_ref:Ref|null,latest_attempt_id:Id|null,attempts:AttemptView[],artifact_refs:Ref[],created_at:Time` |
| WorkflowView | `workflow_id:Id,workflow_ref:Ref,row_version:integer,enabled:boolean,state:ready\|running\|awaiting_input\|blocked\|completed\|stopped,runs:RunLink[],edges:EdgeView[],budget:BudgetView[],attention:Check[]` |
| RunLink / EdgeView | `{run_id:Id,latest_attempt_id:Id|null}` / `{parent_ref:Ref,child_kind:string,child_run_id:Id}` |
| BudgetView | `{scope_id:string,dimension:string,limit:integer,used:integer,remaining:integer,policy_ref:Ref}`；remaining=max(0,limit-used) |
| ErrorDetail | `{code:string,message:string,details:object}`；details为下方按错误码定义的结构 |

RunView.attempts最多最近20项，超过时另外必含`attempts_next_cursor:string|null`（所有RunView均返回此字段）；workflow runs/edges各最多100，超过时分别返回`runs_next_cursor/edges_next_cursor`，所有WorkflowView都返回两字段。其他字段不得以截断丢失代替分页。没有Attempt的Run不推断succeeded；workflow completed表示所有所选自动链已终止且产物/业务否定均已登记，不表示统计成立；存在需用户回答优先awaiting_input，硬门禁/预算优先blocked，用户停止为stopped，运行中为running。具体阻断原因保持独立Check，不压成状态名。

## 3. 查询与分页

所有新GET无业务副作用，不启动计算/采集/发布。读取对象缺失或载荷漂移不回退旧版本。

| GET路由 | 查询字段 / 响应 |
| --- | --- |
| /v1/experiments/{id} | ExperimentView |
| /v1/research-inputs/{id}、/v1/research-artifacts/{id} | id为artifact_id；ArtifactEnvelope（ARTIFACT_CONTRACT），大载荷只有manifest，不内嵌二进制 |
| /v1/research-runs/{id}、/v1/data-pipeline-runs/{id} | RunView；后者另含publication_status、quality_report_ref:null或Ref、snapshot_ref:null或Ref |
| /v1/research-runs | 可省略experiment_id、workflow_kind、origin；游标分页RunSummary：RunView去掉attempts/artifact_refs/attempts_next_cursor，添加artifact_count |
| /v1/research-runs/{id}/attempts | 游标分页AttemptView |
| /v1/research-workflows/{id} | WorkflowView |
| /v1/research-workflows/{id}/runs、/edges | 游标分页RunLink / EdgeView |
| /v1/data-quality-reports/{id} | QualityReport payload及Ref |
| /v1/data-quality-reports/{id}/issues | 游标分页Issue（产物合同），可省略severity、field、instrument_id；过滤条件入游标 |
| /v1/workbench-presets | 游标分页PresetView：部署已登记的可选模板/政策引用，不启动运行 |
| /v1/data-sources、/v1/research-agent-capabilities | 游标分页CapabilityView |
| /v1/artifacts/{id}/download | 已登记且允许导出的文件流；可选part_id只能从manifest选，不接收path/URL；类型/长度/hash响应头，禁目录遍历 |

分页统一`{schema_version:1,request_id,items:[],next_cursor:string|null}`，limit可省略默认20、1—100；非法422。游标签名绑定过滤/排序/最高已见序号或时间+ID边界；新对象不挤入已开始遍历，过期409/cursor_expired，用户可重新查第一页；不支持客户端自由SQL排序。Run按created_at/run_id倒序，Attempt按attempt_no/attempt_id倒序，artifact问题按稳定ordinal。无上游请求的能力检查显示observed_at，不用GET重新探测供应商。

CapabilityView全部字段：`capability_ref:Ref,capability_id,provider_id,adapter_version,operation,status,configured,verified_at:Time|null,observed_at:Time,components:string[],limits:object,checks:Check[],evidence_refs:Ref[]`；status=ready/limited/blocked/not_configured/not_implemented。limits仅使用已定义Policy中的整数/枚举字段，未知值null；不含secret_ref或本机路径。ready须实际适配验收证据，不能按类已注册推断。

PresetView全部字段：`preset_id:Id,title:string,workflow_kind:string,execution_policy_ref:Ref,resource_policy_ref:Ref|null,rule_refs:Ref[],field_contract_refs:Ref[],engine_binding_ref:Ref|null,protocol_ref:Ref|null,status:ready|limited|blocked,checks:Check[]`。UI由此取得完整版本引用，不拼接政策ID；模板名称不构成执行能力证明。部署初始化仅登记经过校验的配置/规则artifact，不启动任务、不导入样例行情；缺所需类型/实例则模板blocked。

## 4. 错误及HTTP/CLI映射

统一HTTP错误`{code,message,request_id,details}`，没有成功schema_version字段。message面向用户，字段定位用JSON Pointer，不返回栈/密钥/本机绝对路径。

| HTTP / code | details固定字段 | CLI退出 |
| --- | --- | --- |
| 422/validation_error | `errors:[{path,rule,message}]` | 2 |
| 413/payload_too_large | `limit_bytes,actual_bytes`（字符/集合超限则用422） | 2 |
| 404/not_found | `resource_type,resource_id` | 3 |
| 409/reference_mismatch | `artifact_id,expected_digest,provided_digest` | 3 |
| 409/revision_conflict | `entity_id,expected_revision:Ref|null,current_revision:Ref|null` | 3 |
| 409/version_conflict | `resource_id,expected_version,current_version`；workflow/pointer CAS | 3 |
| 409/idempotency_conflict | `idempotency_key,original_operation`，不泄露原请求 | 3 |
| 409/legacy_idempotency_unverifiable | `attempt_id` | 3 |
| 409/binding_conflict | `source_instance_id,external_id,bound_run_id,target_run_id` | 3 |
| 409/plan_expired | `plan_ref,expired_at` | 3 |
| 409/precondition_failed、capability_unavailable、formula_not_executable | `checks:Check[]` | 3 |
| 409/capacity_exceeded、budget_exhausted | `scope_id,dimension,limit,used,requested`；并发dimension=concurrency | 3 |
| 409/retry_not_allowed、workflow_already_started | `run_id:Id|null,workflow_id:Id|null,reason_code` | 3 |
| 409/cursor_expired | `restart_url`（本服务相对路径） | 3 |
| 409/content_mismatch | `artifact_id,component,expected_digest,actual_digest` | 3 |
| 503/storage_unavailable | `retryable:boolean` | 4 |
| 500/internal_error | `{}`；细节仅脱敏内部日志 | 4 |

WriteMeta成功重放时新request_id，业务Receipt身份/原冻结字段不变；replayed=true、created=false。202不保证完成，Location指向相应Run查询；CLI提交成功退出0并输出同一Receipt，不隐式等待。CLI `qwb research {experiment-create,input-save,definition-save,run-start,run-retry,workflow-save,workflow-start,workflow-stop,handoff,decision,budget}`及`qwb data {definition-save,plan,run,default}`用`--request <JSON文件>`承载完整body，路径参数用`--id`/`--run-id`；查询对应`show/list`命令及游标。CLI不自行展开另一套默认参数或改变错误语义。

## 5. 贯穿示例（标识为示意，不是可调用真实对象）

下面合法JSON用固定示意摘要，实际须从保存/查询响应取得Ref；不能复制后当真实已登记版本。数据方案内容见产物合同。

```json
{"schema_version":1,"idempotency_key":"prepare-1","plan_ref":{"artifact_id":"P1","artifact_type":"data_plan","schema_version":1,"content_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"execution_policy_ref":{"artifact_id":"EP1","artifact_type":"execution_policy","schema_version":1,"content_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}
```

准入返回202、Location=/v1/data-pipeline-runs/R1，完整响应示例：

```json
{"schema_version":1,"request_id":"req-1","run_id":"R1","attempt_id":"A1","attempt_no":1,"status":"queued","definition_ref":{"artifact_id":"D1","artifact_type":"data_definition","schema_version":1,"content_digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},"plan_ref":{"artifact_id":"P1","artifact_type":"data_plan","schema_version":1,"content_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"execution_policy_ref":{"artifact_id":"EP1","artifact_type":"execution_policy","schema_version":1,"content_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"created":true,"replayed":false}
```

同键同请求200返回同R1/A1（created=false、replayed=true）；改plan而复用prepare-1返回如下错误，不能创建R2：

```json
{"code":"idempotency_conflict","message":"此请求标识已用于另一组输入，请刷新后重新提交。","request_id":"req-2","details":{"idempotency_key":"prepare-1","original_operation":"POST /v1/data-pipeline-runs"}}
```

成功快照S1→research_input I1→workflow W1（辅助模式）→start生成R2/A2→Review/候选H1→handoff保存I2，全部引用完整Ref。方向评议decision=rejected仍可A2 succeeded；数值输入必需字段缺失则在start返回409 checks，不产生Attempt。公式报告E1被人工选择进训练定义D3时登记selection事件，模型M1/预测Y1后用于回测D4；改费用产生D5和新Run，M1/Y1保持原引用。详细时序与账本在PHYSICAL_CONTRACT，不能通过接口重放绕过预算。
