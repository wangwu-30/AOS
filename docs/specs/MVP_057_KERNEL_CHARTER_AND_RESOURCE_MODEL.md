# MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL

- 状态（Status）：Draft
- 日期（Date）：2026-03-14
- 目标版本（Target）：MVP_057
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md`
  - `docs/specs/MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT.md`
  - `docs/specs/MVP_010_MEMORY.md`

## 目的（Purpose）

定义内核（Kernel）的稳定职责边界、统一资源模型、操作器合同（Operator Contract）与语义系统调用（Semantic Syscall）分层，防止业务语义、driver 细节与渠道细节泄漏到 canonical 执行面。

## 范围（Scope）

本规范覆盖：

- 内核宪章（Kernel Charter）与非目标范围
- 领导者（Leader）控制面角色与外部 loop 边界
- 资源预算（Resource Budget）与资源成本向量（Resource Cost Vector）
- 系统服务（System Service）、语义系统调用（Semantic Syscall）与 operator/driver 的分层
- 任务（Task）与推理动作（Reasoning Action）的边界与调度语义
- 任务级上下文快照（Task-Scoped Context Snapshot）与信息补齐语义
- `hold` 作为 kernel interrupt 的交付约束
- 应用层（Application Layer）与内核的职责边界
- 等价变换公理（Equivalence Transformation Axiom）的归属边界

本规范不覆盖：

- 具体 provider、模型、prompt 模板
- 具体 memory/web/channel 服务的业务 schema
- UI 呈现样式

## 核心概念（Concepts）

- 内核（Kernel）：唯一负责任务调度、资源管理、能力/策略、证据/恢复与终态交付合同的稳定执行底座。
- 领导者（Leader）：内核控制面角色，独占 task graph、共享资源、generation、暂停恢复与最终交付状态的裁决权。
- 任务（Task）：内核唯一默认允许的顶层 durable 调度单位，围绕单个可验收目标聚合预算、状态迁移与交付合同。
- 推理动作（Reasoning Action）：task 内部的局部控制流单元，可以表现为 thought/tool selection/tool call observation，但默认不是顶层内核调度单位。
- 任务级上下文快照（Task-Scoped Context Snapshot）：围绕单个 task 和 generation 裁剪、冻结并带 provenance 的最小充分上下文包，不等于系统全部已知上下文。
- 系统服务（System Service）：位于 Kernel 之上的稳定服务层，封装 memory、web、channel、scheduler 等领域能力。
- 语义系统调用（Semantic Syscall）：面向推理层暴露的稳定高层服务调用，屏蔽 driver payload 细节。
- 操作器合同（Operator Contract）：每个 operator 必须公开的 purity、idempotency、retry、preflight、resource cost 与 degraded 语义描述。
- 资源成本向量（Resource Cost Vector）：统一描述 `compute / time / context / io / side_effect / delivery` 六类成本的结构化向量。
- 应用层（Application Layer）：位于 Kernel 之上的产品语义层，负责 persona、领域对象模型、doctrine、默认假设与用户可见交互策略。

## 接口/数据结构（Interfaces/Data）

### Kernel Charter

内核必须（MUST）只承担以下职责：

- task / worker 调度
- 资源预算裁决与暂停/恢复判定
- capability / policy / HITL / side-effect boundary
- evidence / durable state / replay
- terminal state 与 delivery contract

内核不得（MUST NOT）直接承担以下职责：

- 业务语义映射
- 渠道 payload 拼装
- driver 兼容 alias 解释
- prompt doctrine 细节

### Scheduling Unit

内核的 canonical 顶层调度单位必须（MUST）是 `Task`。

`Reasoning Action` 默认只可以（MAY）作为以下对象存在：

- task 内部的 worker-local 控制流步骤
- trace/evidence 中的 event
- provider/driver 的内部执行细节

`Reasoning Action` 默认不得（MUST NOT）成为：

- 顶层 durable scheduler primitive
- 任务修订（Task Amendment）的直接目标
- 用户可见交付合同（Delivery Contract）的主绑定对象

### LeaderBoundaryV1

Leader 作为内核控制面角色，必须（MUST）独占以下权限：

- 修改 task graph
- 分配与回收共享资源 lease
- 决定 `generation / supersede / hold / resume`
- 批准 scope 扩张与 shared resource escalation
- 决定 final delivery state

外部 loop、worker、operator 不得（MUST NOT）拥有上述权限。

Leader 独占操作的执行入口必须（MUST）满足以下约束：

- 对外暴露的控制面入口必须（MUST）绑定受信任的 `caller_role = "leader"` 或等价控制面身份
- 非 Leader 身份若尝试触发 task graph 变更、shared resource 裁决或 final delivery 裁决，必须（MUST）返回 `E_KERNEL_CHARTER_VIOLATION`
- 首版实现可以（MAY）先通过 internal-only API boundary 与审计调用约定满足该约束；当 multi-agent delegation 或 external loop registration 暴露公共入口时，必须（MUST）升级为显式 caller-role assertion

### TaskSpecV1

进入 Kernel Task API 的 `TaskSpecV1` 至少必须（MUST）包含：

- `task_id`
- `submission_id`
- `generation`
- `objective`
- `acceptance_contract_ref`
- `effect_class`
- `execution_lane`
- `resource_budget`
- `policy_context`
- `context_refs`
- `attachments`
- `missing_inputs`
- `context_strategy`
- `max_escalation_count`
- `application_context_ref`

默认值（MUST）：

- `generation = 1`
- `attachments = []`
- `missing_inputs = []`
- `context_strategy = "auto_enrich_then_clarify"`
- `max_escalation_count = 2`
- `application_context_ref = null`

约束（MUST）：

- `application_context_ref` 只作为应用层 opaque ref 保存；Kernel 不得（MUST NOT）解释其内部业务语义
- `missing_inputs` 必须（MUST）只记录当前 task 仍缺失的关键信息，不得用作全量上下文镜像
- `context_strategy` 只能取：
  - `auto_enrich_then_clarify`
  - `clarify_before_execution`
  - `assumption_allowed`
- `max_escalation_count` 必须（MUST）大于等于 `1`

说明（SHOULD）：

- `leader_escalation` 是 runtime 在执行期间基于信息缺口、shared resource 或 scope 扩张判定出的结果，不是提交时可选的 `context_strategy` 取值

### TaskContextSnapshotV1

`TaskContextSnapshotV1` 至少必须（MUST）包含：

- `snapshot_id`
- `task_id`
- `submission_id`
- `generation`
- `frozen_at_generation`
- `task_contract`
- `selected_context`
- `execution_boundary`
- `open_gaps`
- `provenance`

默认值（MUST）：

- `selected_context.memory_hits = []`
- `selected_context.evidence_refs = []`
- `selected_context.file_refs = []`
- `selected_context.context_segments = []`
- `open_gaps.missing_inputs = []`
- `open_gaps.assumptions = []`

约束（MUST）：

- `TaskContextSnapshotV1` 不得（MUST NOT）默认等于系统全部已知上下文
- `TaskContextSnapshotV1` 必须（MUST）只包含当前 task 与 generation 允许看到的最小充分上下文
- `frozen_at_generation` 必须（MUST）等于当前 snapshot 被批准冻结时的 task generation
- snapshot 中每个 context segment 必须（MUST）能追溯 provenance
- `selected_context.context_segments` 中的每个 segment 至少必须（MUST）包含：
  - `source_ref`
  - `kind`
  - `content_hash`
  - `token_estimate`
- `open_gaps.missing_inputs` 的 canonical 形状中，每条记录至少必须（MUST）包含：
  - `input_key`
  - `resolution_strategy`
- 兼容模式下，legacy string-only `missing_inputs` 可以（MAY）被 compatibility bridge 接受，但 canonical 读写结果必须（MUST）归一化为对象列表
- `content_hash` 必须（MUST）基于归一化后的 segment 内容计算；首版算法固定为 `sha256(normalized_content)` 的前 16 个十六进制字符

### AssumptionEvidenceV1

当 runtime 选择 `assumption_continue` 时，必须（MUST）产出 `AssumptionEvidenceV1`，至少包含：

- `assumption_text`
- `confidence`
- `fallback_strategy`
- `snapshot_id`

默认值（MUST）：

- `confidence = 0.5`
- `fallback_strategy = "need_context"`

字段约束（MUST）：

- `confidence` 必须（MUST）位于 `[0.0, 1.0]`
- `fallback_strategy` 只能取：
  - `need_context`
  - `leader_escalation`
  - `abort`

说明（SHOULD）：

- `confidence` 应被视为 runtime-assigned estimate，而不是 calibrated probability；下游不得（MUST NOT）把该值解释为统计意义上的置信概率

### ResourceEscalationRequestV1

当 worker 在执行期发现未声明的共享写资源、scope 扩张或 task graph 重排需求时，必须（MUST）提交 `ResourceEscalationRequestV1`，至少包含：

- `request_id`
- `task_id`
- `submission_id`
- `generation`
- `discovered_resource_ref`
- `requested_effect_class`
- `reason`
- `evidence_refs`
- `side_effect_boundary_reached`
- `escalation_count`

默认值（MUST）：

- `evidence_refs = []`
- `side_effect_boundary_reached = false`
- `escalation_count = 1`

字段约束（MUST）：

- `requested_effect_class` 必须（MUST）是比当前 task 已批准 effect class 更宽或不同的 effect 需求
- `escalation_count` 必须（MUST）小于等于当前 task 的 `max_escalation_count`
- 当 `side_effect_boundary_reached = true` 时，Leader 在批准新的 shared resource task 前必须（MUST）先把当前 task 转为 `hold` 或等价受控状态
- 当 `escalation_count` 超过 `max_escalation_count` 时，runtime 不得（MUST NOT）继续无限 escalate；必须（MUST）转为 `hold` 或 `need_context`

EffectClass 偏序（MUST）：

- `read_only < workspace_write < external_effect < user_visible_delivery`
- `requested_effect_class` 中“更宽”的判定必须（MUST）以该偏序为准

### ResourceBudgetV1

执行面必须（MUST）支持统一资源预算对象 `ResourceBudgetV1`，至少包含：

- `compute_units`
- `time_budget_ms`
- `context_units`
- `io_calls_max`
- `side_effect_calls_max`
- `delivery_ops_max`

默认值（MUST）：

- `compute_units` 默认继承当前 `execution_lane` 的预算
- `time_budget_ms` 默认继承当前 `stop_policy.deadline_ms`
- `context_units = 8`
- `io_calls_max = 4`
- `side_effect_calls_max = 0`
- `delivery_ops_max = 1`

语义（MUST）：

- `context_units` 计数的是 distinct context segment injections，例如：
  - memory recall segment
  - evidence injection segment
  - file ref expansion segment
- `context_units` 不直接等价于 token 数；它与 `compute_units` 属于不同量纲

### Migration Mapping

过渡期内，runtime 必须（MUST）允许旧预算字段与 `ResourceBudgetV1` 并存，并在 admission 时完成归一化。

映射规则（SHOULD）：

- `stop_policy.deadline_ms -> resource_budget.time_budget_ms`
- `tool_budget.max_calls -> resource_budget.io_calls_max`
- `token_budget.max_total_tokens -> resource_budget.compute_units` 的近似 seed
- `side_effect_calls_max / delivery_ops_max / context_units` 若旧字段缺失，必须（MUST）回落到默认值

实现说明（SHOULD）：

- runtime 应提供单独的 legacy 映射函数，例如 `legacy_token_budget_to_compute_units(max_total_tokens)`，避免把近似换算逻辑分散到多个 admission 入口

过渡期 enforcement（MUST）：

- `side_effect_calls_max` 与 `delivery_ops_max` 必须（MUST）先作为硬约束
- `compute_units / context_units / io_calls_max` 首版可以（MAY）先作为 advisory / log-only 约束

### ResourceCostVectorV1

每个 operator 必须（MUST）声明 `ResourceCostVectorV1`，至少包含：

- `compute_cost`
- `time_cost`
- `context_cost`
- `io_cost`
- `side_effect_cost`
- `delivery_cost`

默认值（MUST）：

- 未显式声明的 cost 字段默认值为 `0`
- `purity = read_only` 的 operator 其 `side_effect_cost` 默认必须（MUST）为 `0`
- 用户可见交付类 operator 其 `delivery_cost` 默认必须（MUST）大于 `0`

### OperatorContractV1

每个可执行 operator 必须（MUST）声明：

- `operator_ref`
- `purity`
- `idempotency_class`
- `retry_class`
- `preflight_required`
- `degraded_behavior`
- `resource_cost_vector`
- `visibility`

字段约束（MUST）：

- `purity` 只能取：
  - `read_only`
  - `workspace_write`
  - `external_effect`
  - `user_visible_delivery`
- `idempotency_class` 只能取：
  - `idempotent`
  - `caller_scoped`
  - `non_idempotent`
- `retry_class` 只能取：
  - `safe`
  - `idempotent_retry`
  - `no_auto_retry`
- `visibility` 只能取：
  - `canonical`
  - `compat`
  - `internal`

默认值（MUST）：

- `preflight_required = true`
- `degraded_behavior = "surface_to_runtime"`
- `visibility = "canonical"`
- `retry_class = "safe"`

### SemanticSyscallV1

语义系统调用必须（MUST）声明：

- `syscall_ref`
- `service`
- `operation`
- `arguments_contract_ref`
- `maps_to_operator_refs`
- `completion_contract_ref`

默认值（MUST）：

- `maps_to_operator_refs = []`
- `completion_contract_ref = "delivery_contract:v1"`

### ExternalLoopAdapterContractV1

外部 loop 接入时必须（MUST）声明：

- `adapter_id`
- `scheduling_mode`
- `supports_replayable_evidence`
- `supports_side_effect_boundary`
- `supports_hold_resume`

字段约束（MUST）：

- `scheduling_mode` 首版只能取 `task_scoped`

默认值（MUST）：

- `supports_replayable_evidence = false`
- `supports_side_effect_boundary = false`
- `supports_hold_resume = false`

## 语义与状态机（Semantics/State Machine）

### Layering

canonical 执行面必须（MUST）按以下顺序分层：

1. `Kernel`
2. `System Service`
3. `Semantic Syscall`
4. `Operator / Driver`
5. `Submitter / Consumer Adapter`

reasoning surface 必须（MUST）优先暴露 semantic syscall；当且仅当满足以下条件时，才可以（MAY）暴露 raw operator：

- 当前能力仍无等价 semantic syscall
- 该 operator 被标记为 `visibility = compat`
- 运行时能提供完整 operator contract

### Task Over Action

内核必须（MUST）围绕 `Task` 而不是 `Reasoning Action` 做以下核心决策：

- 预算绑定
- side-effect boundary
- `hold / resume`
- supersede / amendment
- delivery contract

`Reasoning Action` 可以（MAY）被记录与回放，但其默认语义必须（MUST）从属于所属 `Task`。

当外部 loop 被接入时：

- 若其内部以 action/thought/tool 粒度运行，内核可以（MAY）把这些过程当作 task 内 evidence
- 但不得（MUST NOT）因此把 kernel scheduler 改写成 action scheduler

### Task-Scoped Context Snapshot

每次 task 执行前，runtime 必须（MUST）为当前 `submission_id + generation` 生成 `TaskContextSnapshotV1`。

该 snapshot 必须（MUST）只包含：

- 当前 task contract
- 与 task 直接相关的 memory hits / evidence / file refs / event state
- 当前 execution boundary
- 当前缺口与假设

该 snapshot 不得（MUST NOT）默认包含：

- 完整对话 transcript
- 全部 memory
- 全部 workspace 文件
- 系统全部历史 evidence

### Information Sufficiency

当 task 信息不足时，runtime 必须（MUST）区分以下路径：

1. `auto_enrich`
   - 缺口可以通过 memory、evidence、file refs、event metadata 自动补齐
2. `assumption_continue`
   - 缺口对 side-effect boundary 不敏感，且 assumption 已以 `AssumptionEvidenceV1` 写入 evidence
3. `need_context`
   - 缺口无法安全补齐，必须向用户追问最小信息
4. `leader_escalation`
   - 缺口意味着需要新的共享写资源、scope 扩张或 task graph 重排

worker-runtime 与 task-service 必须（MUST）把“信息不足”形式化映射到以下可观察结果之一：

- `need_context`
- `leader_escalation`
- `assumption_continue`
- `auto_enrich`

当 worker 在执行期间发现未声明的共享写资源时：

- worker 必须（MUST）提交 `ResourceEscalationRequestV1`
- worker 不得（MUST NOT）直接扩大写范围
- Leader 必须（MUST）决定：
  - 直接 replan
  - 转 `hold`
  - 或创建新的 shared resource task
- 若 `side_effect_boundary_reached = false`，Leader 应该（SHOULD）优先直接 replan
- 若 `side_effect_boundary_reached = true`，Leader 必须（MUST）先转 `hold` 再决定后续 shared resource 调度

### Semantic Syscall Preference

当某个目标存在 semantic syscall 与 raw operator 双重路径时：

- planner / executor 默认必须（MUST）优先选择 semantic syscall
- raw operator 不得（MUST NOT）作为默认推荐执行面
- semantic syscall 到 raw operator 的解析必须（MUST）留下 evidence

### Kernel Interrupt

`hold` 必须（MUST）被视为 kernel interrupt，而不是普通失败态。

当 execution 进入 `hold` 时：

- runtime 必须（MUST）保留当前 task/worker 状态、证据与预算快照
- runtime 必须（MUST）产出至少一条用户可见 delivery artifact，除非当前 submitter 明确声明 `replay_mode=true`
- Consumer Adapter 不得（MUST NOT）在 `hold` 场景下发送空 `reply_text` 或空 `deliveries`

### External Loop Integration

外部 shell loop、provider-native tool loop、第三方 agent loop 若要接入内核，必须（MUST）满足：

- 能以 `Task` 作为最外层执行单位
- 能服从 `ResourceBudgetV1`
- 能服从 side-effect boundary 与 `hold/HITL`
- 能产出 replayable evidence
- 能接受 Leader 独占 task graph / shared resource / final delivery 裁决

不满足上述条件的 loop 可以（MAY）作为参考实现，但不得（MUST NOT）成为 kernel canonical executor。

### Equivalence Transformation Boundary

等价变换公理必须（MUST）归属 doctrine 层，而不是 Kernel primitive。

等价变换只在满足以下条件时可以（MAY）发生：

- 原目标的 acceptance contract 未变化
- 变换理由已写入 evidence
- 变换后路径仍受同一资源预算与 side-effect boundary 约束
- 变换后不得（MUST NOT）引入新的 side-effect class

中高风险任务在完成等价变换后，verifier 必须（MUST）重新回审 acceptance contract。

## 错误与重试（Errors/Retry）

错误码（MUST）至少包含：

- `E_KERNEL_CHARTER_VIOLATION`
- `E_OPERATOR_CONTRACT_INVALID`
- `E_SEMANTIC_SYSCALL_UNRESOLVED`
- `E_RESOURCE_BUDGET_INVALID`
- `E_RESOURCE_CLASS_EXHAUSTED`
- `E_CONTEXT_SNAPSHOT_INSUFFICIENT`
- `E_SHARED_RESOURCE_ESCALATION_REQUIRED`
- `E_REASONING_ACTION_SCHEDULING_FORBIDDEN`
- `E_HOLD_DELIVERY_MISSING`
- `E_EQUIVALENCE_CONTRACT_BROKEN`

重试规则（MUST）：

- `preflight_required=true` 的 operator 在 preflight 失败时不得（MUST NOT）进入真实 side effect
- `non_idempotent` operator 在失败后不得（MUST NOT）自动重试，除非存在显式人工批准或 caller-scoped idempotency key
- `hold` 不得（MUST NOT）被自动映射为普通失败回复

## 边界条件（Boundary Conditions）

- 没有 semantic syscall 的 legacy operator 可以（MAY）继续存在，但必须（MUST）标记为 `compat` 或 `internal`。
- 同一 service 下若 semantic syscall 与 raw operator 同时暴露，文档必须（MUST）明确 semantic syscall 为推荐入口。
- `delivery_ops_max = 0` 的任务不得（MUST NOT）进入需要用户可见消息的终态；若进入，必须（MUST）返回 `E_RESOURCE_BUDGET_INVALID`。
- replay-mode 下可以（MAY）抑制外发 delivery，但不得（MUST NOT）丢失 `hold` 的内部 evidence。
- 对 action-native 外部 loop 的接入，若无法维持 `Task` 顶层边界，必须（MUST）拒绝并返回 `E_REASONING_ACTION_SCHEDULING_FORBIDDEN`。
- `E_REASONING_ACTION_SCHEDULING_FORBIDDEN` 首版可以（MAY）先作为保留错误码；最迟在 `ExternalLoopAdapter` 注册入口或等价 task admission 入口出现时必须（MUST）落地触发。
- `io_calls_max` 默认同时覆盖 workspace file read/write 与外部 I/O 类 operator；若未来需要细分，必须（MUST）在兼容前提下新增子类预算字段。

### Personal Assistant Reference Scenario

在个人助理（Personal Assistant, PA）多项目共享依赖场景中：

- 应用层可以（MAY）把“同时推进 A/B/C 三个项目”编译成工作计划（Program / Workstream）
- Kernel 不得（MUST NOT）把 Program 当作 primitive；Kernel 只接收 task graph
- `project_A/B/C` task 若共同依赖共享资源 `dependency:X`，Leader 必须（MUST）独占 `dependency:X` 的 shared resource 裁决权
- 若 `project_A` worker 执行中才发现必须修改 `dependency:X`：
  - worker 必须（MUST）提交 `ResourceEscalationRequestV1`
  - worker 不得（MUST NOT）直接修改 `dependency:X`
  - 若未越过 side-effect boundary，Leader 应该（SHOULD）重排 task graph
  - 若已越过 side-effect boundary，Leader 必须（MUST）先转为 `hold` 或等价受控状态

## 安全与隐私（Security/Privacy）

- operator contract 必须（MUST）声明是否越过 side-effect boundary。
- semantic syscall 不得（MUST NOT）绕过 operator preflight、policy gate 或 evidence 记录。
- `external_effect` 与 `user_visible_delivery` 类 operator 必须（MUST）保留稳定 idempotency 语义或显式声明为 `non_idempotent`。

## 应用层边界（Application Boundary）

应用层必须（MUST）负责：

- persona 与用户可见沟通风格
- 领域对象模型，例如 Program / Workstream / Reminder / Project
- doctrine 选择与默认假设策略
- `need_context` 场景下的提问文案与最小澄清策略

应用层不得（MUST NOT）负责：

- task graph durable 调度
- shared resource lease
- generation guard 与 supersede 执行
- replay / audit / evidence persistence

## 可观测性（Observability）

trace/evidence 必须（MUST）至少可观测：

- 当前 `ResourceBudgetV1`
- 当前 `TaskContextSnapshotV1`
- `Task -> Reasoning Action` 的映射链
- operator 的 `OperatorContractV1`
- semantic syscall 到 operator 的解析链
- `hold` 的预算原因与交付 artifact
- 等价变换前后的 objective 与 acceptance contract ref

## 兼容与版本（Compatibility/Versioning）

- 现有 `builtin://memory.write/search/delete/compact`、`builtin://web.search/browse` 等 raw operator 可以（MAY）继续存在，但必须（MUST）被视为 driver/compat surface。
- 已有 runtime 在过渡期可以（MAY）继续直接暴露 raw operator；但新的 canonical 文档与新能力设计必须（MUST）优先定义 semantic syscall。
- `OperatorContractV1` 与 `SemanticSyscallV1` 为 additive schema；旧 operator 若未显式声明完整 metadata，必须（MUST）通过 compatibility bridge 补齐默认值。
- `TaskSpecV1` 与 `TaskContextSnapshotV1` 为 additive contract；旧 task 请求可以（MAY）继续不显式提供 `missing_inputs / context_strategy / max_escalation_count / application_context_ref`，由 compatibility bridge 补默认值。
- `AssumptionEvidenceV1` 与 `ResourceEscalationRequestV1` 为新增 canonical 结构；旧 runtime 若尚未显式产出，必须（MUST）在对外文档中声明仍处于 compatibility-only 阶段。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：

1. 评审者能够根据文档明确区分 Kernel、System Service、Semantic Syscall、Operator/Driver、Adapter 五层职责。
2. 评审者能够明确解释为什么 `Task` 是顶层调度单位，而 `Reasoning Action` 只是 task 内部控制流。
3. `TaskContextSnapshotV1` 必须被定义为最小充分上下文，而不是系统全部已知上下文。
4. `hold` 场景必须具备用户可见 delivery contract，不允许空交付。
5. raw operator 与 semantic syscall 并存时，semantic syscall 必须被定义为 canonical reasoning surface。
6. 每个 operator 必须具备完整 operator contract 或可验证的 compatibility default。
7. 等价变换必须有 acceptance contract 不变与 evidence 可追溯要求。

建议验收命令：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_spike_memapi1_builtin_memory -v`
