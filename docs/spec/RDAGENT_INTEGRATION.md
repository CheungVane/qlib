# RD-Agent 因子研究接入规范

## 2026-09-26 共享 A 股配置复验

最新入口使用 `configs/cn/profile.json` 与独立规则/账户/日历/研究文件；固定文本替换已移除。模板存于 `git_ignore_folder/qwb_cn_factor_template_<配置指纹>`，容器数据存于独立 `~/.qlib/qlib_data/qwb_cn_current/<配置指纹>`。生成配置和质量报告写入运行产物，结果缓存因不包含场景参数已在探针关闭。

现行规则合成回放已复验：5个因子、8832行因子数据、123个回测日、19项指标；123个有效IC日、0个常数预测日、122个交易日。基线质量检查也通过（123个有效IC日、109个交易日）。这是日频合成行情验收，不是实盘或因子盈利保证。原始历史探针数据与结果保留，下面旧日期/数量记录用于追溯。

配置指纹：`b1d50a4a179583d447997dfab594c9eb2572cca3142fc286d62f66a4bc8612e6`。操作和限制见 [配置说明](../../configs/cn/README.md)。当前只编译已验证的 LightGBM baseline/combined-factor 模板，未支持的模型模板拒绝生成。

状态：2026-09-26 只读观察接入 + 执行层接入（`rdagent.factor.baseline` / `rdagent.factor.loop`，界面与CLI共用同一服务）；本地 Linux Docker、embedding、合成数据因子基线与完整单轮 Agent 循环已实测。RD-Agent 是用户维护的独立 fork，工作台不得把其源码复制进 Qlib，也不得直接导入 RD-Agent Python 对象到 API 进程。通过独立 checkout、外部配置、适配器和独立子进程接入，见 [执行层规范](EXECUTION.md)。

## 用户意图与边界

- 因子研究流程在统一工作台中可发现、观察、启动与取消；执行入口为合成情景集成探针，探针标签在研究结果与执行记录中保留。
- RD-Agent 的 `origin` 保持用户 fork；登记官方 `microsoft/RD-Agent` 为 `upstream`，上游更新先审查再集成。
- DeepSeek 聊天模型从 RD-Agent 本地 `.env` 注入，密钥不写入 tracked 文件、API 响应、浏览器代码、日志或研究结果。
- 因子研究需另行满足 embedding、运行环境和 Qlib 数据/费用情景一致性；只配置聊天密钥不等于因子流程可运行。

资源能力（**2026-09-27 部分实现，完整A41重新打开**）：AGENT04 要求的资源上限不再只是"检查资源下限"——整个 Attempt（LLM 驱动 + 因子代码）在 `qwb-rdagent-cpu:local` 容器内运行，内存=`--memory/--memory-swap` cgroup 硬上限、CPU=`--ulimit cpu=`，LLM 调用次数按政策在执行前通过文件账本原子预留；这不证明独立DB试验账本原子性。SR01—03的超时/失联恢复/试验预算反例仍待修，详见[监督审查](archive/review-20260927-supervision.md)。行为合同见 [EXECUTION](EXECUTION.md) EXEC13，验收与证据见 [IMPLEMENTATION](IMPLEMENTATION.md) A41，构建与核验命令见 [EXECUTION §5.1](EXECUTION.md)。

## 契约与阶段

| ID | 约束与验收 |
| --- | --- |
| AGENT01 | UI 经 `/v1/agents/rdagent` 只读查询接入状态；Qlib 工作台核心/API 不导入 RD-Agent 包；缺 checkout 时返回 `not_connected` |
| AGENT02 | 状态API仅返回模型/服务/fork和会话元信息；研究API可返回已脱敏中立结果与过程摘录，不返回原始凭据日志或可执行路径。密钥文件被 Git 忽略且权限仅限所有者 |
| AGENT03 | HTTP观察进程不反序列化pickle；可信本机产物仅由显式授权的离线CLI解析，并在发布前脱敏（RW03）；无会话显示空态，不伪造成功因子、IC 或收益 |
| AGENT04 | 执行接入前验证已实测的运行环境（官方 Linux 路径，或另行验证的 macOS/容器方案）、聊天与 embedding、数据快照、交易日历、费用情景、资源上限、Attempt 持久化和终态证据；缺任一条件时 UI 不提供假启动 |
| AGENT05 | 上游更新后验证 RD-Agent 的配置键、CLI/日志契约和适配器，再升级；不得自动合并、改写用户 fork 的工作分支或迁移其日志 |

## 历史实测与限制（以下含旧探针参数，当前入口以顶部共享配置为准）

- RD-Agent checkout `484776c` 与已获取的 `upstream/main` 相同；仅 Git remote 配置增加 `upstream`，tracked 源码没有改动。
- 本地 `.env` 使用 `CHAT_MODEL=deepseek/deepseek-flash` 和 DeepSeek 官方 URL。官方 `/models` 与最小聊天调用均返回 200；RD-Agent 独立环境中的 LiteLLM 调用也成功。DeepSeek [官方接口文档](https://api-docs.deepseek.com/zh-cn/)当前列出 `deepseek-flash`。
- 独立 Python 3.11 环境已安装，279 个依赖通过 `uv pip check`；`rdagent --help` 可启动。
- RD-Agent [官方 README](https://github.com/microsoft/RD-Agent/blob/main/README.md)声明当前仅支持 Linux，且多数场景需要 Docker。这是官方支持边界，并非本地聊天 API 的系统限制。代码中 Qlib 回测环境可选 Conda 或 Docker（默认 Conda），但默认因子数据生成路径直接使用 Docker。当前 Mac 的 Colima `rdagent` profile 已启动 Linux/arm64 Docker 引擎（4 CPU、6 GiB RAM、40 GiB 虚拟磁盘），Alpine 容器实测 `Linux/aarch64`。Ollama 本机 `bge-m3`（1.2 GB）已通过中文输入的 1024 维向量调用和 RD-Agent LiteLLM 调用。
- 上游 Qlib Dockerfile 使用 CUDA 基础镜像和固定的旧 Qlib 提交，不能直接用于本机 Apple Silicon CPU。平台自建两个 Linux/arm64 镜像，都不改上游 Dockerfile：(a) `scripts/build_rdagent_cpu_image.sh` → `qwb-qlib-cpu:local`（本仓库 Qlib + qrun/PyTables/LightGBM，供 Qlib 入口与因子代码执行）；(b) `QWB_RDAGENT_ROOT=../RD-Agent scripts/build_rdagent_runner_image.sh` → `qwb-rdagent-cpu:local`（只装上游 `requirements.txt`，**RD-Agent 检出运行时挂载、不打包**，上游代码变化无需重建，只有依赖变化才重建）。
- `scripts/prepare_rdagent_demo_data.py` 从 Qlib 合成 `cn_demo` 生成因子输入 HDF5；`scripts/prepare_rdagent_cn_template.py` 在 RD-Agent 忽略目录复制模板并适配 CSI500、百股交易单位与买入佣金万二、卖出佣金万二加演示税费。训练、验证、测试的 2020–2021 日期由 RD-Agent 本地 `.env` 配置。执行模板适配通过脚本注入，不修改上游受跟踪文件。
- RD-Agent runner 的基线因子 `CLOSE=$close` 已在上述容器内完成训练与回测，返回 19 项结果指标。随后完整单轮探针完成生成、编码、运行、反馈、记录五步，进程退出码 0；生成 5 个因子（REV_1、MOM_5、VOLUME_RATIO_5、VOL_10、RANGE_5），合并输入 9,520 行 × 5 列，回测记录为 2021-07-01 至 2021-12-31 的 132 个交易日，结果包含 19 项指标。IC、Rank IC、ICIR、Rank ICIR 四项为空；该合成数据探针只验收执行链路，不验收因子投资价值。
- 实测结果目录为 RD-Agent 忽略目录 `git_ignore_folder/RD-Agent_workspace/5f6e2ce2386a4aa2b3cceaba6c192b8f`，包含 `combined_factors_df.parquet`、`ret.parquet`、`qlib_res.csv`。`scripts/run_rdagent_factor_smoke.py` 保留了基线与单轮入口，并在循环后检查真实产物和指标；运行证据写入 RD-Agent 忽略目录，UI 只读显示摘要。工作台启动器、取消任务、统一 Attempt 持久化仍未接入，不能把命令行探针成功解释为 UI 可执行。
- macOS 下 RD-Agent 的因子编码环境默认假定 Conda，且基础因子验证硬编码历史证券与日期。探针显式设置 `FACTOR_COSTEER_PYTHON_BIN`，只对已由容器基线验证的 `$close` 表达式放行。第一次失败循环虽然进度为 100% 且退出码为 0，实际因 `python` 不存在而跳过回测，因此验收必须检查产物。
- **容器路线下的适配（仍不改上游）**：平台探针把 `QlibFBWorkspace.execute` 用到的 `QTDockerEnv` 换成同容器的 `LocalEnv`——本机 `.env` 设了 `MODEL_COSTEER_ENV_TYPE=docker`，不换就会去连嵌套 Docker（实测 125/`docker.from_env` 失败）；`FACTOR_COSTEER_PYTHON_BIN` 与 LocalEnv 的 `bin_path` 指向容器解释器；Ollama 基址由平台改写为宿主可达地址（`host.lima.internal`）。研究快照出口由 `QWB_PLATFORM_ROOT` 指定（容器内 repo 只读）。这些都在 `scripts/run_rdagent_factor_smoke.py` 内，属于平台侧适配层。

本机容器与 embedding 恢复命令为 `bash scripts/start_research_runtime.sh`。复现路径有两条，按需要选：

- **平台入口（推荐，受政策约束）**：构建镜像（见上）后执行 `qwb execute rdagent.factor.baseline --idempotency-key <key>` 或 `qwb execute rdagent.factor.loop --idempotency-key <key>`（需要 `QWB_RDAGENT_ROOT` 指向 checkout）。平台把 Attempt 放进容器并施加内存/CPU/调用预算，运行中可用 `docker inspect` 核对上限；完整单轮会调用付费模型。
- **宿主直跑（仅调试适配层）**：`scripts/prepare_rdagent_demo_data.py` → 从 RD-Agent checkout 用其 `.venv/bin/python` 执行 `../qlib/scripts/run_rdagent_factor_smoke.py --mode baseline|loop`。这条路径**不受**平台资源上限与调用预算约束，不能用作 A41 证据。

工作台启动命令、RD-Agent 安装与会话目录彼此分离；外部 agent 失败不能改写 Qlib 原生运行状态。

## U30能力适配目标（2026-09-29，仅设计）

新增ResearchAgentPort及direction_review/hypothesis_review/formula_review/formula_proposal能力声明，见[HUMAN_RESEARCH](HUMAN_RESEARCH.md) HR05与[ARCHITECTURE](ARCHITECTURE.md) §9。现有baseline/loop探针不能证明这些能力已支持；适配器须逐项验证结构化输入/输出、预算与真实产物。RD-Agent不支持某项时明确not_supported，可由用户选择另一个已配置研究Agent，不自动改供应商。纯文字任务按自身能力要求预检，不统一强制Qlib/embedding；一旦需要计算则必须校验对应运行时/数据。既有AGENT04对旧Qlib因子执行入口的前置条件不削弱；新增文字能力的专属前置以本段和HR05为准。
