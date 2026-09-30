# 版本产物、输入准备及首批政策合同

状态：G0设计版本1，2026-09-29；仅spec。本文定义[命令DTO](COMMAND_CONTRACT.md)的payload和[物理存储](PHYSICAL_CONTRACT.md)的不可变对象；引用的数据/统计含义仍归DATA_PIPELINE、DATA_PROCESSING、HUMAN_RESEARCH、FACTOR_ANALYSIS与VALIDATION。所有下表字段必填；nullable写`|null`，空集合显式`[]`，未知不能填0。不支持的载荷版本拒绝，不能当任意JSON透传。

## 1. 通用封套与摘要

ArtifactEnvelope完整字段：`artifact_id:Id,artifact_type:string,schema_version:positive_integer,content_digest:Digest,entity_id:Id|null,created_at:Time,producer:{run_id:Id|null,attempt_id:Id|null,author_kind:user_authored|agent_generated|platform_computed|imported,author_ref:string|null},parent_refs:Parent[],payload:<按类型>,provenance:{market_data_kind:string|null,source_class:string|null,evidence_refs:Ref[],limitations:string[]}`。来源枚举严格用PROVENANCE_AUDIT，null表示该产物无行情，不用新source_class冒充原定义。已消费行情的派生产物必须保留其真实/模拟分类，不允许null规避。

新artifact的摘要输入仅为`{artifact_type,schema_version,parent_refs,payload,provenance}`；ID/创建时间/显示名/producer不参与内容哈希。科学或执行身份需要的种子、代码/规则版本、agent/model/prompt身份必须显式进入payload，不能仅放producer。parent_refs按(role,ordinal)排序，集合字段按各自规定排序，数组有业务顺序则保序。使用规范JSON：键按Unicode码点排序、UTF-8、不转义非ASCII、无空白、禁止重复键和非有限数；整数十进制无前导0；身份参数中的非整数用规范十进制字符串（无多余尾0，负零为"0"），禁止浮点跨语言格式影响身份。数值面板/报告的大规模double存分块文件，只以字节摘要入manifest。新payload的小型统计标量亦用十进制字符串或null，显示端转换不能回写摘要。计算比率用分子/分母精确计数，展示/报告比率舍入到17位有效十进制数字（ties-to-even）；计数是复算权威，不能根据已舍入比率反推分母。

存储的整个封套另有文件字节SHA，object_key按该文件SHA定位；content_digest是上述语义摘要，两者不可混淆。相同entity/type/content复用既有artifact；其他entity可产生不同artifact_id但相同content_digest，不能因此删除独立研究行为。dataset_snapshot schema2引用桥是例外：Ref.content_digest保留原快照digest，封套注明`digest_scheme=legacy_snapshot_v2`，解析同时核验封套文件SHA和原登记摘要；不能按新算法重算后改旧版本。schema3快照使用下述独立清单算法，Ref.type=dataset_snapshot、schema_version=3，亦不套普通产物摘要。

Id、Ref、Parent、Time、Date、Check来自COMMAND_CONTRACT。Payload中Ref类型必须与字段指定对象匹配；普通rule/policy引用通过通用schema登记，只允许部署验证过的类型/版本。初版artifact_type注册清单为本文各表列值及下方技术类型；新增类型需先更新spec及validator，不能运行时随意注册。

## 2. 研究输入、定义与固定链

| artifact_type | payload完整字段 |
| --- | --- |
| research_input | `experiment_id:Id,input_kind:direction|hypothesis|formula,content:string,language:string,hypothesis_type:causal|risk_premium|behavioral|statistical|unspecified,market:string,frequency:day,constraints:string[],attachments:Ref[],author:user|agent`；content非空且≤32768字符 |
| research_workflow | `experiment_id:Id,input_ref:Ref,entry_kind:direction_review|hypothesis_review|formula_evaluate,mode:assisted|automatic,snapshot_ref:SnapshotRef|null,protocol_ref:Ref|null,reference_set_ref:Ref|null,agent_binding:AgentBinding,budget_policy_ref:Ref,stop_after:review|factor_report,selection_rule:feasibility_then_source_order,code_ref:Ref`；automatic必须绑定全部数值输入、stop_after=factor_report |
| research_definition | `experiment_id:Id,workflow_kind:direction_review|hypothesis_review|formula_evaluate|train|mine|backtest,inputs:<下表判别类型>,seed:integer,code_ref:Ref`；0≤seed≤2^63-1 |
| human_decision | `experiment_id:Id,subject_ref:Ref,decision:accept|revise|reject|defer|explore_anyway,reason:string,actor:user,decided_at:Time,followup_refs:Ref[]` |
| review | `input_ref:Ref,review_kind:direction|hypothesis|formula,decision:ready_to_test|needs_clarification|not_supported|rejected,intent_summary:string,mechanism_type:causal|risk_premium|behavioral|statistical,target:string,expected_sign:positive|negative|unspecified,horizons:integer[],mechanism_steps:string[],alternatives:string[],falsification:string[],data_requirements:string[],known:string[],unknown:string[],citations:Citation[],candidate_refs:Ref[],agent_binding:AgentBinding,usage:Usage,question:string|null` |
| hypothesis_proposal | `statement:string,expected_sign:positive|negative|unspecified,horizons:integer[],variables:Variable[],mechanism:string,falsification:string[],pending_questions:string[],input_ref:Ref` |
| formula_proposal | `hypothesis_ref:Ref|null,expression:string,math_explanation:string,variables:Variable[],lookback_sessions:integer>=0,signal_timing:session_close,expected_sign:positive|negative|unspecified,missing_policy:propagate_null,limitations:string[]` |
| factor_definition | `expression:string,ast:AST,operator_registry_ref:Ref,field_contract_ref:Ref,unit:string,lookback_sessions:integer>=0,signal_timing:session_close,parameters:Parameter[],preprocessing_ref:Ref|null,compiler_ref:Ref` |

发布一个评议包时先登记候选（候选只引用已发布输入/假设），再登记引用候选的review；候选与review的同次生产关系由Run/Attempt/Stage记录，不让候选反向持有尚不存在的review摘要。TrialLedger快照只包含截至评价前的事件，报告发布事件随后追加，不让报告与账本摘要循环依赖。

AgentBinding全部字段：`agent_id,adapter_version,model_id,model_version:string|null,prompt_ref:Ref,output_schema_version:1,capabilities:string[],allowed_tools:string[]`；capabilities为HR05四项子集，不能为空。model_version未知必须null并显示不可精确重现，不用当前安装版本补历史。Citation=`{title,url,accessed_at:Time|null,evidence_kind:retrieved|user_supplied|unverified}`，unverified不得呈现为检索支持。Usage=`{calls:integer,tokens_in:integer|null,tokens_out:integer|null,cost_decimal:string|null,currency:string|null,measurement:exact|partial|unknown}`。Variable=`{name,meaning,unit,field_name:string|null}`；Parameter=`{name,value:string}`，名称唯一。

AST是封闭联合：`{op:"field",name:string}`、`{op:"constant",value:decimal_string}`、`{op:<已登记算子>,args:AST[],window:positive_integer|null}`；无其他字段，算子参数数量/窗口/单位按HR06，field/constant节点不带args/window。编译产物重算AST摘要并检查禁未来，不能信任Agent提供的lookback。预处理null表示无拟合变换，不表示隐含全样本标准化。

### research_definition.inputs 判别类型

| workflow_kind | 完整inputs |
| --- | --- |
| direction_review / hypothesis_review | `input_ref:Ref,agent_binding:AgentBinding,snapshot_ref:SnapshotRef|null,protocol_ref:Ref|null`；null明确not_required_for_text_review，模型/组合字段不出现而不是伪造空模型 |
| formula_evaluate | `input_ref:Ref,agent_binding:AgentBinding,formula_ref:Ref,preparation_ref:Ref,protocol_ref:Ref,reference_set_ref:Ref`；formula_ref可为formula_proposal/已编译factor_definition，开始compute前必须生成通过编译的definition |
| train | `preparation_ref:Ref,feature_refs:Ref[],validation_plan_ref:Ref,preprocessing_ref:Ref,engine_binding_ref:Ref,model_spec_ref:Ref,evaluation_protocol_ref:Ref,selection_evidence_refs:Ref[]` |
| mine | `preparation_ref:Ref,generator_binding_ref:Ref,search_policy_ref:Ref,evaluation_protocol_ref:Ref,reference_set_ref:Ref,trial_scope_id:Id` |
| backtest | `preparation_ref:Ref,strategy_ref:Ref,signal_input:<联合>,execution_scenario_ref:Ref,evaluation_protocol_ref:Ref,engine_binding_ref:Ref` |

signal_input为`{kind:"prediction",prediction_ref:Ref}`或`{kind:"model",model_ref:Ref,inference_preparation_ref:Ref}`或`{kind:"factor_rule",factor_panel_refs:Ref[]}`。规则必须在strategy_ref，禁止裸面板直接作为权重；model路线只predict不fit。train/mine/backtest承接已有目标，但具体model_spec/generator/execution_scenario及engine_binding的各引擎配置schema仍需在该适配器实施前冻结，当前不能声明这些类型已可运行；共用封套/交接字段不再留白。

## 3. 数据方案、计划与批次

| 类型 | payload完整字段 |
| --- | --- |
| data_definition | `market,frequency:day,timezone,universe_ref:Ref,date_rule:DateRule,components:ComponentRequest[],source_bindings:SourceBinding[],acquisition_mode:online_fetch|registered_import,update_mode:full|incremental,revision_policy_ref:Ref,merge_policy_ref:Ref,cleaning_policy_ref:Ref,quality_policy_ref:Ref,resource_policy_ref:Ref,output_schema_version:3` |
| data_plan | `definition_ref:Ref,date_range:{start:Date,end:Date},universe_ref:Ref,calendar_ref:Ref,source_plans:SourcePlan[],base_snapshot_ref:SnapshotRef|null,estimated_chunks:integer|null,estimated_bytes:integer|null,estimated_rows:integer|null,checks:Check[],created_at:Time,expires_at:Time` |
| raw_batch | `plan_ref:Ref,source_id,adapter_version,request_digest:Digest,source_revision:string|null,requested_range:{start:Date,end:Date},actual_range:{start:Date|null,end:Date|null},chunk_key,files:FilePart[],completion:{local:verified|failed,remote:verified|unknown|failed,evidence_refs:Ref[]},fetch_requests:integer,actual_bytes:integer,fetched_at:Time` |
| normalized_batch | `raw_refs:Ref[],canonical_schema_version:1,mapping_ref:Ref,calendar_ref:Ref,security_mapping_ref:Ref,price_basis_ref:Ref,parts:FilePart[],lineage_ref:Ref,missing_reasons_ref:Ref,transforms:TransformCount[]` |
| candidate_data | `plan_ref:Ref,normalized_refs:Ref[],merge_policy_ref:Ref,parts:FilePart[],lineage_ref:Ref,conflicts_ref:Ref|null,field_contract_ref:Ref,calendar_ref:Ref,membership_ref:Ref,availability_ref:Ref` |
| quality_report | `candidate_ref:Ref,plan_ref:Ref,policy_ref:Ref,conclusion:pass|limited|fail,publication_decision:allowed|blocked,counts:FieldCounts[],checks:Check[],uses:UseVerdict[],confidence:Confidence,issue_parts:FilePart[],issue_count:integer,coverage:Coverage,source_completion:Check[],transform_counts:TransformCount[]` |

full计划的base_snapshot_ref必须null；incremental必须非null且与目标market/frequency/证券及复权语义兼容。plan.definition_ref必须与提交的数据方案确切版本一致，expires_at严格晚于created_at；source_plans不能新增定义中未授权来源。actual_range两端同时null表示有效空响应，不等于获取失败；completed证据仍需单独验证。

DateRule=`{kind:"absolute",start:Date,end:Date}`或`{kind:"latest_complete_session",start:Date}`；解析只在创建plan发生。ComponentRequest=`{component,fields:string[],required:boolean}`。SourceBinding=`{source_id,capability_ref:Ref,component,field_group,role:primary|supplement|validator,priority:integer>=0,required:boolean,fallback_allowed:boolean}`，同组priority唯一。SourcePlan=`{source_id,capability_ref:Ref,query_digest:Digest,release_id:string|null,boundary:{start:Date,end:Date},chunks:Chunk[],limitations:string[]}`；Chunk=`{chunk_key,instrument_ids:Id[],start:Date,end:Date}`，无版本锁的release_id=null。

FilePart=`{part_id,object_digest:Digest,byte_size:integer>=0,row_count:integer|null,serialization:parquet|csv|json|binary,schema_ref:Ref|null,partition:{market:string|null,frequency:string|null,year:integer|null},sort_keys:string[]}`。大文件不在manifest存本机路径；定位由object_digest到受控存储映射。binary需在所属类型另声明格式/加载能力，不能任意反序列化用户pickle。Parquet/CSV要求schema_ref，CSV固定UTF-8、逗号、LF、首行列名、RFC4180引用、空串为null；原始真实空字符串需要在normalize前计blank原因，CSV层不再猜来源。double数值文件允许空，不允许Inf，NaN在规范层归null。

TransformCount=`{transform_ref:Ref,applied_cells:integer,reason}`；FieldCounts=`{field,E:integer|null,V:integer,A:integer|null,N:integer,I:integer,X:integer|null,blank:integer,D:integer|null,missing_rate:decimal_string|null,invalid_rate:decimal_string|null,valid_rate:decimal_string|null}`，分母未知的E/A/X/D和比率为null，不能要求未知E仍满足求和；已知时遵守ING06。UseVerdict=`{use:price_description|exploratory_factor|pit_training|portfolio_backtest,status:available|limited|blocked,reasons:string[]}`。Issue=`{ordinal:integer,severity:warning|error,code,field:string|null,instrument_id:Id|null,session_date:Date|null,source_id:string|null,message}`。Coverage=`{requested_start:Date,requested_end:Date,actual_start:Date|null,actual_end:Date|null,instrument_count:integer,session_count:integer,missing_required_rows:integer|null,unaffected_rows:integer|null}`。

Confidence=`{source_evidence:{source_classes:string[],manifest_verification:verified|partial|unknown,independence:independent|shared_upstream|unknown},structural:Check[],cross_source:{comparable:integer,agree:integer,expected:integer|null,coverage:decimal_string|null,agreement:decimal_string|null},historical_availability:{known:integer,total:integer,status:complete|partial|unknown}}`。comparable=0时agreement=null；expected=0/null时coverage=null；这不是正确概率。

### DatasetSnapshot schema3

payload完整字段：`digest_scheme:"snapshot_manifest_v3",candidate_ref:Ref,quality_report_ref:Ref,raw_refs:Ref[],normalized_refs:Ref[],field_contract_ref:Ref,calendar_ref:Ref,membership_ref:Ref,availability_ref:Ref,merge_policy_ref:Ref,cleaning_policy_ref:Ref,parts:FilePart[],market,frequency:day,timezone,allowed_uses:UseVerdict[]`。快照content_digest=sha256(规范JSON的`{schema_version:3,payload}`)，不含外层ID/创建时间/producer。传递摘要校验包含所有Ref和FilePart。质量报告的candidate_ref不能指snapshot，以免成环；报告验证通过不等于用途全部available。

CDF1字段schema注册为field_contract：`fields:[{name,logical_type:string|date|timestamp|float64|bool,nullable:boolean,unit,role:key|observation|metadata,missing_policy:string}],primary_key:string[],sort_keys:string[],price_basis_ref:Ref|null`。规范bar键instrument_id/frequency/session_date，status键instrument_id/session_date；其他记录族按DATA_PIPELINE。实体关系/时间及列名在读取前检查，列顺序不能按位置猜。可用时间旁表必须能定位每个非空字段值的available_at和依据；缺依据显式unknown。

## 4. 统一输入准备、面板与下游产物

输入准备是声明请求和实际产物两件事，禁止只保存“用了S1”。

| 类型 | payload完整字段 |
| --- | --- |
| preparation_request | `snapshot_ref:SnapshotRef,calendar_ref:Ref,membership_ref:Ref,field_contract_ref:Ref,feature_refs:Ref[],label_ref:Ref|null,sample_plan_ref:Ref,availability_mode:strict_pit|exploratory,missing_policy:propagate_null,alignment_version:string,code_ref:Ref` |
| prepared_input | `request_ref:Ref,snapshot_ref:SnapshotRef,axis_ref:Ref,feature_parts:FilePart[],label_parts:FilePart[],membership_mask_parts:FilePart[],feature_validity_parts:FilePart[],label_validity_parts:FilePart[],availability_parts:FilePart[],exclusions_ref:Ref,logical_input_digest:Digest,checks:Check[],limitations:string[]` |
| label_definition | `field_name,price_basis_ref:Ref,horizons:positive_integer[],formula_version,entry_timing:next_session|session_close,exit_timing:session_close,full_window_required:true,tradability_policy_ref:Ref`；horizons升序去重，未知公式版本拒绝 |
| sample_plan | `start:Date,end:Date,warmup_sessions:integer>=0,universe_ref:Ref,selection_intervals:Interval[],folds:Fold[],embargo_sessions:integer>=0,label_boundary_policy:drop_cross_partition_labels` |
| factor_panel | `definition_ref:Ref,prepared_input_ref:Ref,axis_ref:Ref,parts:FilePart[],validity_parts:FilePart[],compiler_ref:Ref,computation_ref:Ref,date_count:integer,instrument_count:integer,valid_count:integer,unit` |
| factor_evaluation | `panel_refs:Ref[],prepared_input_ref:Ref,protocol_ref:Ref,reference_set_ref:Ref,analysis_version:integer,metrics_parts:FilePart[],exclusions_ref:Ref,trial_ledger_ref:Ref,outcome:completed|limited|unavailable,limitations:string[]` |
| model | `model_spec_ref:Ref,engine_binding_ref:Ref,prepared_input_ref:Ref,fold_id,feature_contract_ref:Ref,preprocessing_state_ref:Ref,label_ref:Ref,fit_interval:Interval,validation_plan_ref:Ref,weights:FilePart[],code_ref:Ref,environment_ref:Ref,seed:integer` |
| prediction | `model_ref:Ref,prepared_input_ref:Ref,fold_id:string|null,parts:FilePart[],signal_availability_parts:FilePart[],feature_contract_ref:Ref,code_ref:Ref` |
| strategy | `signal_kind:model|factor_rule,model_ref:Ref|null,factor_definition_refs:Ref[],signal_rule_ref:Ref,portfolio_rule_ref:Ref,risk_rule_ref:Ref` |
| materialization | `prepared_input_ref:Ref,target_format,adapter_ref:Ref,parts:FilePart[],logical_input_digest:Digest,equivalence_report_ref:Ref` |

Interval=`{start:Date,end:Date}`；Fold=`{fold_id,train:Interval,valid:Interval|null,test:Interval}`，同折区间按日历互斥有序，标签完整窗口必须留在所属分区，embargo按VALIDATION处理。axis产物=`{calendar_ref:Ref,dates:Date[],instrument_ids:Id[],order:"date_major",axis_digest:Digest}`；dates完整交易日升序，instrument_ids稳定ID升序。大轴用FilePart替代数组时必须axis schema2，不允许同版本两种任意表现。

每份分块按axis坐标标识，不依靠行号隐式对齐；feature矩阵绝不提供label有效掩码作为可计算特征。训练和因子评价可在评价阶段用label_validity交集，但这不能改变当时特征是否可计算的事实。prepared_input逻辑摘要覆盖请求、轴、有效值/空值及原因的规范行流；明确定义行序(date,instrument,field)、数值double为IEEE754小端8字节、null单独标记0x00、非空0x01后跟值，字符串UTF-8前缀uint32小端长度；字段名和行坐标也按字符串编码。流头包含规范请求摘要及轴摘要。物化文件字节变化不改变该逻辑摘要，但转换后的值/空值/轴必须同源独立重算等价报告；仅复制一个hash字符串不是验证。

参考集reference_set=`{panel_refs:Ref[],signs:positive|negative数组,selection_interval:Interval|null,selection_reason}`，两个数组等长且顺序对应；空参考集合法，正交统计unavailable/no_reference_set，不把空集等同“完全正交”。评价协议evaluation_protocol=`{label_ref:Ref,sample_plan_ref:Ref,horizons:positive_integer[],primary_horizon:positive_integer,analysis_version:integer,orthogonal_version:string|null,multiple_testing_policy_ref:Ref,reference_set_ref:Ref}`；primary必须在horizons，FACTOR_ANALYSIS的新正交必须用已验对应版本，否则阻断该指标/能力，不默默回退。

model推理比对feature_contract/单位/顺序/预处理状态；不得重新fit。模型文件存在不是输入契约可兼容证据。回测交易/账户产物沿用RESULT_CONTRACT中立结果包，并绑定strategy/prediction/scenario/prepared_input的父引用；公司行动/原价不可支持时拒绝真实组合回测，不编造成交。新增训练引擎载荷仍需对应适配契约，不把本表当所有Qlib配置已冻结。

## 5. 政策默认值与能力矩阵

以下是产品工程默认，非市场规则或统计有效性保证；实施时落配置并生成不可变policy，禁止写死在UI。既有CPU/内存/全局并发/墙钟/Agent政策继续以configs/workbench/execution_policy.json实际版本为准，本轮不改文件。有效限额为全局政策与任务/工作流上限中更严者，不能靠换任务类型绕过全局资源限制。

| 政策字段 | 初始默认 / 修改规则 |
| --- | --- |
| plan_ttl_seconds | 900；从plan.created_at起计；过期刷新需新plan |
| source_concurrency | 1/来源；跨worker共享，同一来源资格更严格时取更低值 |
| request_timeout_seconds / max_retries | 30 / 2（共最多3次请求，均计量）；认证/黑名单/禁止访问不重试 |
| retry_backoff_seconds | 2、4；服务端Retry-After大于剩余墙钟时停止，不越过冻结期限 |
| max_fetch_requests / max_download_bytes | 10000 / 2147483648每数据Run；重试共享同Run已用量；预计超限预检拒绝，未知估计按运行时预留阻断 |
| download_reservation_chunk_bytes | 1048576；实际小于预留仍保留预留消费，界面显示差异 |
| max_hypotheses / max_formulas_per_hypothesis / max_numerical_evaluations | 3 / 3 / 3每workflow；数值重试消耗额度；统计候选数另记 |
| max_agent_attempts / max_agent_calls | 13 / 26每workflow；调用修复/重试计入，不给每子Run重新赠送额度 |
| max_format_repairs | 1每Agent Attempt；也计入calls，失败保持agent_output_invalid |
| max_panel_cells / max_ast_nodes / max_ast_depth | 5000000 / 256 / 32；编译/准备预检检查，超限要求显式新政策或缩小范围；不截断样本后偷偷评价 |
| quality_policy | 必需字段V>0、身份/单位/必需文件/历史池与日历可验证；硬错误0；缺测不强造通用合格比例，初版仅允许exploratory_limited用途。strict_pit与组合回测独立门禁 |

BudgetLimits完整字段为`max_hypotheses,max_formulas_per_hypothesis,max_numerical_evaluations,max_agent_attempts,max_agent_calls`，均正整数，用户修订不得超过部署批准上限；数值初值如表。新的data_resource_policy完整payload为表中plan/source/request/retry/download字段及max_panel_cells；execution_policy复制实际现存政策规范值及其版本、不包含secret。其他rule配置使用`{rule_id,rule_version,parameters:Parameter[],code_ref:Ref}`，仅接受已登记rule_id对应的参数名/类型；merge/cleaning/映射规则未登记不允许执行，不把通用封套当有实现。

| 提供方/能力 | 本次核对状态 | 首批接入准入条件 |
| --- | --- | --- |
| registered_import / 现有schema2免费数据 | 已有离线处理和真实因子路径；新流水线适配未实现 | 只读已冻结原料/manifest，保留remote_completion=unknown与探索限制 |
| 在线免费来源（含BaoStock） | 新端口未实现；历史禁止/黑名单不能当已恢复 | 逐源能力/单位/映射/完成性/限流证据；先验一个真实源，再按同端口补充；不可访问则blocked，不绕过 |
| RD-Agent方向/假设/公式评议及提案 | 四项均未验收；旧factor.loop不能代替 | 配置确定模型/prompt、结构输出和调用计量，按能力单独验收 |
| 受限公式引擎 / 新正交版本 | 目标未实现 | DSL禁未来/禁任意代码、oracle及统计版本验收 |
| 实际训练/预测/组合回测 | 完整真实链未验 | 冻结所选引擎model_spec/载荷schema、折内训练证据、成交组件与账户语义；无证据不展示ready |

不在设计阶段猜一个“现在肯定可访问”的供应商，也不调用外部服务验证。本次冻结共享物理/API/产物合同，供应商映射与引擎专属参数留在各适配器设计门；新增适配不得改变本合同的身份、预算和时间语义。

## 6. 技术引用类型、worker输入与输出

本节补齐前文Ref的落点；它们是同一artifact仓储里的类型，不建第二个注册数据库。技术类型有code_identity、environment、operator_registry、compiler_identity、algorithm_identity、reference_set、evaluation_protocol、execution_policy、data_resource_policy、budget_policy、rule、axis、preprocessing_state、trial_ledger、exclusions、lineage、availability、security_mapping、calendar、membership、equivalence_report、engine_binding、model_spec、search_policy、feature_contract、capability_record、execution_evidence、validation_plan。各场景的`*_rule_ref`指rule，`*_binding_ref`指engine_binding，`code_ref`指code_identity；不能因字段名不同复制类型。merge/cleaning/quality等policy_ref指已登记rule；execution_policy/resource/budget有独立类型。

| 技术类型 | payload字段与约束 |
| --- | --- |
| capability_record | `capability_id,provider_id,adapter_version,operation,components:string[],field_contract_refs:Ref[],version_lock:boolean,pagination:string,rate_policy_ref:Ref,verified_at:Time|null,evidence_refs:Ref[],limitations:string[]`；能力不是当前数据完整性证明 |
| execution_evidence | `executor_id,launch_token,process_identity:string,observed_at:Time,exit_code:integer|null,end_confirmed:boolean,evidence_digest:Digest`；无原始日志/密钥 |
| validation_plan | `sample_plan_ref:Ref,selection_policy_ref:Ref,fit_policy_ref:Ref,test_access_policy_ref:Ref,metric_protocol_ref:Ref`；每项规则版本须已登记，不允许空协议代替分折证据 |
| code_identity | `repository,commit,dirty:boolean,patch_digest:Digest|null`；dirty=true必须有patch摘要，无凭据URL |
| environment | `runtime,version,dependency_lock_digest:Digest|null,container_digest:string|null,observed_at:Time,limitations:string[]`；运行时实测，不拿当前环境补历史 |
| compiler_identity / algorithm_identity | `name,version,code_ref:Ref,parameters:Parameter[]` |
| operator_registry | `version,code_ref:Ref,operators:[{name,arity:integer,window_required:boolean,unit_rule,time_rule,missing_rule}]`；仅HR06允许的算子，不开放任意表达式扩展 |
| rule | `rule_id,rule_version,parameters:Parameter[],code_ref:Ref`；每个rule_id在适配器/统计专题给封闭参数schema，未知拒绝 |
| feature_contract | `features:[{definition_ref:Ref,unit,position:integer}],preprocessing_ref:Ref|null,label_ref:Ref|null`；position从0连续，顺序进入摘要 |
| preprocessing_state | `recipe_ref:Ref,fit_interval:Interval,fit_input_ref:Ref,state_parts:FilePart[],engine_binding_ref:Ref,fold_id`；只允许声明的训练区间 |
| trial_ledger | `experiment_id:Id,through_event_id:Id,events_parts:FilePart[],candidate_count:integer,test_access_count:integer,complete:boolean` |
| calendar / membership / security_mapping / availability / lineage / exclusions | `schema_ref:Ref,parts:FilePart[],coverage:Coverage,code_ref:Ref,limitations:string[]`；schema_ref指field_contract，字段键/时间分别遵循CDF1/输入准备规定 |
| equivalence_report | `source_ref:Ref,materialized_parts:FilePart[],logical_input_digest:Digest,checked_rows:integer,checked_cells:integer,checks:Check[],algorithm_ref:Ref`；只做抽样不得声明全量等价 |
| budget_policy | `limits:BudgetLimits,previous_policy_ref:Ref|null,decision_ref:Ref|null`；初版无修改时后两者null |

axis/reference_set/evaluation_protocol等已在§4完整定义；execution_policy引用实际配置规范字段（不改已有字段名），data_resource_policy依§5。model_spec/engine_binding/search_policy需要按选定引擎补充参数schema，不允许作为未知payload发布；这是G3/G4适配设计门，不阻塞G1共享存储/命令实现。公式与数据首批所用rule/field_contract同样须发布具体版本实例和独立oracle，不能仅有类型表就开启能力。G1-0补齐Parameter=`{name:string,value:string|integer|boolean|null,unit:string|null}`，仅接受该闭合形状；rule参数名/类型仍由各rule_id契约限定。未被专题冻结或未注册validator的artifact_type一律按`payload_schema_not_frozen`拒绝，不能用任意JSON绕过。

ExecutionContext完整字段：`run_id,attempt_id,launch_token,definition_ref:Ref,execution_policy_ref:Ref,workflow_id:Id|null,budget_scope_ids:string[],deadline_at:Time,cancellation_token_id:Id,output_namespace:Id`；只在worker边界解析namespace为受控目录，不对API返回路径。执行器将secret_ref解析为短期进程环境，Context、命令、产物不含密钥。方法契约统一为ARCHITECTURE §9端口+此Context；长任务不持数据库连接，预算预留经ExecutionService受控调用，不信任worker自报剩余额度。

Worker输出ArtifactBundle=`{run_id,attempt_id,launch_token,stage_id,artifacts:[{envelope:ArtifactEnvelope,object_digest:Digest}],stage_outcome:succeeded|failed|skipped,reason_code:string|null,execution_evidence_ref:Ref|null}`。发布端核验身份、stage、所有父引用、文件内容与schema，bundle内按依赖拓扑排序登记；全部验证通过才在一个事务发布该bundle。退出码0而缺必需输出记artifact_incomplete；正常业务否定可stage succeeded且review rejected。模型权重等不返回HTTP，仅FilePart；引擎内部对象不跨端口。
