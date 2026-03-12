# MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_053
- 相关规范（Related Specs）：
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 目的（Purpose）

定义运行时图耐久调度器（Runtime Graph Durable Scheduler）的最小规范，使 `assistant_loop` 不再直接内嵌 `RuntimeGraph` 调度与持久化细节，而是通过单一 durable 调度边界完成 root bootstrap、task state 迁移、plan revision 推进与 `worker_task` 落图。

## 2026-03-12 规范覆盖（Normative Override）

本节自 2026-03-12 起覆盖本文件中所有将 `action task` 视为 durable scheduler canonical 子任务的描述。

### 调度拓扑（MUST）

- 运行时图耐久调度器必须（MUST）暴露为运行时图会话（Runtime Graph Session）。
- Runtime Graph Session 必须（MUST）组合：
  - 推理调度器会话（Reasoning Scheduler Session）
  - 工作者任务调度器会话（Worker Task Scheduler Session）
- `assistant_runtime` 必须（MUST）是 Runtime Graph Session 的 canonical owner。

### Reasoning Scheduler Session（MUST）

Reasoning Scheduler Session 至少必须（MUST）负责：

- root bootstrap
- compile failure 落盘
- leader phase `record_step`
- `plan_revision` 追加/推进
- root finalization

### Worker Task Scheduler Session（MUST）

Worker Task Scheduler Session 至少必须（MUST）负责：

- `ensure_worker_task`
- `set_task_state`
- `list_worker_tasks`
- worker event / worker final capsule 落盘
- graph reopen 时把 `running` 的 `worker_task` 恢复为 `queued`

默认值（MUST）：

- `active_plan_revision = 0`
- `max_parallel_workers = 1`
- `root final capsule id = capsule:root:final`
- `compile failure decision id = leader:compile`

### Canonical durable 记录（MUST）

- 新 graph 写路径必须（MUST）以 `worker_task` 作为唯一 canonical 子任务节点。
- 工具调用不得（MUST NOT）创建顶层 durable `action task`。
- worker 内部工具调用必须（MUST）落为 `result_capsules`，且 `event_kind` 至少支持：
  - `tool_call`
  - `worker_iteration`
  - `worker_final`

### 恢复与边界（MUST）

- bootstrap 期间必须（MUST）执行 `recover_incomplete`，把 `root task` 与 `worker_task` 的 `running` 恢复为 `queued`。
- scheduler 仍然必须（MUST）假定 single-writer；多写竞争不在保证范围内。
- `replay_mode` 下不得（MUST NOT）调用任何写接口。

### 兼容策略（MUST）

- 旧 `action task` 只允许（MAY）作为历史快照读取对象存在；新写路径不得（MUST NOT）继续写入。
- `runtime_graph_v1` 的顶层 JSON 形状、root state 映射与 stable record id 语义必须（MUST）保持兼容。

### 错误码（MUST）

- `E_WORKER_TASK_GRAPH_INVALID`
- `E_WORKER_SPLIT_REQUIRES_LEADER`
- `E_HITL_REQUIRED`
- `E_PA_TG_SCHEMA_INVALID`
- `E_PA_TG_IO_FAILED`

### 测试与验收（MUST）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`

## 范围（Scope）

本规范只覆盖：

- `runtime_graph_v1` 的单写（single-writer）durable 调度边界
- `assistant_loop` 对 `TaskGraph` 的写入编排
- 基于既有 `FileTaskGraphStore` 的持久化与恢复索引

本规范不覆盖：

- 外部时间调度器（time-based scheduler）
- 分布式多写一致性
- 新的 planner / verifier 语义

## 核心概念（Concepts）

- 运行时图耐久调度器（Runtime Graph Durable Scheduler）：负责把 `RuntimeGraph` 的状态迁移、记录追加与 action task 去重封装成单一 durable API 的调度组件。
- 引导快照（Bootstrap Snapshot）：在单轮 `assistant_loop` 启动时，对 root task、`message_turn`、`context_snapshot` 与初始 `plan_revision` 的一次性落盘。
- 动作任务索引（Action Task Index）：基于 `source_phase + action_id + operator_ref` 维护的 action task 稳定索引，用于避免重复创建 action node。

## 接口与数据结构（Interfaces/Data）

调度器引导输入至少必须（MUST）包含：

- `data_dir`
- `workspace_id`
- `graph_id`
- `logical_task_id`
- `query`
- `objective`
- `trace_id`
- `turn_id`
- `interaction_mode`
- `active_plan_revision`

调度器在 assistant loop 路径至少必须（MUST）提供以下能力：

- root bootstrap
- compile failure 落盘
- step execution 结果落盘
- action task 去重创建
- plan revision 追加
- replan revision 推进
- root finalization

调度器写入的记录形状必须（MUST）继续兼容既有 `runtime_graph_v1`：

- `message_turns`
- `plan_revisions`
- `context_snapshots`
- `result_capsules`
- `leader_decisions`

默认值（MUST）：

- `active_plan_revision = 0`
- `max_parallel_workers = 1`
- root bootstrap 完成后 `root_task.state = "running"`
- root final capsule id = `capsule:root:final`
- compile failure decision id = `leader:compile`

## 语义与状态机（Semantics/State Machine）

### Root Bootstrap

- 非 replay 模式下，assistant loop 必须（MUST）通过调度器执行 root bootstrap。
- bootstrap 必须（MUST）使用 `graph_id` 执行 `load_or_create`，不得（MUST NOT）绕过既有 `TaskGraph` 存储。
- bootstrap 后必须（MUST）至少写入：
  - root payload
  - `message_turn`
  - root runtime metadata
  - 若 `task_bundle` 存在，则写入 `context_snapshot` 与初始 `plan_revision`
  - root task `state="running"`

### Step Recording

- 每个可审计 step 完成后，调度器必须（MUST）同步更新对应 task state 与 `result_capsule`。
- 若 step 的 `runtime_role="leader"` 且存在 phase 名称，调度器必须（MUST）同步追加 `leader_decision`。
- 非 root task 的状态映射必须（MUST）为：
  - `accepted -> succeeded`
  - `error_code=E_HITL_REQUIRED -> awaiting_leader`
  - 其他失败 -> failed
- root task 在中间 step 失败时必须（MUST）保留：
  - `error_code=E_HITL_REQUIRED -> awaiting_leader`
  - 其他失败 -> failed

### Action Task Scheduling

- action task 创建必须（MUST）通过 durable 调度器执行，不得（MUST NOT）由 assistant loop 直接调用 `add_task(...)`。
- 调度器必须（MUST）基于 `source_phase + action_id + operator_ref` 做稳定去重。
- 调度器重建 existing graph 时必须（MUST）从已落盘 `tasks/result_capsules` 重建 action task index 与 action result index。
- action task 的 `parent_task_id` 必须（MUST）指向当前 root task。

### Plan Revision

- planner 首次产出的 action graph 必须（MUST）追加到当前 `active_plan_revision` 对应的 `plan_revisions` 记录。
- verifier/replanner 产生新 batch 且预算允许时，调度器必须（MUST）原子地：
  - `active_plan_revision += 1`
  - `replan_count += 1`
  - 追加新的 `plan_revision` 记录

### Root Finalization

- 调度器必须（MUST）在最终快照生成后追加 root final capsule。
- 调度器必须（MUST）将 `delivery_state` 映射为 root task 终态：
  - `done -> succeeded`
  - `need_context -> waiting_context`
  - `hold -> awaiting_leader`
  - `blocker -> failed`

## 错误与边界条件（Errors/Boundary Conditions）

调度器不得（MUST NOT）引入新的 public error code；必须（MUST）复用既有稳定错误码：

- `E_PA_TG_SCHEMA_INVALID`
- `E_PA_TG_IO_FAILED`
- `E_PA_TG_REPLAY_DENY`
- `E_CYCLE_DETECTED`
- `E_HITL_REQUIRED`

边界条件（MUST）：

- replay-mode 下不得（MUST NOT）调用调度器写接口。
- 调度器必须（MUST）假定单写执行；多写竞争不在本规范保证范围内。
- action task 去重命中时，调度器必须（MUST）返回已有 `task_id`，不得（MUST NOT）重复创建节点。
- 调度器若从旧 graph 恢复到 action result index，必须（MUST）优先使用已落盘 `result_capsule.id` 作为依赖引用。

## 可观测性（Observability）

运行时必须（MUST）保证以下对象在同一张 `RuntimeGraph` 中可审计：

- root bootstrap 记录
- planner / verifier 的 `plan_revision`
- leader phase 的 `leader_decision`
- action / root 的 `result_capsule`
- final root state

## 兼容与版本（Compatibility/Versioning）

- 本规范为 additive change；不得（MUST NOT）修改 `ExecuteRequest` 顶层结构。
- 调度器必须（MUST）保持既有 `runtime_graph_v1` JSON 形状与 record id 语义兼容。
- trace viewer 与其他消费者可以（MAY）继续读取逻辑合成视图；但 assistant loop 的写路径现在必须（MUST）经由 durable scheduler，而不是散落在 loop 内部。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：

1. root bootstrap 会写入 `message_turn/context_snapshot/plan_revision`。
2. action task 重复创建请求必须（MUST）返回同一 `task_id`。
3. step record 会同步更新 task state 与 `result_capsule`。
4. replan 会推进 `active_plan_revision` 与 `replan_count`。
5. compile failure 会写入 `leader:compile` 并令 root 失败。

验收命令（MUST）：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`
