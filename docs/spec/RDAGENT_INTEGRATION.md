# RD-Agent 因子研究接入规范

## 2026-09-26 共享 A 股配置复验

最新入口使用 `configs/cn/profile.json` 与独立规则/账户/日历/研究文件；固定文本替换已移除。模板存于 `git_ignore_folder/qwb_cn_factor_template_<配置指纹>`，容器数据存于独立 `~/.qlib/qlib_data/qwb_cn_current/<配置指纹>`。生成配置和质量报告写入运行产物，结果缓存因不包含场景参数已在探针关闭。

现行规则合成回放已复验：5个因子、8832行因子数据、123个回测日、19项指标；123个有效IC日、0个常数预测日、122个交易日。基线质量检查也通过（123个有效IC日、109个交易日）。这是日频合成行情验收，不是实盘或因子盈利保证。原始历史探针数据与结果保留，下面旧日期/数量记录用于追溯。

配置指纹：`b1d50a4a179583d447997dfab594c9eb2572cca3142fc286d62f66a4bc8612e6`。操作和限制见 [配置说明](../../configs/cn/README.md)。当前只编译已验证的 LightGBM baseline/combined-factor 模板，未支持的模型模板拒绝生成。

状态：2026-09-26 只读观察接入；本地 Linux Docker、embedding、合成数据因子基线与完整单轮 Agent 循环已实测。RD-Agent 是用户维护的独立 fork，工作台不得把其源码复制进 Qlib，也不得直接导入 RD-Agent Python 对象到 API 进程。通过独立 checkout、外部配置、适配器和后续执行进程接入。

## 用户意图与边界

- 因子研究流程在统一工作台中可发现、观察，已支持查看历史结果；未来接入界面启动。
- RD-Agent 的 `origin` 保持用户 fork；登记官方 `microsoft/RD-Agent` 为 `upstream`，上游更新先审查再集成。
- DeepSeek 聊天模型从 RD-Agent 本地 `.env` 注入，密钥不写入 tracked 文件、API 响应、浏览器代码、日志或研究结果。
- 因子研究需另行满足 embedding、运行环境和 Qlib 数据/费用情景一致性；只配置聊天密钥不等于因子流程可运行。

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
- 上游 Qlib Dockerfile 使用 CUDA 基础镜像和固定的旧 Qlib 提交，不能直接用于本机 Apple Silicon CPU。独立脚本 `scripts/build_rdagent_cpu_image.sh` 已构建 `qwb-qlib-cpu:local` Linux/arm64 镜像，并验证 Qlib、PyTables、LightGBM 导入及 RD-Agent `QTDockerEnv` 容器调用。未修改上游 Dockerfile。
- `scripts/prepare_rdagent_demo_data.py` 从 Qlib 合成 `cn_demo` 生成因子输入 HDF5；`scripts/prepare_rdagent_cn_template.py` 在 RD-Agent 忽略目录复制模板并适配 CSI500、百股交易单位与买入佣金万二、卖出佣金万二加演示税费。训练、验证、测试的 2020–2021 日期由 RD-Agent 本地 `.env` 配置。执行模板适配通过脚本注入，不修改上游受跟踪文件。
- RD-Agent runner 的基线因子 `CLOSE=$close` 已在上述容器内完成训练与回测，返回 19 项结果指标。随后完整单轮探针完成生成、编码、运行、反馈、记录五步，进程退出码 0；生成 5 个因子（REV_1、MOM_5、VOLUME_RATIO_5、VOL_10、RANGE_5），合并输入 9,520 行 × 5 列，回测记录为 2021-07-01 至 2021-12-31 的 132 个交易日，结果包含 19 项指标。IC、Rank IC、ICIR、Rank ICIR 四项为空；该合成数据探针只验收执行链路，不验收因子投资价值。
- 实测结果目录为 RD-Agent 忽略目录 `git_ignore_folder/RD-Agent_workspace/5f6e2ce2386a4aa2b3cceaba6c192b8f`，包含 `combined_factors_df.parquet`、`ret.parquet`、`qlib_res.csv`。`scripts/run_rdagent_factor_smoke.py` 保留了基线与单轮入口，并在循环后检查真实产物和指标；运行证据写入 RD-Agent 忽略目录，UI 只读显示摘要。工作台启动器、取消任务、统一 Attempt 持久化仍未接入，不能把命令行探针成功解释为 UI 可执行。
- macOS 下 RD-Agent 的因子编码环境默认假定 Conda，且基础因子验证硬编码历史证券与日期。探针显式设置 `FACTOR_COSTEER_PYTHON_BIN` 为 RD-Agent 虚拟环境 Python，并在本机执行因子编码；只对已由容器基线验证的 `$close` 表达式放行。第一次失败循环虽然进度为 100% 且退出码为 0，实际因 `python` 不存在而跳过回测，因此验收必须检查产物。生产执行器需要把上述适配改造成明确的可配置接口，避免依赖进程内 monkeypatch。

本机容器与 embedding 恢复命令为 `bash scripts/start_research_runtime.sh`。基线复现先运行 `scripts/prepare_rdagent_demo_data.py`、`scripts/prepare_rdagent_cn_template.py` 与 `scripts/build_rdagent_cpu_image.sh`，再从 RD-Agent checkout 用其 `.venv/bin/python` 执行 `../qlib/scripts/run_rdagent_factor_smoke.py --mode baseline`；完整单轮探针用 `--mode loop`，会调用付费模型。工作台启动命令、RD-Agent 安装与会话目录彼此分离；外部 agent 失败不能改写 Qlib 原生运行状态。
