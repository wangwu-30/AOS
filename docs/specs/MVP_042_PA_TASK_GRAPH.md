# MVP_042_PA_TASK_GRAPH

## Goal

Provide a minimal, recoverable **TaskGraph** primitive for the Personal Assistant application layer。本阶段任务图必须（MUST）兼容 `runtime_graph_v1` 的最小执行元数据：

- persistent task graph state (queued/running/succeeded/failed)
- additive runtime graph metadata (`type`, plan revision, task bundle, execution policy)
- minimal dynamic decomposition support (append tasks)
- crash recovery helper (running -> queued)
- cycle detection (same fingerprint repeated triggers block)

## Boundary (Non-Negotiables)

- `top_level_api_stable`: MUST NOT expand `ExecuteRequest` top-level fields (extensions only via `policy_context`).
- `fail_closed`: invalid schema / IO failure / cycle detection MUST deny with stable `error_code` (no traceback leakage).
- `replay_mode_no_side_effects`: replay-mode MUST be zero-write.

Out of scope (v1):

- distributed concurrency / multi-writer consensus
- LLM planning / ReAct policies (TaskGraph is a mechanism, not intelligence)
- remote execution scheduling

## 2026-03-12 规范覆盖（Normative Override）

本节自 2026-03-12 起覆盖前文与本文件其余位置中所有把 `action` 或 `ActionGraph` 视为顶层 canonical durable 单位的描述。

### 顶层 durable 单位（MUST）

- 任务图（Task Graph）在 `runtime_graph_v1` 中的 canonical durable 单位必须（MUST）为：
  - `root task`
  - `worker_task`
- 顶层 `action task` 不再是 canonical durable 单位；新实现不得（MUST NOT）继续依赖顶层 `action task` 作为 planner/verifier 的主语义。
- worker 内部工具调用必须（MUST）仅以 `result_capsule`/evidence 形式落盘，且 `event_kind` 至少必须（MUST）支持：
  - `tool_call`
  - `worker_final`

### 恢复与默认值（MUST）

- `max_parallel_workers` 默认必须（MUST）为 `1`。
- `recover_incomplete` 必须（MUST）把 `root task` 与 `worker_task` 的 `running` 恢复为 `queued`。
- `worker_task` 的默认 durable 状态机必须（MUST）支持：
  - `queued -> running -> succeeded|failed|awaiting_leader`

### 边界条件（MUST）

- 工具执行线程池（Tool Executor Pool）内部 future 不属于 durable 恢复粒度；进程重启后不得（MUST NOT）尝试恢复单个 future。
- `worker_task` 崩溃恢复后可以（MAY）重新进入 ReAct 子循环，但有副作用工具不得（MUST NOT）自动重放。
- `replay_mode` 仍必须（MUST）零写入。

### 兼容策略（MUST）

- 历史 `action` payload 与旧 `ActionGraph` 记录可以（MAY）只读兼容；但任何新写入必须（MUST）以 `worker_task` 与 worker event capsule 为 canonical 语义。
- 本规范不提供 `ActionGraph -> WorkerTaskGraphV1` 的运行时兼容写路径；旧语义仅保留为历史快照读取能力。

### 错误码（MUST）

- `E_WORKER_TASK_GRAPH_INVALID`
- `E_WORKER_SPLIT_REQUIRES_LEADER`
- `E_TASK_DEPENDENCY_UNRESOLVED`
- `E_TASK_DEPENDENCY_CYCLE`
- `E_HITL_REQUIRED`

### 测试与验收（MUST）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`

## Storage Layout (File-Backed)

Relative to `data_dir`:

- `pa/task_graph/<workspace_id>/<graph_id>.json`

The file is written atomically (temp + replace) on updates.

## Schema (Stable JSON)

- `schema_version`: `"1.1.0"`（读取兼容 `1.0.0`）
- `type`: `"runtime_graph_v1"`
- `workspace_id`: `string`
- `graph_id`: `string`
- `created_at_utc`: `string` (UTC ISO)
- `updated_at_utc`: `string` (UTC ISO)
- `root_task_id`: `string`
- `cycle_threshold`: `int` (MUST be `>=2`)
- `next_task_num`: `int`
- `active_plan_revision`: `int`
- `max_parallel_workers`: `int`
- `replan_count`: `int`
- `tasks`: `array` of task nodes
- `message_turns|plan_revisions|context_snapshots|result_capsules|leader_decisions`: `array`

Default values (MUST):

- EV1 runtime `task_cycle_threshold` default: `3`
- `cycle_threshold` at graph creation: value passed by caller, MUST be `>=2`
- `type = "runtime_graph_v1"`
- `active_plan_revision = 0`
- `max_parallel_workers = 1`
- `replan_count = 0`

Task node fields:

- `task_id`: `string`
- `seq`: `int` (monotonic within a graph)
- `parent_task_id`: `string|null`
- `fingerprint`: `string` (deterministic identity)
- `state`: `"queued"|"running"|"waiting_context"|"awaiting_leader"|"succeeded"|"failed"|"interrupted"`
- `created_at_utc`: `string`
- `updated_at_utc`: `string`
- `attempts`: `int`
- `payload`: `object`
- `error_code`: `string|null`
- `plan_revision`: `int`
- `context_snapshot_ref`: `string|null`
- `completion_contract_ref`: `string|null`
- `task_bundle`: `object|null`
- `task_execution_policy`: `object|null`
- `file_refs`: `array`
- `dependency_result_refs`: `array`
- `read_only_ancestor_context_refs`: `array`
- `allowed_capabilities`: `array`
- `workspace_root`: `string|null`
- `context_escalation_mode`: `"auto"|"leader_gate"`
- `worker_task_admission_mode`: `"leader_gate"|"auto_within_scope"`
- `sufficient_for_execution`: `bool|null`
- `result_refs`: `array`
- `superseded_by_revision`: `int|null`
- `interruption_reason`: `string|null`

Task bundle / execution policy 规则（MUST）：

- `task_bundle.type` 必须（MUST）为 `task_bundle_v1`。
- `task_execution_policy.type` 必须（MUST）为 `task_execution_policy_v1`。
- `worker_task_admission_mode` 默认必须（MUST）为 `leader_gate`。
- `task_bundle.file_refs[].ref_type` 只能（MUST）为 `workspace_path|evidence_ref|artifact_ref`。

Task payload compatibility (MUST):

- 新写入的 `action`、`reasoning`、`aggregate_reasoning` payload 必须（MUST）使用 canonical `operator_ref/arguments`。
- 运行时读取历史 TaskGraph 快照时可以（MAY）兼容 `skill_ref/input` 只读别名，但不得继续新写入该命名。

## State Machine

- `queued` -> `running` -> `succeeded|failed|interrupted`
- `queued` -> `waiting_context|awaiting_leader`
- `recover_incomplete`: `running` -> `queued` (attempts++)

## Cycle Detection (Frozen)

When adding a task:

- if adding would cause `count(fingerprint) >= cycle_threshold`, MUST fail-closed:
  - `error_code = E_CYCLE_DETECTED`

## Expansion Idempotency (EV1 Integration)

When EV1 expands actions from LLM/tool outputs into TaskGraph:

- The runtime MUST treat expansion as idempotent by `fingerprint`.
- If an action fingerprint already exists in the graph, runtime MUST skip that action (no write, no error escalation).
- Runtime MUST append `aggregate_reasoning` only when at least one new action node was actually appended in the current expansion batch.
- Runtime SHOULD log expansion summary (`added/skipped`) for debugging.
- Runtime MUST NOT treat duplicate-only expansion as a fatal expansion failure.
- Runtime MUST treat `aggregate_reasoning` as terminal for expansion: executing this node MUST NOT trigger another action expansion wave.

Boundary conditions (MUST):

- malformed action item（缺少 `operator_ref`/`skill_ref`，或 `arguments`/`input` 不是 object）=> skip item, continue remaining actions.
- cycle detection raised while appending one action => skip that action and continue remaining actions.
- non-cycle storage/schema error while appending => fail-closed as IO/schema failure path.
- if parent node type is `aggregate_reasoning` => skip expansion immediately.
- `aggregate_reasoning` 执行时必须（MUST）可以读取同批 sibling action 的已落盘结果。
- 若 sibling action 失败，运行时必须（MUST）把失败证据中的稳定错误信息一并传给聚合步骤。
- 聚合步骤的最终用户回复必须（MUST）显式说明相关工具失败，不得（MUST NOT）静默吞掉失败；若失败表明用户提供的路径、工作区或输入不足，回复应该（SHOULD）请求最小更正信息。

## Replay Mode

- Any operation that would write to `pa/task_graph/...` MUST deny with:
  - `error_code = E_PA_TG_REPLAY_DENY`
- MUST NOT create directories/files in replay-mode.

## Integration (Minimal)

- THREAD-033 EV1 may create/update a root TaskGraph entry per `event_id`:
  - graph_id = event_id
  - root state: running -> succeeded|failed
- assistant loop runtime 必须（MUST）在非 replay 模式下通过运行时图耐久调度器（Runtime Graph Durable Scheduler）持久化 RuntimeGraph：
  - `graph_id` 默认应该（SHOULD）优先使用上游显式传入值；
  - 若无显式值，则必须（MUST）回退到当前 `turn_id`；
  - 若上游事件系统存在 `event_id`，则应该（SHOULD）令 `graph_id = event_id` 以便 trace viewer 与 PA records 对齐。
- assistant loop 写入的 root graph 至少必须（MUST）包含：
  - `message_turns`
  - `plan_revisions`
  - `context_snapshots`
  - `leader_decisions`
  - `result_capsules`
- assistant loop root task 终态必须（MUST）满足：
  - `done -> succeeded`
  - `need_context -> waiting_context`
  - `hold -> awaiting_leader`
  - `blocker -> failed`

Compatibility strategy (MUST):

- This spec is additive to existing TaskGraph schema and does not add top-level fields to `ExecuteRequest`.
- assistant loop 的 `RuntimeGraph` 写路径可以（MAY）从 loop 内部细节迁移到独立 durable scheduler；但落盘后的 JSON 形状、record id 与 root state 语义必须（MUST）保持兼容。
- 运行时读取 `schema_version="1.0.0"` 的旧快照时，必须（MUST）补齐默认 `type/plan revision/runtime metadata`。
- Existing `E_CYCLE_DETECTED` semantics in `add_task` remain unchanged.
- Idempotent expansion only changes EV1 runtime orchestration behavior (duplicate actions are skipped earlier).
- 历史 TaskGraph 若仍包含 `skill_ref/input`，运行时必须（MUST）可读；一旦有新写入，payload 必须（MUST）落为 `operator_ref/arguments`。

## Error Codes

- `E_PA_TG_SCHEMA_INVALID`
- `E_PA_TG_IO_FAILED`
- `E_PA_TG_REPLAY_DENY`
- `E_CYCLE_DETECTED`

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread042_pa_task_graph.py -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `tests/test_thread042_pa_task_graph.py::test_task_graph_persists_runtime_bundle_metadata` 必须（MUST）通过。
- `PYTHONPATH=src python3 -m unittest tests/test_thread049_builtin_fs_path_resolution.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true
