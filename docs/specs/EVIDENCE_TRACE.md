# 证据与追踪（Evidence & Trace）

## 目的（Purpose）

定义 Evidence/Trace 的数据模型、引用（ref）语义、可回放（Replay）与兼容策略，为仲裁、回归测试与可观测性提供统一底座。

## 范围（Scope）

涵盖：
- evidence ref 模型
- trace correlation（trace_id/turn_id/span_id）
- commit_artifact 语义
- soft-cancel 语义

## 核心概念（Concepts）

见 `docs/glossary.md`：证据（Evidence）、追踪（Trace）、工件（Artifact）、提交工件（commit_artifact）。

## 接口/数据结构（Interfaces/Data）

### EvidenceRef

必须（MUST）包含：
- `ref`：内容寻址或随机 ref（实现可选，但必须唯一）
- `kind`：`tool_io|llm_io|policy|routing|snapshot|artifact_draft|error`
- `ts`：时间戳
- `size_bytes`
- `preview`：可选的短预览（需脱敏策略）

### TraceEvent

必须（MUST）包含：
- `trace_id`
- `turn_id`
- `span_id` 与 `parent_span_id`
- `event_type`：`TOOL_CALL_STARTED|TOOL_CALL_FINISHED|POLICY_DECIDED|ROUTED|RETRIEVAL_CHAIN|ARTIFACT_COMMITTED|...`
- `evidence_refs`：关联证据

### DIALOG_EVENT（多轮对话状态机事件，Dialog State Machine Events）

当系统需要表示“会话/对话（session/dialog）生命周期”的关键状态转移时，应（SHOULD）发出 `event_type=DIALOG_EVENT` 的 TraceEvent，并在 `data` 中至少包含：

- `dialog_event_type`：例如 `DIALOG_OPENED|USER_MESSAGE_RECEIVED|TURN_STARTED|TURN_FINISHED|...`
- `dialog_id`：MVP 推荐与 `trace_id` 相同
- `turn_index`：当事件与某个 turn 绑定时（1-based）

大对象（例如 user message 原文、turn 的最终结果快照）应（SHOULD）落在 Evidence，并通过 `evidence_refs` 引用，避免在 trace 行内携带不可控体量。

### RETRIEVAL_CHAIN（检索链回放）

当系统执行任何“检索/选择”（retrieval/selection）行为（例如 Memory 搜索、上下文装配、候选技能筛选）时，应（SHOULD）发出 `event_type=RETRIEVAL_CHAIN` 的 TraceEvent，并在 `evidence_refs` 中包含一个可回放的 evidence（例如 `kind=routing` 或 `kind=policy`），至少记录：
- 输入摘要（query/filters）
- 候选集合规模（scanned_count）
- 选择结果（selected refs/ids）与得分/原因（如适用）
- 关键约束（例如 TTL/tombstone 过滤、redaction、replay-mode 限制）

## 语义与状态机（Semantics/State Machine）

- `commit_artifact` 必须（MUST）只能由控制面触发（single-leader + commit）。
- soft-cancel 后：
  - 已完成的 tool_call 结果仍入 Evidence
  - 但不得继续自动续跑、不得自动 commit、不得投递 tool_feedback

## 错误与重试（Errors/Retry）

错误必须（MUST）记录为 `kind=error` 的 evidence，并关联到失败 span。

## 安全与隐私（Security/Privacy）

- 默认真相源本地；云端同步走端侧加密（见 ADR-0003）。
- preview 与索引元数据必须有脱敏规则（待补齐）。

## 可观测性（Observability）

必须（MUST）支持导出：
- turn view
- plan lifecycle view
- artifact lineage view

当系统存在多轮会话（multi-turn session）时，可观测性应该（SHOULD）额外支持 session view：
- 按 `workspace_id + conversation_id` 或稳定 session key 聚合
- 展示最近 turn 列表与进入单 turn 详情的导航
- 明确标示最新执行状态与最新错误码（若存在）

### Turn View 最小导出集（Minimum Turn View Export）

`turn view` 必须（MUST）可重建单次执行的最小追溯视图，至少包含：
- trace events 时间线（按 trace 行序）
- 本轮实际发送给模型的 prompt evidence（若存在）
- tool 输入/输出 evidence
- LLM 输出 evidence
- policy / routing / context_routing evidence
- error evidence 与失败详情

当系统存在应用层封装（例如个人助理 / Personal Assistant）时，turn view 应该（SHOULD）额外关联：
- `pa/events/<workspace>/<event_id>.json`
- `pa/outbox/<workspace>/<event_id>.json`
- `pa/task_graph/<workspace>/<event_id>.json`
- 与该 event/task 关联的 idempotency execute result

若存在任务图（task graph）或多次 prompt / context / output 演化，turn view 应该（SHOULD）提供：
- 任务图的图形化视图（例如 DAG / node-link）
- 相邻 prompt 的差分视图
- 相邻 context / output evidence 的差分视图

若提供交互式 viewer，viewer 应该（SHOULD）额外提供：
- 任务图节点到 evidence / diff / task execution 的联动聚焦
- 按 task / step 过滤 prompt、context、output、error 与 task execution
- trace timeline 到 task graph 的反向定位
- 对同一会话（session）的 turn 导航
- `Leader Rail`：展示 `intent_router|planner|verifier_replanner|communicator` 的状态、错误码与 deadline
- `Task Bundle`：展示 objective、file refs、execution policy、worker admission mode、bundle sufficiency
- `Context Chain`：展示 context snapshot ref、ancestor context refs、context escalation mode
- `Retry & Timeout`：展示 task 级 timeout/retry 实际轨迹

当 viewer 检测到 `delivery_state=hold` 或 `E_HITL_REQUIRED` 时，必须（MUST）显示 hold/HITL 状态；不得（MUST NOT）把该 turn 渲染为普通 blocker 终局。

turn view 禁止（MUST NOT）静默省略与最终结果相关的失败步骤。若某个失败 evidence 已被 trace / outbox / idempotency / manifest 任一路径引用，导出结果必须（MUST）显式呈现该失败。

## 兼容与版本（Compatibility/Versioning）

- evidence/trace schema 必须（MUST）有 `schema_version` 字段，并在 `VERSIONING_COMPAT.md` 规定迁移策略。

## 测试与验收（Tests/Acceptance）

- Golden traces：GT1–GT5（具体用例在实现仓库中定义，但语义必须与本 spec 对齐）。
