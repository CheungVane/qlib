# 增量开发监督审查（2026-09-27）

审查基线：`668506ed`，覆盖`6d59bc97..668506ed`的48个提交。当前checkout先从origin快进同步；未修改另一worktree。角色为监督与质量审查，本批仅回写spec、保存隔离反例，不修业务代码、不改变历史结果。

**结论：架构方向适合个人工作台，但不能维持T02全线、T04/A41整体已通过的声明。** 新增模块与测试是真实进展；以下反例表明已有测试未覆盖关键跨模块行为。规范中的保护要求继续有效，实现需要补齐，不能把行为改写成更宽松的合同。T01指定纠正项、T03既有交付保留；本轮未全面重审上游Qlib或逐个认证所有历史产物。

## 可复现发现与修复出口

代码行号以668506ed为准；未写完整路径的模块均位于`extensions/workbench/quant_workbench/`，脚本路径相对仓库根。实现变化后以函数名定位。

### SR01 / P1：墙钟超时依赖读请求，关闭界面后任务可无限运行

- 位置：`extensions/workbench/quant_workbench/execution.py:341`，`enforce_timeouts/reconcile`；`adapters/executors.py:319`，`start`。
- 事实：监督只在reconcile/list/get路径触发；执行包装器没有持久deadline的独立监督。隔离sleep任务timeout=1秒，1.3秒后不调用service读取，进程仍运行，数据库仍running。CPU累计时间上限不能终止等待网络/休眠的墙钟超时。
- 违反：EXEC13、LIFE06、A41。持久化deadline不等于强制执行deadline。
- 出口：服务/独立监督器持续处理截止时间，CLI提交后退出和API无客户端时也生效；重启恢复、政策变更、完成/超时竞争都保留冻结事实。增加无轮询测试，以确认结束为终态依据。A41超时子项重新打开。

### SR02 / P1：失联释放并发槽，宿主进程消失被误作容器取消完成

- 位置：`storage_base.py:27`的ATTEMPT_OPEN_STATUSES、`storage_attempts.py:125`的list_open_attempts，以及create_attempt计数；`adapters/executors.py:425`的cancel早返回。
- 事实：槽位只统计queued/running。注入termination未知的interrupted记录后open计数为0；没有独立的“进程已确认结束”槽位状态。cancel遇宿主pid已不存在立即confirmed=true，未执行容器核对/清理。单元故障注入复现confirmed=true且cleanup调用0次；本轮未真实遗留容器。
- 影响：Docker客户端/包装器丢失而容器仍运行时，系统可能继续准入新任务或错误确认取消；迟到证据也不能通过只扫描open状态的路径自动恢复。
- 出口：槽位生命周期与展示状态分离，未知结束保留槽位；持久容器/进程身份核对并确认终止，不能凭宿主pid推断；覆盖失联、重启、迟到退出与容器清理失败。保持EXEC13/EXEC02原要求，A41恢复子项重新打开。

### SR03 / P1：Agent试验预算的“读后写”不是原子预留

- 位置：`storage_attempts.py:135`，reserve_agent_budget；对比create_attempt使用BEGIN IMMEDIATE。
- 事实：SELECT used与后续UPSERT之间没有写事务保护，SQLite连接上下文不在SELECT前自动开启写事务。以屏障安排两个连接先读同一旧值，limit=1时两个预留均allowed，账本最终used=1，实际批准2次。该反例只安排线程交错，未替换存储判定逻辑。
- 影响：并发CLI/API可越过试验总预算且低估用量。文件调用账本的flock不保护这个独立的DB试验账本。
- 出口：条件更新或写事务覆盖读判定与写入，增加多连接竞争测试；并核查准入失败、同幂等键竞争时是否应消耗试验预算，将语义与Attempt事实一致化。A41预算子项重新打开。

### SR04 / P1：验证v2未执行冻结的同质性检查

- 位置：`application.py:269`，strategy_validation；`validation_v2.py:198`起build_report。
- 事实：服务传入input_basis却未在报告层比较cost_basis；calendar身份也没有完成跨配置检查。成本前/成本后、不同calendar的20日夹具仍返回DSR与PBO available，excluded为空。单项登记收益检查不足以保证多个配置同质。
- 合同：VALIDATION §2A.3明确混用应为mixed_return_basis/mixed_calendar，对应统计不可用，PSR可独立返回。§2A.8的return_basis等定义字段亦缺失；短共同窗口/全排除返回200不可用与§2A.2要求400仍不一致。后两项为静态核对，未单独通过HTTP复现。
- 出口：在同一服务层校验并披露身份、收益口径及选择范围；按冻结DTO逐字段核对，包括排除项、默认embargo实际值、逐输入时间/版本及状态。增加异成本/异日历、未知身份、全排除与短窗口服务/API/CLI反例；不得靠前端比较页过滤兜底。T02重新打开同质性和合同验收，已有公式手算证据保留。

### SR05 / P1：快照清单摘要不能防止读取内容漂移

- 位置：`data_directory.py:108`的load_snapshot、FreeSnapshotReader.path/calendar/validate（约431—470行）、materialize_panel。
- 事实：load只校验清单自身摘要；reader与validate检查路径/日期合法性，但不校验组件内容。夹具登记2020年日历后原路径改写为2021年，snapshot_id/content_digest未变，validate仍ok=true且读出新日期。
- 影响：同一历史快照可产生不同标签/结果；切换data_root到另一内容相异目录也可能静默成功。当前“不可变/物化可复现”证据不足以满足DATA04/A17/ARC11。
- 出口：冻结实际组件或内容寻址对象，首次解析/物化核对已登记摘要及组件清单，缓存核验不能跨内容身份；不要求每次浏览扫描整棵数据树。覆盖文件替换、数据根切换、组件缺失及非published对象拒读。A17/A40相关子项保持未通过。

### SR06 / P1：研究试点另写NW实现，重新删除缺口后计算显著性

- 位置：`factor_pipeline.py:321`，newey_west_t；`scripts/run_factor_research.py:143`、`scripts/run_factor_walkforward.py:160`，调用前也压缩缺失IC。
- 事实：函数过滤非有限值后按相邻观测计算滞后；有一个缺失交易日的夹具仍给出t=9.14640442562508。这违反FACTOR_ANALYSIS §4.1要求缺IC时显著性不可用，且使交易日horizon与删缺口后的索引错位。
- 影响：试点FDR与依赖FDR的筛选不能沿用T01-F的认证。探索性标签不能豁免公式/日历合同。旧“7项通过FDR”等数字保留为当时输出，不能作为纠正后证据；本轮没有重跑真实研究。
- 出口：研究脚本复用有日期轴与可用性状态的统一统计服务，禁止调用方预先丢缺口；加入完整/缺口/尾部未成熟标签对照，重新生成受影响FDR/筛选/样本外证据。已有walk-forward缺purge/embargo和期末股票池条件的限制继续保留，未认证为T07。

### SR07 / P2：状态多处复制，导致互相冲突的执行指引

- README同时写T04剩余调用预算、验证待T02-B，而IMPLEMENTATION称T04/A41通过；IMPLEMENTATION顶部要求T05，后文仍写“下一步T02-U”；T05目录浏览已接service/API/CLI，却仍写“把data_directory接入应用层”。
- 本轮处置：当前状态统一到IMPLEMENTATION监督复审区；改为“目录浏览已接入，分析路径尚未使用目录”；T02/T04重新打开指定子项，下一步先修本报告P1。历史数字和CHANGELOG原条目不覆盖，追加纠正记录。
- 维护出口：每次关闭里程碑时搜索所有同ID状态和“下一步”，同步当前索引；历史证据显式标注提交和适用范围，避免再写“250+当前门禁”这种无法复核的完成依据。

## 架构与代码质量评价

模块化单体、独立工作台包、外部引擎适配器、版本化计算模块的方向合理。v2与v1分离、对不可用项保留原因、独立数值样例及真实来源限制都有价值。目录浏览适配器与生命周期草案不能自动代表数据访问和对象持久化已完成。

主要结构风险是跨层职责仍靠约定：execution.py直接导入storage_attempts的异常，核心执行层因此依赖SQLite适配实现；ResultRepository Protocol没有覆盖执行/因子/预算调用，数据目录以未声明协议的对象注入；application.py仍聚合结果/比较/分析/数据入口，factor_snapshot_dir仍读取当前CN配置。adapters/executors.py同时处理编译、容器路径、资源限制、进程恢复与预算。UI请求、状态和渲染仍集中于app.js。以上与D06/ARC10—12一致，不能靠拆文件数量宣布完成。

优先抽出共享统计服务、执行仓储/数据目录协议及核心异常，保证错误处理和并发事务由正确层负责；再按职责拆分服务与适配器。研究脚本负责参数/展示，数值与身份检查进入共享服务。SR06证明重复实现已经造成实质行为漂移，应先修这些边界，再扩展T06/T08能力。无需引入微服务或新前端框架。

## 验证与证据边界

- 在668506ed运行`bash scripts/workbench_gate.sh`：Python 292项，287通过、5跳过；JS25项全部通过，退出码0。跳过项目不能作为容器/外部环境通过证据；本轮不重做历史容器路线验收。
- 新反例：[脚本](evidence/20260927-supervision-probes.py)、[输出](evidence/20260927-supervision-results.json)。脚本仅使用临时目录、SQLite测试库和可清理的本地sleep进程；不训练、不访问数据供应商/聊天API、不修改用户数据库。
- 文档校验：本批修改的Markdown与审查报告共176个本地链接均可定位，`git diff --check`通过；反例重跑输出与保存JSON完全一致。
- 反例是对当前缺陷的复现，不是断言修复后的回归。修复者须转成正确行为断言并通过后关闭对应SR。
- 本轮未声称完整无缺陷，未重新核对外部统计文献、供应商规则、历史行情或原始产物。已知真实数据/PIT、试验账本、训练验证与交易缺口保留。
