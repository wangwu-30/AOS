# MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT

- 状态（Status）：Draft
- 日期（Date）：2026-03-13
- 目标版本（Target）：MVP_055
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE.md`
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 目的（Purpose）

定义内核（Kernel）作为唯一执行底座的最小规范，冻结执行通道（Execution Lane）、停止策略（Stop Policy）、任务修订（Task Amendment）、提交（Submission）与持续执行语义，使控制器（Controller）只负责绑定、路由、规划、复核与交付，不再以批次式循环接管 worker。

## 范围（Scope）

本规范只覆盖：

- 任务服务（Task Service）的任务提交、恢复、暂停、supersede 与 generation guard
- 任务执行图（Task Execution Graph）的 canonical 字段、状态与 stale result 拦截
- 技能执行 API（Skill Execute API）在 `ExecuteRequest` / `TaskSpec` 上的任务级执行合同
- 执行通道（Execution Lane）与停止策略（Stop Policy）
- 任务修订（Task Amendment）与 side-effect boundary
- `assistant_loop` 的控制器路由与持续执行语义

本规范不覆盖：

- 多写调度一致性
- 分布式 worker 编排
- 新的 public transport 协议

## 核心概念（Concepts）

- 提交（Submission）：同一轮 controller 准入后的一组任务执行单元，必须（MUST）由 `submission_id` 稳定标识。
- 代次（Generation）：同一 task 在 supersede、hold/replan 后的有效 epoch；旧 generation 的 reason/tool/result 必须（MUST）视为 stale。
- 执行通道（Execution Lane）：控制任务级 reasoning profile、model pool、tool parallelism、verification mode 与 lane insufficiency 行为的固定枚举。
- 停止策略（Stop Policy）：控制 deadline、token budget、no-progress window 与 repeated fingerprint cap 的结构化预算对象。
- 副作用边界（Side-Effect Boundary）：task 首次 dispatch 非只读操作后的边界；越界后任务不得（MUST NOT）被静默 supersede。
- 任务修订（Task Amendment）：用户对 active submission 的纠正、补充或覆盖；应用层识别，内核负责 supersede 与 stale 拦截。

## 接口/数据结构（Interfaces/Data）

### TaskSpec / Skill Execute Request

`TaskSpec` 与进入技能执行 API（Skill Execute API）的任务级请求必须（MUST）携带以下字段：

- `submission_id`
- `execution_lane`
- `token_budget`
- `stop_policy`

默认值（MUST）：

- `execution_lane` 默认值为 `standard_task`
- `max_parallel_workers` 默认值为 `1`
- `correction_coalesce_window_ms` 默认值为 `5000`
- `token_budget.max_total_tokens` 与 `stop_policy.deadline_ms` 若未显式提供，必须（MUST）按 lane 默认值补齐

### Execution Lane 枚举

`execution_lane` 必须（MUST）限制为：

- `fast_chat`
- `standard_task`
- `deep_task`
- `research_task`
- `skill_exec`

每个 lane 的策略对象必须（MUST）至少包含：

- `reasoning_profile_ref`
- `model_pool_ref`
- `tool_parallelism_cap`
- `on_lane_insufficient`
- `verification_mode`

`on_lane_insufficient` 默认值必须（MUST）为 `controller_replan`。

### Stop Policy

`stop_policy` 必须（MUST）至少包含：

- `deadline_ms`
- `no_progress_window`
- `max_repeated_action_fingerprint_hits`
- `continue_until_terminal`

`token_budget` 必须（MUST）至少包含：

- `max_total_tokens`
- `reserve_tokens`

### Task Execution Graph

`task_execution_graph_v1` 的 node/attempt/event 必须（MUST）支持：

- `submission_id`
- `generation`
- `superseded_by_submission_id`
- `effect_class`
- `side_effect_boundary_reached`

`effect_class` 必须（MUST）限制为：

- `read_only`
- `workspace_write`
- `external_effect`
- `user_visible_delivery`

状态枚举必须（MUST）支持：

- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`
- `hold`
- `need_context`
- `interrupted`
- `superseded`

## 语义与状态机（Semantics/State Machine）

### Kernel Primitive

内核（Kernel）必须（MUST）冻结为以下五个 primitive：

- `Task Service`
- `Task Execution Graph`
- `Skill Execute API`
- `Worker ReAct Runtime`
- `Policy / Evidence / Replay`

新增执行能力不得（MUST NOT）绕过这五个 primitive 建立第二条 canonical 执行主链。

### Controller 职责

控制器（Controller）必须（MUST）只保留以下角色：

- Binder
- Routing Policy
- Planner
- Verifier / Replanner
- Communicator

Binder 必须（MUST）以非 LLM 方式完成 continuation、pending contract 与 correction binding。

Routing Policy 必须（MUST）只路由 `execution_lane`，不得（MUST NOT）逐步接管 worker 的 tool-by-tool 执行。

### Execution Lane 选择

控制器必须（MUST）按下列默认规则选择 lane：

- 显式技能执行（Skill Execute）或 skill-first 命中：`skill_exec`
- 明确外部证据或调研需求：`research_task`
- 工作区观察、多步拆解或复杂局部推理：`deep_task`
- 纯聊天、状态、确认：`fast_chat`
- 其他情况：`standard_task`

lane 决策必须（MUST）落到 evidence 与 trace，至少包含：

- `execution_lane`
- `execution_lane_policy`
- `controller_execution_mode=token_time_progress`

### 持续执行

controller 在初次准入后必须（MUST）默认进入 token/time/progress 驱动的持续执行模式：

- 只要仍有预算且存在进展，worker 必须（MUST）继续执行
- `loops_max`、固定 replan 次数或 batch 次数只可以（MAY）作为兼容提示，不得（MUST NOT）成为 canonical stop condition
- verifier 默认只应（SHOULD）在 `done / blocked / hold / no-progress / explicit amendment / lane insufficient` 时介入

worker 必须（MUST NOT）自行升档 lane；若当前 lane 不足，必须（MUST）返回 `E_REASONING_LANE_INSUFFICIENT` 并交还 controller replan。

### Hold 语义

`hold` 必须（MUST）被视为可恢复暂停态，而不是失败态。

以下错误码默认必须（MUST）映射为 `hold`：

- `E_HITL_REQUIRED`
- `E_DEADLINE_EXCEEDED`
- `E_TOKEN_BUDGET_EXHAUSTED`
- `E_NO_PROGRESS`

审批恢复（resume）时：

- 若原 `submission_id` 仍为当前 active submission，系统必须（MUST）继续该 submission
- 若原 submission 已被 supersede，系统必须（MUST）切换到最新 submission

### Task Amendment

应用层必须（MUST）把新输入判定为下列之一：

- `NEW_TASK`
- `FOLLOWUP_ACTIVE_SUBMISSION`
- `AMEND_ACTIVE_SUBMISSION`

`AMEND_ACTIVE_SUBMISSION` 的 v1 判定必须（MUST）满足：

- 同一 `conversation_id`
- 存在 `queued | running | hold` 的 active submission
- 新消息命中显式纠正词，或在 `correction_coalesce_window_ms` 内到达且明显指向上一任务

内核必须（MUST）提供 `supersede_submission(old_submission_id, new_submission_id, reason)` primitive。

### Supersede 与 Side-Effect Boundary

读型任务（`effect_class=read_only`）在未越过 side-effect boundary 前必须（MUST）允许自动 supersede。

以下任务一旦 dispatch 或越过 side-effect boundary，收到 amendment 时不得（MUST NOT）被静默覆盖：

- `workspace_write`
- `external_effect`
- `user_visible_delivery`

这类任务必须（MUST）转为：

- `hold`
- `blocked`
- `HITL`

之一，具体策略可以（MAY）由 controller 决定，但不得（MUST NOT）把旧结果静默写回新 submission。

### Generation Guard 与 Stale Result Rejection

每个 attempt/event 必须（MUST）携带 `generation`。

内核必须（MUST）在以下时刻执行 generation guard：

- reason step 前
- tool dispatch 前
- tool result 回灌前

当 generation 不匹配时：

- 当前 attempt 必须（MUST）终止为 `superseded`
- 结果必须（MUST）标记为 stale
- stale result 不得（MUST NOT）写回当前 active submission

## 错误与重试（Errors/Retry）

以下错误码必须（MUST）稳定保留：

- `E_HITL_REQUIRED`
- `E_REASONING_LANE_INSUFFICIENT`
- `E_DEADLINE_EXCEEDED`
- `E_TOKEN_BUDGET_EXHAUSTED`
- `E_NO_PROGRESS`
- `E_TASK_SUPERSEDED`
- `E_TASK_DEPENDENCY_UNRESOLVED`
- `E_TASK_DEPENDENCY_CYCLE`

兼容策略（MUST）：

- 旧调用方若仍依赖 `E_HITL_REQUIRED` 表示暂停，系统应（SHOULD）继续兼容
- 新调用方必须（MUST）把 `E_DEADLINE_EXCEEDED`、`E_TOKEN_BUDGET_EXHAUSTED` 与 `E_NO_PROGRESS` 视为 pause-class 错误

## 安全与隐私（Security/Privacy）

- worker 不得（MUST NOT）绕过 lane 策略使用未授权 model pool。
- worker 不得（MUST NOT）接触 MCP transport 或外部 skill transport 的 session 细节。
- side-effect boundary 必须（MUST）在首个非只读调用 dispatch 前后可审计。

## 可观测性（Observability）

系统必须（MUST）记录以下 evidence / trace：

- `controller_routing_decision_v1`
- `execution_lane_replan_v1`
- `worker_task_runtime_batch`
- `task_execution_graph_v1`
- `submission_superseded`

trace 必须（MUST）能够重建：

- lane 决策
- generation 切换
- supersede 结果
- hold / blocker / done 的最终原因

## 兼容与版本（Compatibility/Versioning）

- 本规范为 additive change；`ExecuteRequest` 顶层结构不得（MUST NOT）破坏兼容。
- 历史 `loops_max` 与旧的 phase-based batching 可以（MAY）继续存在于编译层，但不得（MUST NOT）作为默认 stop rule。
- `hold` 不得（MUST NOT）再被解释为失败分支。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖：

1. controller 路由 evidence 包含 `execution_lane_policy` 与 `controller_execution_mode=token_time_progress`
2. worker 在 deadline / token budget / no-progress 时进入 `hold`
3. `skill_exec` 且无显式只读声明时默认 `effect_class=external_effect`
4. amendment 导致的 supersede 不得污染新 submission

验收命令（MUST）：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_emits_query_gated_evidence_and_simple_plan -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread055_kernel_execution_lane_and_local_skill -v`
