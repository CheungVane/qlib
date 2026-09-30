# 工作台代码入口与职责

权威合同在[docs/spec/ARCHITECTURE](../../../docs/spec/ARCHITECTURE.md)，持久化/API/产物分别见该入口指向的三个CONTRACT。本文是代码导航，不另定义业务规则。

## 新增用例放在哪里

| 模块 | 所有者/调用方向 | 当前边界 |
| --- | --- | --- |
| domain/artifacts.py | 共享不可变引用与基础身份检查 | 不证明文件存在或来源真实 |
| domain/admission.py | 原始命令、冻结输入、准入回执与关联规则 | 不自行查数据库、不自动选择latest |
| domain/workflows.py | 7类固定计划及顺序/步骤职责 | 描述计划，不是DAG运行器 |
| domain/worker.py | worker上下文、截止时间、预算范围及受控输出身份 | 不携带SDK对象或本机绝对路径 |
| domain/data_pipeline.py / factor_expression.py | 来源计划子集与公式编译结果 | 不是来源客户端或DSL解释器 |
| services/data_pipeline.py | 数据入口→ResearchRunService | 不能自己创建Attempt/扣预算/启动下载 |
| services/research_workflows.py | 人参与入口→ResearchRunService | 后续人工交接、候选账本归此服务；无自动后台链实现 |
| services/research_runs.py | 唯一Run用例入口→ManagedExecutionPort | 存储写入交给原子准入，不能先插Run再插预算 |
| services/execution.py | 现有执行所有者，新admit_managed路径 | 新旧准入明确分开；没有新适配器时拒绝，不能回退submit |
| ports/research.py | read-only预检、幂等重放、原子准入 | 需要通过schema7/EXEC13验收的实现；无默认假仓储 |
| ports/data_acquisition.py / data_inputs.py | 来源→规范化→合并→质量→发布；共用准备/物化 | IO和数值规则分离；prepare绑定所有语义引用 |
| ports/research_agent.py / factor_compute.py | 评议/提案与确定性编译/计算/统计分开 | Agent不能自报可信IC |
| ports/modeling.py | fit / predict / portfolio / simulate各自独立 | 回测无fit，推理无重新拟合 |
| bootstrap.py | 显式注入事务/预检实现，组装现有ExecutionService | 默认不注入，不暴露新HTTP能力 |
| application.py | 将各领域入口暴露为同一服务对象图 | 兼容门面不扩展业务规则 |

## 一次准入的实际调用链

```text
DataPipelineService.start / ResearchWorkflowService.start
  → ResearchRunService.start(AdmissionCommand)
    → ExecutionService.admit_managed
      → ManagedAdmissionPort.replay          # 同键冲突拒绝；命中校验回执后返回
      → AdmissionPreflightPort.prepare_admission  # 只读校验与冻结输入解析
      → AdmissionRequest验证固定计划与引用
      → ManagedAdmissionPort.admit_run      # 再次查幂等、原子验证并提交
      → 关联回执核对 → 返回
```

最后一步提交的应是Run/Attempt/预算/自动边/launch意图及响应存根。worker返回ProducedArtifact暂存产物，只有统一ArtifactPublicationPort核验并发布后得到的Ref才能传给下一阶段。编译通过不等于产物已发布或策略有效。

网络和进程启动在事务之后，由未来独立监督核对launch_token并启动。GET不承担执行推进。端口实现负责事务内重复验证，不能把预检结果当永久授权。返回queued仅表示准入，不能当工作完成。

## 后续实现顺序

唯一执行队列见[IMPLEMENTATION](../../../docs/spec/IMPLEMENTATION.md)的“当前TODO：执行队列与任务完成门”。G1-0补剩余工程映射，G1-1—5分别交付契约/迁移、原子准入、独立监督、产物发布与联合验收；领域适配器和专业页面随后按G2—G4切片。本文只维护代码导航，不维护另一份任务状态。

测试入口：仓库根`bash scripts/workbench_gate.sh`。`tests/test_managed_framework.py`使用隔离替身检查拒绝、幂等顺序、身份保持和单事务边界；`tests/architecture_rules.py`阻止错误依赖和绕过Run所有者。它们不证明SQLite并发、独立监督、真实源/Agent或引擎可用。
