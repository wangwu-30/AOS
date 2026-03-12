# ADR-0016：Runtime Graph、Task Bundle 与 HITL Hold

- 状态（Status）：Accepted（关于“暂不迁移 durable scheduler”的约束已由 `ADR-0017` 部分替代）
- 日期（Date）：2026-03-12
- 相关规范（Related Specs）：
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md`
  - `docs/specs/MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE.md`
  - `docs/specs/MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER.md`
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 背景（Context）

现有 assistant loop 已经稳定拥有五阶段主链，但缺少三类可审计合同：

- task 级 timeout/retry
- worker 可执行但不可越权拆分的边界
- 预算耗尽后的非终止语义

同时，调试台需要在不重写整个 runtime 的前提下，展示 leader/worker、task bundle、file refs、execution policy 与 hold/HITL 状态。

## 决策（Decision）

采用以下不可逆设计点：

1. `query compile` 收敛为任务简报（Task Brief）与 `task_bundle_v1` 生成器，而不是细计划器。
2. `task_bundle_v1` + `task_execution_policy_v1` + `file_ref_v1` 成为新的 canonical 执行合同。
3. leader 独占：
   - intent binding
   - 首层拆分
   - replan
   - 父任务验收
   - communicator
   - HITL 升级
4. worker 只能执行、补上下文、提交结果、提交 `split_request`；不得直接创建子任务。
5. 预算耗尽不再直接终止；统一进入 `hold/HITL_REQUIRED`。
6. assistant loop 在不重写调度器的前提下，仍必须把 `message_turn / plan_revision / context_snapshot / result_capsule / leader_decision` 持久化到同一张 RuntimeGraph。
7. executor 若直接吐出 planner 未批准的新 action，必须拒绝并回到 leader 审批边界。
6. `runtime_graph_v1` 首版采用逻辑合成视图，而不是立即把 assistant loop 迁移到新的 durable scheduler。

## 备选方案（Alternatives Considered）

### 方案 A：让 worker 直接在作用域内自动拆分

未采纳。原因：

- trace 难以解释“这次拆分究竟是执行细化还是重新规划”
- 风险、能力边界与验收标准容易漂移
- 后续引入 HITL 时边界不清楚

### 方案 B：预算耗尽立即 blocker 终止

未采纳。原因：

- 会丢失人工接管窗口
- 与“保留部分结果、等待 leader/HITL”目标冲突
- 对复杂研究类任务过于激进

### 方案 C：先重写成全新的 durable RuntimeGraph 调度器

未采纳。原因：

- 变更面过大
- 现有 assistant loop 主链已经可复用
- 调试台与规范落地会被调度器重写阻塞

## 取舍（Trade-offs）

收益：

- 执行合同与 trace 语义显著更清晰
- 不破坏现有主链
- 为后续 durable scheduler / swarm queue 保留升级空间

代价：

- 首版 `runtime_graph_v1` 是逻辑合成视图，不是单一持久化真相源
- worker 的蜂群能力被刻意收紧，需要 leader 介入更多拆分判断
- `deadline_ms` 与 `task_execution_policy_v1` 在过渡期会并存

## 后果（Consequences）

- query compile 会继续保留历史字段，但 `task_bundle/task_execution_policy/file_refs` 成为新的 canonical 执行合同。
- trace viewer 需要新增 runtime inspector 面板。
- 测试需要显式覆盖 `hold/HITL_REQUIRED`。

## 风险与缓解（Risks and Mitigations）

- 风险：逻辑合成的 runtime graph 与未来 durable scheduler 语义漂移。
  - 缓解：冻结 `task_bundle_v1`、`task_execution_policy_v1`、`hold/HITL_REQUIRED` 这些先验合同。
- 风险：`deadline_ms` 与新 policy 共存导致混淆。
  - 缓解：在 spec 中明确 `deadline_ms` 仅为兼容 hard cap / default seed。
- 风险：worker 无法直接拆分导致吞吐下降。
  - 缓解：允许 worker 提交 `split_request`，由 leader 批量裁决。

## 可观测 / 验收（Observability / Acceptance）

必须可观测：

- leader rail
- task bundle
- file refs
- execution policy
- context chain
- hold/HITL state

验收命令：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread042_pa_task_graph -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread050_trace_view -v`
