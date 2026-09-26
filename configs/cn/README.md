# 中国 A 股场景配置

入口：[profile.json](profile.json)。JSON 是唯一参数来源，生成的 YAML 不手工修改。

| 文件 | 内容 |
| --- | --- |
| rules.current.json | 截至 2026-09-26 核查的现金 A 股规则：税费、板块涨跌幅、价格精度、数量约束及来源 |
| account.json | 用户指定双向万二；最低5元、含规费但不含过户费仍为账户假设 |
| research.json | 股票池/日期、TopK、模型、滑点、参与率、质量门槛、Agent预算、未支持能力 |
| calendar.fixture.json | 用于现有合成数据日期的交易所日历，覆盖2019-10-01至2022-01-10，含2020春节延期 |

## 修改与运行

从 Qlib 根目录执行 `bash scripts/run_cn_demo.sh`，会校验配置、生成独立数据目录、编译 YAML，再运行训练/回测。替代配置可设置 `QWB_CN_PROFILE=/绝对路径/profile.json`。相对配置引用按 profile 文件目录解析；data_path 相对项目根目录。

每次编译输出 `.data/cn_runs/<时间>-<配置指纹>/workflow.yaml` 和 `effective.json`。数据与RD-Agent模板使用配置指纹目录，原运行数据保留。修改数据/模型/规则配置会生成新快照，不覆盖旧配置结果。指纹证明配置内容，不代替完整代码/数据版本审计。

RD-Agent（在 Qlib 根目录依次执行）：

```bash
.venv/bin/python scripts/make_cn_current_data.py
.venv/bin/python scripts/prepare_rdagent_demo_data.py
.venv/bin/python scripts/prepare_rdagent_cn_template.py
bash scripts/build_rdagent_cpu_image.sh
cd ../RD-Agent
.venv/bin/python ../qlib/scripts/run_rdagent_factor_smoke.py --mode baseline
# 完整一轮（会调用已配置的付费聊天模型）
.venv/bin/python ../qlib/scripts/run_rdagent_factor_smoke.py --mode loop
```

探针自动设置独立Python路径、共享日期配置和编码预算。会关闭上游不包含场景参数的结果缓存，防止改费用后复用旧基线。暂只编译已验证的两个 LightGBM 模板，不生成未验证的 SOTA 模型模板。

## 当前生效的假设

- `current_rules_counterfactual`：用现行规则回放历史日期的合成行情，**不是历史制度复原**。
- 佣金万二；佣金最低5元；印花税卖出0.05%；过户费双向0.001%。最低费仅应用于佣金，分项按分四舍五入，零成交零费用。含规费/过户费开关避免重复计费；净佣金模式尚未实现，设置后明确报错。
- 5 bps 双向滑点作为单列执行摩擦成本；不伪装成实际订单簿成交价。5%日成交量参与率是保守研究假设，非交易所规则。
- 每次模拟订单视为一次成交，未实现同一委托多笔成交的券商合并计费。
- 日频前一交易日信号、当日收盘成交；涨跌停采用保守禁止双方向交易。限价状态字段由数据物化器提供；当前物化器仅支持正常状态模拟股票。
- 账户维护当日新买数量，禁止当日卖出新仓；旧仓可卖；现金不足会按含分项成本的金额缩量。
- 标签使用未来2个交易日，因此训练/验证/测试均移除末尾跨边界样本；有效日期写入生成配置。
- 费用逐笔写入 `fees.jsonl`（RD-Agent为 `cn_fee_ledger.jsonl`）；质量检查、有效配置作为MLflow产物保存。

## 明确限制

当前运行只接受 synthetic=true、正常状态、日频现金股票。科创/创业板数量规则已实现；北交所参数已收录但默认禁用（规则原文需进一步归档）。ST、IPO无涨跌幅期、退市整理、市价/盘后交易、真实PIT、公司行动现金/红利税、行业约束、分钟订单簿和券商执行仍未接入。它们不能靠填一个配置值假装实现；不支持的运行范围会拒绝或明确列为unsupported。

日历越界直接报错，不能回退成普通工作日。交易所规则修订时新增版本文件并修改profile引用；历史结果保留原指纹。更换标签公式/预测期限需一起更新时间边界实现及测试，校验器拒绝静默套用旧规则。

质量状态 `passed_checks` 仅表示覆盖率/预测差异/交易活动达到配置门槛，不表示产生有效alpha，更不表示已具备实盘条件。
