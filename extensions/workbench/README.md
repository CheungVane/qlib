# Quant Workbench（本地原型）

工作台是独立包；Qlib 仍在仓库根目录，工作台核心不导入 Qlib/MLflow。当前实现结果导入、SQLite + 不可变本地对象、CLI、只读 API，以及总览/回测/训练/比较/因子 Agent 页面。实时行情与正式数据目录仍显示未接入；系统页已采集当前API进程的窗口错误率与响应耗时。

若同级目录存在用户的 `RD-Agent` checkout，启动脚本会自动将它登记为只读观察来源。界面「因子 Agent」显示 DeepSeek 聊天配置、embedding/执行前提、fork 的 upstream 状态与最近会话目录；也可运行 `QWB_RDAGENT_ROOT=/path/to/RD-Agent extensions/workbench/.venv/bin/qwb agent-status`。工作台只判断密钥是否已配置，不返回或展示密钥内容。执行边界见 [RD-Agent 接入规范](../../docs/spec/RDAGENT_INTEGRATION.md)。

本机 Linux Docker 与本地 embedding 环境可用 `bash scripts/start_research_runtime.sh` 恢复：Colima `rdagent` profile 提供 Linux/arm64 容器，Ollama 在 Mac 上提供 `bge-m3`。CPU Qlib 镜像、中国市场合成数据及万二费用模板已通过 RD-Agent 基线训练和回测，得到 19 项指标。复现入口为 `scripts/run_rdagent_factor_smoke.py --mode baseline`（从 RD-Agent checkout 用其 `.venv/bin/python` 运行）。工作台仍只读观察；因子研究启动器尚未接入。

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

接口文档在服务启动后访问 `/docs`。工作台的目标与验收定义见 [spec](../../docs/spec/README.md)；当前完成度按 [实施状态](../../docs/spec/IMPLEMENTATION.md) 判断。这个本地原型还没有真实行情源、多用户权限、远程部署或持久化任务遥测。

## 研究结果与过程

「研究中心」可搜索、分页并打开每个会话的结果、因子说明/代码、评审反馈与阶段日志；有报告的会话进入统一回测、训练、比较页面。总览展示最近研究；回测/训练展示判断依据及下一步；系统页展示当前进程的真实API观测。

同步既有 RD-Agent 本机可信产物（从 RD-Agent checkout，当前这些记录均是模拟数据）：

```bash
.venv/bin/python ../qlib/scripts/export_rdagent_research.py --trust-local-artifacts --synthetic
```

导出不调用模型、不执行生成代码。签名pickle仅在RD-Agent进程中读取，工作台API只读脱敏JSON快照；修改后的smoke入口会在退出时自动同步。其他入口产生的记录需运行上述命令，再点界面“刷新记录”。真实记录须用 `--session <会话目录名> --real` 逐项选定；不要混合数据性质后整批标注。

工作台 CLI：`qwb research-list`、`qwb research-detail <研究ID>`、`qwb review <运行ID>`。过程快照保存在 `.data/workbench/research`，平台结果仍使用不可变revision。新需求、限制与验收见 [研究工作台合同](../../docs/spec/RESEARCH_WORKBENCH.md)。
