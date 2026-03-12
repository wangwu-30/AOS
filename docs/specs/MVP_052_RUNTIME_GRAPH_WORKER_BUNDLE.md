# MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_052
- 相关规范（Related Specs）：
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER.md`
  - `docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md`
  - `docs/specs/MVP_049_BUILTIN_FS_PATH_RESOLUTION.md`
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 目的（Purpose）

定义运行时图（Runtime Graph）、任务包（Task Bundle）、文件引用（File Reference）、任务执行策略（Task Execution Policy）与 leader/worker 边界的最小规范，使 runtime 在不重写主循环的前提下具备：

- task 级 timeout/retry
- worker 可执行但不可直接拆分
- leader 独占首层拆分、replan 与 HITL
- trace viewer 可审计 runtime 合同

## 2026-03-12 规范覆盖（Normative Override）

本节自 2026-03-12 起覆盖本文件中所有把 `executor + action task` 视为顶层 canonical worker execution seam 的描述。

### Runtime Graph Session（MUST）

- 运行时图会话（Runtime Graph Session）必须（MUST）作为 `assistant_runtime` 持有的 canonical durable facade。
- Runtime Graph Session 必须（MUST）组合：
  - 推理调度器会话（Reasoning Scheduler Session）
  - 工作者任务调度器会话（Worker Task Scheduler Session）

### WorkerTaskGraphV1 与 Worker Bundle（MUST）

- planner / verifier_replanner 必须（MUST）产出 `WorkerTaskGraphV1`。
- `worker_task` 必须（MUST）成为 Task Bundle 的唯一 durable 子任务形态。
- `worker_task.task_bundle` 至少必须（MUST）额外包含：
  - `allowed_operator_refs`
  - `scope_summary`
  - `tool_budget`
  - `time_budget_ms`
  - `parent_runtime_role = "worker"`

默认值（MUST）：

- `worker_task_admission_mode = "leader_gate"`
- `tool_budget.max_calls = 4`
- `tool_budget.max_parallel_calls = 1`
- `tool_budget.retry_read_only_tools = false`

### Worker ReAct Runtime（MUST）

- 工作者 ReAct 运行时（Worker ReAct Runtime）必须（MUST）按 `reason -> select tools -> parallel execute -> observe -> continue/finish/escalate` 执行。
- worker 只能（MUST）在 `allowed_operator_refs` 范围内选工具。
- worker 不得（MUST NOT）直接创建新的 `worker_task`；若试图继续拆分，必须（MUST）回 leader。
- 工具执行线程池（Tool Executor Pool）只允许（MUST）在单 worker 内并行；首版不得（MUST NOT）默认开启多 worker 并行。

### Runtime Graph 记录（MUST）

- `worker_task` 的 durable 状态迁移必须（MUST）为：
  - `queued -> running -> succeeded|failed|awaiting_leader`
- worker 内部工具调用必须（MUST）写入 `result_capsules`，且 `event_kind` 至少支持：
  - `tool_call`
  - `worker_iteration`
  - `worker_final`

### 边界条件（MUST）

- 顶层 `action task` 不再是 canonical durable node。
- worker 工具 future 不属于 durable 恢复粒度；崩溃恢复只发生在 `worker_task` 边界。
- 有副作用工具在恢复路径上不得（MUST NOT）自动重放。

### 兼容策略（MUST）

- 历史 `task_bundle`/`task_execution_policy` 结构继续可读；但新 graph 写路径必须（MUST）以 `worker_task` 和 worker event capsules 为 canonical。
- 不提供 `ActionGraphV1` 作为新写入的过渡兼容层。

### 错误码（MUST）

- `E_WORKER_TASK_GRAPH_INVALID`
- `E_WORKER_SPLIT_REQUIRES_LEADER`
- `E_HITL_REQUIRED`
- `E_TIMEOUT`
- `E_EXECUTION_FAILED`

### 测试与验收（MUST）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`

## RuntimeGraphV1（MUST）

运行时必须（MUST）提供 `runtime_graph_v1` 逻辑视图。最小字段：

- `schema_version`
- `type = "runtime_graph_v1"`
- `root_task_id`
- `active_plan_revision`
- `message_turn`
- `leader_phases`
- `worker_phases`
- `task_bundle_ref`

兼容策略（MUST）：

- 首版可以（MAY）由 `compiled_query + assistant_loop_result + task graph snapshot` 逻辑合成。
- `assistant_loop` 的 `RuntimeGraph` 写路径现在必须（MUST）经由运行时图耐久调度器（Runtime Graph Durable Scheduler）；trace viewer 仍可以（MAY）继续读取逻辑合成视图。

## TaskBundleV1（MUST）

最小字段：

- `schema_version`
- `type = "task_bundle_v1"`
- `objective`
- `completion_contract_ref`
- `task_execution_policy`
- `context_snapshot_ref`
- `file_refs`
- `dependency_result_refs`
- `read_only_ancestor_context_refs`
- `workspace_root`
- `allowed_capabilities`
- `context_escalation_mode`
- `worker_task_admission_mode`
- `bundle_generation`
- `sufficient_for_execution`
- `task_mode`
- `delegation_budget`
- `max_depth`
- `scope_guard`

默认值（MUST）：

- `context_escalation_mode = "auto"`
- `worker_task_admission_mode = "leader_gate"`
- `bundle_generation = "aggressive"`
- `task_mode = "atomic"`
- `delegation_budget = 0`
- `max_depth = 0`
- `sufficient_for_execution = false`，除非 runtime 已确认 bundle 足以执行

约束（MUST）：

- `objective` 不得（MUST NOT）为空。
- worker 不得（MUST NOT）直接根据 `TaskBundleV1` 创建子任务。
- 若 worker 需要继续拆分，只能（MUST）提交 `split_request`。
- `scope_guard.worker_split_requires_leader` 必须（MUST）为 `true`。

## FileRefV1（MUST）

最小字段：

- `schema_version`
- `type = "file_ref_v1"`
- `ref_type = "workspace_path"|"evidence_ref"|"artifact_ref"`
- `value`
- `usage = "required"|"optional"|"hint"`
- `summary`
- `resolver = "fs.read"|"fs.list"|"direct_ref"`

规则（MUST）：

- `workspace_path` 必须（MUST）遵守 `MVP_049_BUILTIN_FS_PATH_RESOLUTION.md`。
- 大文件不得（MUST NOT）默认内联进 bundle；必须（MUST）优先提供 ref + summary。
- planner/query compile 应该（SHOULD）优先把 required file refs 编入 bundle，减少 worker 回看父上下文。

## TaskExecutionPolicyV1（MUST）

最小字段：

- `schema_version`
- `type = "task_execution_policy_v1"`
- `root_deadline_ms`
- `llm_timeout_ms`
- `tool_timeout_ms`
- `llm_retry_policy`
- `tool_retry_policy`
- `max_attempts`
- `backoff_policy`
- `side_effect_safe_retry`
- `deadline_mode`

默认值（MUST）：

- `deadline_mode = "compat_root_cap"`
- `side_effect_safe_retry = false`
- `max_attempts >= 1`

规则（MUST）：

- LLM 调用与工具调用都必须（MUST）有 timeout。
- 自动重试必须（MUST）有界。
- 非幂等 action 默认不得（MUST NOT）自动重试。
- `deadline_ms` 必须（MUST）保留在 `ExecuteRequest` 顶层，但只能作为兼容上限与默认种子。

## Leader / Worker（MUST）

- leader phases 必须（MUST）为：
  - `intent_router`
  - `planner`
  - `verifier_replanner`
  - `communicator`
- worker seam 必须（MUST）为：
  - `executor`
  - 所有 builtin/tool action
- worker 可以（MAY）提交：
  - `task_result_capsule`
  - `context_escalation_request`
  - `split_request`
  - `replan_signal`
- worker 不得（MUST NOT）：
  - 直接新增子任务
  - 直接改写父任务 objective / acceptance
  - 直接发起新 plan revision
  - 直接对用户输出最终消息

## Budget Hold / HITL（MUST）

- 当 tool、step 或 replan 预算任一耗尽时，runtime 不得（MUST NOT）直接终止为普通 blocker。
- 预算耗尽必须（MUST）映射为：
  - `delivery_state = "hold"`
  - `error_code = "E_HITL_REQUIRED"` 或等价稳定语义
  - 保留当前 trace、steps、evidence、partial results
- communicator 在 hold 态不得（MUST NOT）强行生成最终用户消息。
- 若 worker phase 直接发出 planner 未批准的新 action，runtime 必须（MUST）拒绝，并返回 `E_WORKER_SPLIT_REQUIRES_LEADER`。

## 错误码（Error Codes）

- `E_HITL_REQUIRED`
- `E_BUDGET_EXHAUSTED`（仅可作为内部 reason，不应作为 hold 的最终 public state code）
- `E_WORKER_SPLIT_REQUIRES_LEADER`
- `E_TIMEOUT`
- `E_EXECUTION_FAILED`

## 边界条件（Boundary Conditions）

- 若 `task_bundle.sufficient_for_execution=true`，worker 应该（SHOULD）优先依赖 bundle，而不是祖先上下文。
- 若 bundle 不足，worker 可以（MAY）请求 context escalation；自动上升到根仍不足时，必须（MUST）进入 `E_HITL_REQUIRED`。
- 若任务为 `task_mode="atomic"`，worker 不得（MUST NOT）提交拆分后的 action plan 作为新子任务。
- 若任务为 `task_mode="decomposable"`，worker 仍不得（MUST NOT）直接拆分，只能提交 `split_request`。
- runtime 在非 replay 模式下必须（MUST）把 `message_turn / plan_revision / context_snapshot / result_capsule / leader_decision` 写入同一张 RuntimeGraph。

## 兼容策略（Compatibility）

- 首版为 additive change，不改变 `ExecuteRequest` 顶层结构。
- 现有 query compile 可以（MAY）继续产出 `task_envelope`、`delivery_contract`、`context_graph`、`prompt_profiles`；但 `task_bundle/task_execution_policy/file_refs` 必须（MUST）成为新的 canonical 执行合同。
- durable scheduler 抽离后，`RuntimeGraph` 的 record id、root state 映射与 `task_bundle/task_execution_policy/file_refs` 的落盘形状必须（MUST）保持兼容。
- 现有 trace viewer 可以（MAY）沿 detail 页增量展示 runtime inspector，而不要求一次性重写 transcript-first 首页。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖：

1. `task_bundle`、`task_execution_policy`、`file_refs` 出现在 compiled query 中。
2. `worker_task_admission_mode` 默认是 `leader_gate`。
3. `verify_assistant_execution` 在预算耗尽时返回 `delivery_state=hold` 与 `hitl_required=true`。
4. trace viewer 能展示 `Leader Rail`、`Task Bundle`、`File Refs`、`Execution Policy`、`Context Chain`、`Retry & Timeout`。
5. `task graph` 对新增 runtime bundle metadata 的读写兼容旧快照。

验收命令（MUST）：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread042_pa_task_graph -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread050_trace_view -v`
