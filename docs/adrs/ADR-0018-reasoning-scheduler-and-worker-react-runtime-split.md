# ADR-0018：推理调度器与 Worker ReAct 运行时拆分

- 状态（Status）：Accepted
- 日期（Date）：2026-03-12
- 相关规范（Related Specs）：
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE.md`
  - `docs/specs/MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER.md`

## 背景（Context）

ADR-0017 抽离了运行时图耐久调度器（Runtime Graph Durable Scheduler），但当时仍默认 planner/verifier 的顶层计划形态是 `ActionGraphV1`，并把工具执行视为可直接落成 durable `action task`。该模型带来三个持续问题：

- 顶层 durable 单位与真实执行单元不一致，导致 leader 计划与 worker 内部 ReAct 行为耦合。
- 工具调用恢复粒度过细，难以在 crash recovery 下给出安全重放边界。
- `assistant_runtime` 无法清晰区分“推理调度”与“worker 内部工具执行”两层执行面。

## 决策（Decision）

采用以下不可逆决策：

1. 顶层 durable 执行面正式拆为：
   - 推理调度器（Reasoning Scheduler）
   - 工作者任务调度器（Worker Task Scheduler）
2. planner / verifier_replanner 的 canonical 输出改为 工作者任务图（WorkerTaskGraphV1）。
3. 顶层 durable 单位改为：
   - `root task`
   - `worker_task`
4. 工具调用不再作为顶层 durable `action task` 调度；工具调用只允许在 单个 worker 的 工作者 ReAct 运行时（Worker ReAct Runtime）内部执行。
5. worker 内部工具调用必须（MUST）写入同一张 `runtime_graph_v1` 的 evidence 与 `result_capsules`，并至少区分：
   - `tool_call`
   - `worker_iteration`
   - `worker_final`
6. `assistant_runtime` 成为 Runtime Graph Session 的 canonical owner。

## 备选方案（Alternatives Considered）

### 方案 A：保留单调度器，继续把 tool task 当作顶层 durable task

未采纳。原因：

- 顶层 graph 语义会持续暴露 worker 内部实现细节。
- crash recovery 必须在 tool future 级别做不安全恢复。
- 无法清晰冻结 leader 与 worker 的职责边界。

### 方案 B：为工具调用单独再做第三套 durable scheduler

未采纳。原因：

- 复杂度过高。
- 会引入跨调度器依赖与多真相源风险。
- 首版需求只需要在 `worker_task` 边界 durable 恢复。

## 取舍（Trade-offs）

收益：

- leader 只负责 `intent_router / planner / verifier_replanner / communicator`，边界更清晰。
- `worker_task` 成为唯一 durable worker 执行单元，恢复语义简单且可审计。
- 工具执行线程池（Tool Executor Pool）只承担 worker 内局部并行，不污染顶层 graph 语义。

代价：

- `ActionGraphV1` 退出 canonical 路径，相关测试与规范需要同步重写。
- worker 内部工具 future 不能逐个 durable 恢复。
- communicator progress / final 交付需要明确回到 leader 闭环。

## 后果（Consequences）

- 新写入的 `runtime_graph_v1` 必须以 `worker_task` 为顶层子任务节点。
- `ActionGraphV1` 与顶层 `action task` 仅保留历史读取语义。
- query-gated runtime、TaskGraph、worker bundle 与 durable scheduler 规范都必须同步更新。
- 需要新增 `WorkerTaskGraphV1`、`Runtime Graph Session`、`Reasoning Scheduler`、`Worker Task Scheduler`、`Tool Executor Pool` 等术语。

## 风险与缓解（Risks and Mitigations）

- 风险：worker 内部失败不再自动映射为顶层 durable task 失败，可能掩盖执行细节。
  - 缓解：强制把 `tool_call` 与 `worker_final` 写入 `result_capsules`，并保留 evidence。
- 风险：旧测试仍按 `ActionGraphV1` 断言，导致大面积失败。
  - 缓解：明确不提供旧 canonical 写路径兼容；测试必须改写为 `WorkerTaskGraphV1`。
- 风险：有副作用工具在恢复后被误重放。
  - 缓解：恢复粒度固定在 `worker_task`，并规定有副作用工具不得自动重放。

## 可观测 / 验收（Observability / Acceptance）

必须可观测：

- `worker_task` 的 queued/running/succeeded/failed/awaiting_leader 迁移
- `tool_call` / `worker_iteration` / `worker_final` result capsules
- `plan_revision` 中的 `worker_tasks`
- root final state 与 `hold` 映射

验收命令：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_executes_emitted_actions_then_aggregate_reasoning -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`
