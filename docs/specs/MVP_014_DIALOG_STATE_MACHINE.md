# MVP-014 多轮对话状态机（Multi-turn Dialog State Machine）

- 状态（Status）：Draft
- 日期（Date）：2026-02-19
- 目标 Spike（Target Spike）：P1-SM1
- 相关规范（Related Specs）：
  - `docs/specs/EXECUTOR_API.md`（ExecuteRequest/ExecuteResult）
  - `docs/specs/EVIDENCE_TRACE.md`（Evidence/Trace）
  - `docs/specs/LLM_PROVIDER.md`（replay-mode + double-gating）
  - `docs/specs/VERSIONING_COMPAT.md`（Versioning）

## 1. 目的（Purpose）

为 AgentOS Next 的多轮交互（multi-turn interaction）补齐“会话（session/dialog）生命周期”的最小状态机定义，使其具备：

- 可审计（auditable）：关键状态转移落盘到 Trace/Evidence
- 可回放（replayable）：可从 `data/traces/<trace_id>.jsonl` 重建当前对话状态（rehydration）
- 不破坏契约（non-breaking）：不修改既有 CLI 输出 JSON 字段集合与退出码语义（exit code semantics）

## 2. 核心原则（Principles）

1. 事件优先（event-first）：状态由追加式事件（append-only events）重建，不依赖进程内隐式对象。
2. 复用底座（reuse persistence）：复用 `FileTraceLogger` 与 `FileEvidenceStore`，不引入新的“对外持久化 API”。
3. Fail-Closed：缺证据（missing evidence）或事件不完整时，重建必须进入 `BLOCKED` 或 `FAILED`，不能“假装没事”。
4. replay-mode 不降级：`replay_mode=true` 的远程禁用与双闸门策略不变；状态机仅增加“只读重建”能力，不引入远程依赖。

## 3. 不可破坏约束（Non-Negotiables / Invariants）

- 不得修改既有命令的稳定 JSON 输出字段集合（只允许新增命令或仅增加 trace/evidence 落盘）。
- `TraceEvent` 的 schema 必须保持向前兼容（forward-compatible）：仅新增 `event_type` 值与 `data` 子字段，不新增必填字段。

## 4. 概念与标识（Concepts/Identifiers）

- dialog_id（对话 id）：MVP 定义为 `trace_id`
- turn_index（回合序号）：1-based（用于 deterministic 派生与可回放）
- turn_id/span_id：复用既有派生规则（例如 `assistant-loop-stdio` 的 `_derive_replayable_id()`）

## 5. 状态集合（States）

最小状态集合（MUST）：

- `OPEN`：对话已创建，尚未完成任何 turn
- `RUNNING`：正在处理一个 turn
- `BLOCKED`：被策略/证据缺失阻塞（例如 HITL required、missing evidence）
- `IDLE`：完成一个 turn，仍可继续下一 turn
- `CLOSED`：正常终止（terminal）
- `FAILED`：不可恢复失败（terminal）

## 6. 事件模型（Events）

### 6.1 TraceEvent 形态

新增 TraceEvent `event_type`（MUST）：`DIALOG_EVENT`

其 `data` MUST 包含：
- `dialog_event_type`：枚举见 6.2
- `dialog_id`：默认等同 `trace_id`
- `turn_index`：可选（部分事件为 session 级）

事件 payload 不应直接写入大量正文；大对象 SHOULD 落 evidence（`kind=tool_io|snapshot|routing|error`），并通过 `evidence_refs` 引用。

### 6.2 dialog_event_type

最小事件集合（MUST）：

- `DIALOG_OPENED`
- `USER_MESSAGE_RECEIVED`
- `TURN_STARTED`
- `TURN_FINISHED`

可选扩展（SHOULD, future）：

- `DIALOG_BLOCKED`（reason 进入 BLOCKED）
- `DIALOG_CLOSED`
- `DIALOG_FAILED`

### 6.3 TURN_FINISHED 最小字段

`TURN_FINISHED` 的 `data` MUST 包含：
- `ok`: boolean
- `error_code`: string|null
- `final_snapshot_ref`: string|null（指向 assistant loop 的最终 snapshot evidence ref，若可用）

## 7. Rehydration（状态重建）

提供库 API（MUST）：

- `rehydrate_dialog_state(data_dir, trace_id, require_evidence=True) -> DialogState`

语义：
- 仅按 JSONL 行顺序应用 `DIALOG_EVENT`（不按 ts 排序）
- 当 `require_evidence=true`：
  - `TURN_FINISHED` 事件引用的 `final_snapshot_ref`（或 evidence_refs 中的 refs）若缺失，则进入 `BLOCKED`，reason=`missing_evidence`

## 8. Acceptance（验收）

必须（MUST）：

- 全量回归：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 新增测试：
  - 运行 `mvp assistant-loop-stdio` 产生多轮 trace，然后用 rehydrator 重建状态应确定性一致。
  - 删除一个被引用的 evidence/meta 后，rehydration 必须进入 `BLOCKED (missing_evidence)`。

