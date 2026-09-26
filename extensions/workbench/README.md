# Quant Workbench（本地原型）

工作台是独立包；Qlib 仍在仓库根目录，工作台核心不导入 Qlib/MLflow。当前实现结果导入、SQLite + 不可变本地对象、CLI、HTTP API（读取 + 受控写入）、隔离进程执行器，以及总览/回测/训练/比较/研究中心页面。实时行情与正式数据目录仍显示未接入；系统页已采集当前API进程的窗口错误率与响应耗时。执行层合同见 [EXECUTION](../../docs/spec/EXECUTION.md)。

若同级目录存在用户的 `RD-Agent` checkout，启动脚本会自动将它登记为只读观察来源。界面「因子 Agent」显示 DeepSeek 聊天配置、embedding/执行前提、fork 的 upstream 状态与最近会话目录；也可运行 `QWB_RDAGENT_ROOT=/path/to/RD-Agent extensions/workbench/.venv/bin/qwb agent-status`。工作台只判断密钥是否已配置，不返回或展示密钥内容。执行边界见 [RD-Agent 接入规范](../../docs/spec/RDAGENT_INTEGRATION.md)。

本机 Linux Docker 与本地 embedding 环境可用 `bash scripts/start_research_runtime.sh` 恢复：Colima `rdagent` profile 提供 Linux/arm64 容器，Ollama 在 Mac 上提供 `bge-m3`。CPU Qlib 镜像、中国市场合成数据及万二费用模板已通过 RD-Agent 基线训练和回测，得到 19 项指标。复现入口为 `scripts/run_rdagent_factor_smoke.py --mode baseline`（从 RD-Agent checkout 用其 `.venv/bin/python` 运行），也可由工作台执行器启动（见下文执行层）。

完整单轮探针也已实测：5 个生成因子、123 个回测交易日、19 项结果指标；有效 IC 123 天、发生交易 122 天，配置中的质量检查通过（不代表有效 alpha）。旧的 132 天结果保留为历史记录。`--mode loop` 会调用 DeepSeek 并执行生成代码，本机版本通过进程内适配使用 Mac Python 编码和 Linux Docker 回测。详情和证据见 [接入规范](../../docs/spec/RDAGENT_INTEGRATION.md)。

从仓库根目录启动：

```bash
bash scripts/run_workbench.sh
```

首次启动会按 `uv.lock` 建立 `extensions/workbench/.venv`，导入通用 JSON 样本，并监听 `127.0.0.1:8765`。打开 `http://127.0.0.1:8765/`。工作台结果存于 `.data/workbench/`，不写入 Qlib 的 MLflow 库。

A 股参数集中在 [独立配置目录](../../configs/cn/README.md)，Qlib 与 RD-Agent 共用，运行时保存有效配置与指纹。

要先运行中国市场模拟 Qlib 工作流，执行 `bash scripts/run_cn_demo.sh`。从该命令输出查得 MLflow run ID，然后在仓库根目录导入：

```bash
extensions/workbench/.venv/bin/qwb import-qlib \
  --tracking-uri sqlite:///./.data/qlib_mlruns_mlflow3_12.db \
  --source-instance qlib-cn-current \
  --external-id <MLFLOW_RUN_ID> \
  --dataset-id cn-current-synthetic \
  --synthetic \
  --trust-local-artifacts \
  --config-path .data/cn_runs/<本次生成目录>/workflow.yaml
```

导入器会读取本机可信 Qlib 产物中的 pickle，因此需要显式提供 `--trust-local-artifacts`；不要用来导入不可信文件。历史运行缺少 Qlib 运行时版本、数据指纹等证据时，结果会保留 `unknown`。不会用当前安装版本推断历史版本。

从界面或 `qwb execute` 发起的 Qlib CN 回测成功后会自动走同一条导入链路：执行器给出导入候选，平台发布结果并把 `运行ID/revision/回执` 写回 Attempt 的 `outcome.result_import`（`imported`）或说明原因（`failed`/`manual_import_required`）。需要重试时：

```bash
extensions/workbench/.venv/bin/qwb import-attempt <ATTEMPT_ID>   # 只在该 Attempt 没有成功回执时才发布
extensions/workbench/.venv/bin/qwb attempt-stats --window-seconds 86400
```

RD-Agent 入口的结果是研究快照，仍按“可信离线导出后再入库”的路子处理，不会自动当成回测结果发布。

交付门禁（路由覆盖、核心DTO键集合与全部回归）：

```bash
bash scripts/workbench_gate.sh
```

脚本依次运行工作台 Python 与 JavaScript 套件，其中 `tests/test_contracts.py` 冻结 `/v1` 路由与核心只读 DTO 的键集合；改 DTO 必须同时改契约测试。这是本地/代理门禁，不是外部 CI 服务。

常用查询：

```bash
extensions/workbench/.venv/bin/qwb list-runs
extensions/workbench/.venv/bin/qwb show-run <PLATFORM_RUN_ID>
extensions/workbench/.venv/bin/qwb series <PLATFORM_RUN_ID> platform.equity --limit 100
extensions/workbench/.venv/bin/qwb compare platform.equity <RUN_ID_1> <RUN_ID_2>
```

独立环境验证：

```bash
uv sync --directory extensions/workbench --extra api --extra qlib-import --extra test --frozen
extensions/workbench/.venv/bin/python -m unittest discover -s extensions/workbench/tests -v
uv pip check --python extensions/workbench/.venv/bin/python
```

接口文档在服务启动后访问 `/docs`。工作台的目标与验收定义见 [spec](../../docs/spec/README.md)；当前完成度按 [实施状态](../../docs/spec/IMPLEMENTATION.md) 判断。这个本地原型还没有真实行情源、多用户权限或远程部署；执行Attempt已持久化，但Attempt级失败率统计与调度器仍未接入。

## 执行层：启动与取消研究

研究中心可查看每个执行入口的前置条件并启动/取消隔离进程。命令行等价操作：

```bash
# 执行入口与逐项前置条件（缺条件时 available=false，不会假启动）
extensions/workbench/.venv/bin/qwb execution-catalog

# 启动一次真实执行；幂等键由调用方生成，重复提交不会产生第二个进程
extensions/workbench/.venv/bin/qwb execute qlib.cn_synthetic_backtest \
  --params '{"note":"手动验证"}' --idempotency-key local-1

extensions/workbench/.venv/bin/qwb executions
...
extensions/workbench/.venv/bin/qwb execution <ATTEMPT_ID>
extensions/workbench/.venv/bin/qwb execution-log <ATTEMPT_ID> --tail 80
extensions/workbench/.venv/bin/qwb cancel <ATTEMPT_ID>   # 只有执行器确认进程结束后才落 cancelled
```

规则：每次 Attempt 独立进程、独立工作目录与独立 `mlflow.db`（Qlib）；退出码缺失时标记 `interrupted`，不推断成功；`queued/running` 与终态分开，取消请求与已取消分开；写接口校验来源，读取接口不启动执行。执行成功不自动进入结果库——`outcome.import_hint` 给出显式导入所需的 tracking URI 与 run ID，据此走上面的 `import-qlib`。RD-Agent 入口是合成情景的集成探针，界面与结果中保留该标记。

## 研究结果与过程

「研究中心」可搜索、分页并打开每个会话的结果、因子说明/代码、评审反馈与阶段日志；有报告的会话进入统一回测、训练、比较页面。总览展示最近研究；回测/训练展示判断依据及下一步；系统页展示当前进程的真实API观测。

「因子」页是因子层入口：按数据集内容版本分组展示已入库的因子面板，计算单因子统计（Rank IC、Newey-West t、p、BH-FDR、ICIR、分位差与单调性、秩换手），并给出重叠性（因子值相关矩阵、VIF 共线、冗余度、IC 序列相关）与增量贡献（正交残差 IC、等权组合加入/去掉某因子的 IC 变化）。收益标签由平台按 `close`（含复权因子）计算 `r=close_{t+h}/close_t-1`，只用同一数据内容版本的快照；持仓重叠与拥挤度当前显式标注"未接入"并说明缺少的数据。RD-Agent 研究会话导出时会自动发布该会话的因子面板；也可手工导入：

```bash
extensions/workbench/.venv/bin/qwb factors
extensions/workbench/.venv/bin/qwb import-factor-panel panel.json --source-instance manual \
  --external-id my-factor-v1 --dataset-id cn-current-synthetic \
  --dataset-version <内容摘要> --snapshot-label <快照目录名>
extensions/workbench/.venv/bin/qwb factor-analysis <FACTOR_ID> [<FACTOR_ID> ...] --horizons 1,5,10,20
```

比较视图按对象分组：训练、研究、回测各自指标集合不同，**跨组只并排、不做排名**；只有同组且同一把尺子（数据内容 + 执行口径 + 评估口径）时才显示最优/最劣。

同步既有 RD-Agent 本机可信产物（从 RD-Agent checkout，当前这些记录均是模拟数据）：

```bash
.venv/bin/python ../qlib/scripts/export_rdagent_research.py --trust-local-artifacts --synthetic
```

导出不调用模型、不执行生成代码。签名pickle仅在RD-Agent进程中读取，工作台API只读脱敏JSON快照；修改后的smoke入口会在退出时自动同步。其他入口产生的记录需运行上述命令，再点界面“刷新记录”。真实记录须用 `--session <会话目录名> --real` 逐项选定；不要混合数据性质后整批标注。

工作台 CLI：`qwb research-list`、`qwb research-detail <研究ID>`、`qwb review <运行ID>`。过程快照保存在 `.data/workbench/research`，平台结果仍使用不可变revision。新需求、限制与验收见 [研究工作台合同](../../docs/spec/RESEARCH_WORKBENCH.md)。


### 2026-09-26 审查修复

结果导出按Loop/runner事件分开，旧会话链接转为分轮导航；旧v1结果仍可追溯但禁止排名。Qlib只读导入始终在临时MLflow副本上进行。源证据与`--real/--synthetic`冲突会拒绝导入。序列按2000点分页，摘要使用完整revision；CLI `review --revision-id`可锁定版本，`compare --mode auto|equity|metric`使用共同口径检查。

新增回归：`node --test extensions/workbench/tests/test_ui.cjs`；Python仍用上述unittest发现命令（2026-09-26含16项执行层回归）。详见[修复与验收](../../docs/spec/FIXES_20260926.md)与[执行层规范](../../docs/spec/EXECUTION.md)；不代表完整实时/数据目录/多数据库已经支持。

验证与任务中心（U20/U21）：比较页在口径检查后会给出验证卡（每个运行的 Sharpe/PSR/DSR、配置间的 PBO、purged 折剔除比例与有效样本数）；命令行为 `qwb validate <RUN_ID>... [--horizon 1 --splits 5 --embargo 1 --blocks 8]`。PBO 只有在配置之间确有差异时才有意义，完全相同的配置（例如同情景重复运行）会标记为退化并说明不可区分。顶栏"待处理 N"来自 `/v1/attention`（失败执行、未入库结果、探针结果、取消请求中）；`Ctrl/⌘ + K` 打开命令面板，可跳转运行/研究/因子或执行命令，索引范围为命令 + 最近 100 个运行 + 最近 50 条研究 + 已入库因子。
