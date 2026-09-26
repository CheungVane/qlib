# UI 参考研究与取舍（2026-09-25）

本文记录 GitHub 开源项目的可核对设计线索，并约束工作台 UI 的后续演进。参考的是信息组织和交互方式，不复制对方代码、样式或商标。运行事实与可比性规则仍以 [核心规范](WORKBENCH_SPEC.md) 为准。

| 参考 | 可核对的做法 | 对本项目的决定 |
| --- | --- | --- |
| [FreqUI](https://github.com/freqtrade/frequi) 与 [Freqtrade 回测文档](https://github.com/freqtrade/freqtrade/blob/develop/docs/backtesting.md) | 前端通过 API 连接回测服务；已有回测结果可在 Web 界面重新查看；回测包保留配置与策略材料 | 保持浏览器只读 API 边界；先让导入结果可查看，再设计执行入口；详情页突出来源和配置证据 |
| [MLflow Tracking UI](https://mlflow.org/docs/latest/ml/tracking) | 运行列表、搜索、单次运行指标、跨运行比较形成连续路径 | 左侧运行检索、回测/训练详情和比较页共享平台运行 ID；比较选择可由 URL 恢复 |
| [QuantStats](https://github.com/ranaroussi/quantstats) | 报告把核心指标与权益、回撤、滚动统计等图表组织成逐层阅读的 tear sheet | 回测详情优先显示权益、回撤和成本，再给原始证据；增加指标时必须明确计算定义，不能因视觉需要杜撰数值 |
| [W&B Workspaces](https://github.com/wandb/wandb-workspaces) | Workspace、Section、Panel 分层，面板配置和运行集合是独立概念 | 继续使用受校验的 dashboard manifest 与 query 注册表；未来保存布局时采用版本化配置，不把任意查询写进面板 JSON |

## 当前改动

- 增加运行名/引擎/外部 ID 搜索，帮助在多个引擎结果之间定位运行。
- 增加比较页，调用共享 `/v1/compare` 判断口径。数据版本未知时禁用排名提示；曲线按运行分开显示，不把不同时间窗口按点位硬叠加。
- 比较选择写入 URL，以便刷新后恢复；模拟数据与未知版本持续显式标记。

当前侧栏搜索只过滤首批加载的 30 个运行；全量服务端搜索属于后续 API 工作，不能把此过滤器称为全库检索。

## 后续 UI 顺序

1. 完成 M1 的导入回执和来源证据，再把详情中的来源区做成结构化字段。
2. 为结果序列增加服务端窗口查询和可说明的降采样，随后做图表悬停、缩放和数据表切换。
3. 完成 dashboard 配置保存、冲突检测、恢复默认和不可用 widget 的保留显示。
4. 当数据目录与实时遥测有真实数据后接入相应面板；无样本继续显示 `not_recorded`，不显示假 0%。

不引入 FreqUI 的 Vue/PrimeVue 实现或 GPL 代码；当前页面规模仍适合轻量原生前端。只有当可配置面板交互和复杂图表造成可测的维护问题时，才评估前端框架迁移。
