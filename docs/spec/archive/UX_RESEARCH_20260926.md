> 历史资料，归档于2026-09-30。以下状态、建议和“下一步”仅适用于原文日期/基线，不是当前执行指令。当前状态见[IMPLEMENTATION](../IMPLEMENTATION.md)，生效合同见[规范入口](../README.md)。原始发现和数字保留，归档不代表问题已关闭。

# 工作台交互参考与"顺手"改造清单（外部参考，2026-09-26）

状态：**研究输入，不是合同**。参考的是信息架构与交互方式，不复制对方代码、样式或商标，也不因此引入前端框架（沿用 2026-09-25 参考的取舍）。star 与推送时间为 2026-09-26 的 GitHub 检索快照。

## 1. 参考对象

| 项目 | star | 值得借鉴的点 |
| --- | --- | --- |
| [mlflow/mlflow](https://github.com/mlflow/mlflow) | 28142 | 运行表（可过滤/排序/自定义列）、单次运行页、跨运行比较、artifact 与血缘 |
| [wandb/wandb](https://github.com/wandb/wandb) | 11261 | runs 表 + 过滤器 + 保存视图、workspace/section/panel 分层、平行坐标与散点对比、sweep 参数扫描 |
| [grafana/grafana](https://github.com/grafana/grafana) | 76924 | dashboard 组合、时间范围选择、面板钻取、告警与状态色规范 |
| [apache/superset](https://github.com/apache/superset) | 74931 | 探索式图表 + 保存视图 + 行列级筛选 |
| [freqtrade/frequi](https://github.com/freqtrade/frequi) | 1083 | 交易/回测前端与后端 API 的边界，长时间运行的进度与日志查看 |
| [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | 7658 | tear sheet 式报告：一页内按层级给出指标与图 |
| [stefan-jansen/alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded) | 657 | 因子报告结构：IC 分析、换手分析、分组分析（本项目因子页已对齐该结构） |

## 2. 共性模式 → 本项目现状 → 建议

| 编号 | 模式 | 现状 | 建议 |
| --- | --- | --- | --- |
| X1 | **任务中心**：首页先回答"我需要处理什么"（失败、过期、待复核、探针结果） | **已接入**（U21）：顶栏"待处理 N"胶囊 + 总览待处理卡；数据新鲜度仍不在列 | 已落地；后续把"过期数据/未复核结果"补进来源 |
| X2 | **统一对象表 + 过滤/标签 + 保存视图**：运行、执行、研究、因子在一张可过滤表里 | **未实现**：左栏运行列表 + 多张卡片各自为政 | **P0（下一步）**：抽出公共列（类型/状态/来源/数据版本/关键指标/标记），支持标签与保存视图（URL 可恢复） |
| X3 | **全局搜索/命令面板（⌘K）**：跳运行、跳因子、执行动作 | **已接入**（U21）：命令 + 最近 100 个运行 + 最近 50 条研究 + 全部因子，披露索引范围 | 已落地；后续与 X2 共用同一索引 |
| X4 | **对比视图增强**：平行坐标、散点、按指标联动 | 有比较表 + 逐运行曲线（默认折叠） | **P1**：加散点/平行坐标，保留"红最优绿最劣仅在该行允许时"的既有规则 |
| X5 | **URL 状态可分享** | 运行/比较/研究/历史tab/因子组已进 URL | **P1**：补齐筛选、标签、密度等状态，做到"复制链接即复现场景" |
| X6 | **信息密度与键盘操作** | 表格固定样式；无密度切换 | **P1**：dense/comfortable 切换、粘性表头、j/k 与 Enter 导航 |
| X7 | **长任务反馈** | 执行记录 5 秒刷新 + 系统页观测 | **P1**：全局任务条（运行中 Attempt 汇总 + 最近完成），页面内 toast 而非系统通知 |
| X8 | **报告导出**：tear sheet / 因子报告一键导出 | 只能看页面，导出需手工 | **P1**：导出 HTML（含来源、口径、限制、数据版本），后续再评估 PDF |
| X9 | **空态与引导** | 每页有问号说明（U14） | **P2**：每页顶部固定一句"这一步要做什么 + 下一步动作" |
| X10 | **配色语义规范** | 比较表红优绿劣与状态色已分离并写进 UI06 | **P2**：把颜色语义收敛成一份 token 规范，避免后续新页面混用 |

## 3. 建议的"顺手"改造顺序

1. **X1 + X2 + X3**：任务中心、统一对象表、⌘K。这三件事共同解决"东西多、找不到、不知道下一步"的问题，也是当前报怨的主要来源。
2. **X7 + X5**：长任务反馈与状态可分享，让"跑起来了没有、刚才那屏怎么回去"不再是问题。
3. **X4 + X8**：对比增强与报告导出，服务于"比较与决策"。
4. **X6 + X9 + X10**：密度、引导与配色规范，属于打磨项。

以上仅为参考与建议顺序，不改变现有合同；用户确认后再进入 WORKBENCH_SPEC 的 UI 要求与验收。

## 4. 沿用 2026-09-25 的取舍（原 ui-reference 文档已合并到本文）

| 参考 | 可核对的做法 | 对本项目的决定 |
| --- | --- | --- |
| [FreqUI](https://github.com/freqtrade/frequi) 与 [Freqtrade 回测文档](https://github.com/freqtrade/freqtrade/blob/develop/docs/backtesting.md) | 前端通过 API 连接回测服务；已有结果可在 Web 界面重新查看；回测包保留配置与策略材料 | 保持浏览器只读 API 边界（写操作只走同源执行接口）；详情页突出来源与配置证据 |
| [MLflow Tracking UI](https://mlflow.org/docs/latest/ml/tracking) | 运行列表、搜索、单次运行指标、跨运行比较构成连续路径 | 运行检索、回测/训练详情与比较页共享平台运行 ID；比较选择可由 URL 恢复 |
| [QuantStats](https://github.com/ranaroussi/quantstats) | tear sheet 按层级组织核心指标与图表 | 回测详情先给权益/回撤/成本与风险指标，再给原始证据；新增指标必须写清定义（U22 已按此实现） |
| [W&B Workspaces](https://github.com/wandb/wandb-workspaces) | Workspace/Section/Panel 分层，面板配置与运行集合分离 | 继续使用受校验的 dashboard manifest 与 query 注册表；保存布局采用版本化配置，不把任意查询写进面板 |

不引入 FreqUI 的 Vue/PrimeVue 实现或 GPL 代码；当前页面规模仍适合轻量原生前端。只有当可配置面板交互和复杂图表造成可测的维护问题时，才评估前端框架迁移（见代码审查 C7）。
