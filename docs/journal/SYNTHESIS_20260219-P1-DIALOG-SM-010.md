# SYNTHESIS: P1 Multi-Turn Dialog State Machine Spike

- `thread_id`: `20260219-P1-DIALOG-SM-010`
- `updated_at`: `2026-02-19`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

本草案给出 P1 “多轮对话状态机”（multi-turn dialog state machine）的最小定义，用于把现有多轮输入执行（`mvp assistant-loop-stdio`）提升为“可审计、可回放、可测试”的对话生命周期（dialog lifecycle）。

关键设计取向（draft）：
- **事件溯源优先（event-sourced first）**：状态由“追加式事件日志（append-only event log）”重建，而非依赖隐式内存对象。
- **复用既有落盘底座（reuse existing persistence）**：优先复用 `data/traces/<trace_id>.jsonl`（Trace JSONL）与 `data/evidence/...`（Evidence blobs/meta）作为持久化位置，避免新增不必要的存储契约。
- **不改 CLI 契约（no CLI contract changes）**：本 spike 的外显变化仅允许新增内部 trace event 类型与新增 evidence blob（均为追加，不影响既有输出字段）。

## 最小状态集合（Minimal State Set）

以“会话（Dialog/Session）级别”状态为主；回合（Turn）内部的 TOOL_CALL/ROUTED 等细节复用既有 trace event。

状态（State）集合（建议最小 6 个）：

1. `OPEN`：对话已创建，等待输入（waiting for input）
2. `RUNNING`：正在处理一个回合（processing a turn）
3. `BLOCKED`：被策略/审批/证据缺失阻塞（blocked by policy/approval/missing evidence）
4. `IDLE`：一个回合已完成，仍可继续下一回合（turn completed, session still active）
5. `CLOSED`：对话正常关闭（closed normally）
6. `FAILED`：不可恢复失败（terminal failure）

约束：
- `OPEN` 与 `IDLE` 都表示“可接受下一条用户输入”，区别在于是否已有至少一个 turn（用于诊断与验收用例分类）。
- `FAILED` 为终止态；`CLOSED` 为终止态。

## 事件（Events）

事件（Event）必须可串联 replay（可从 trace + evidence 复核），且应能映射到既有组件边界（assistant_loop/orchestrator/executor）。

建议最小事件类型（event types）：

- `DIALOG_OPENED`：创建对话（create dialog）
  - 字段（fields, draft）：`dialog_id`（建议等同 `trace_id`）、`workspace_id`
- `USER_MESSAGE_RECEIVED`：收到用户输入（ingest user message）
  - 字段：`turn_index`（1-based）、`input_digest`（hash）、`idempotency_key`（如果有）
- `TURN_STARTED`：回合开始（begin turn）
  - 字段：`turn_id`、`span_id`
- `TURN_ROUTED`：计划/路由完成（plan routed）
  - 证据：关联 `kind=routing` evidence（例如 assistant loop 的 plan ref）
- `TURN_EXECUTION_FINISHED`：回合执行结束（execution finished）
  - 字段：`ok`、`error_code?`、`final_output_ref?`（建议以 evidence ref 形式引用）
- `DIALOG_BLOCKED`：对话被阻塞（enter blocked）
  - 字段：`reason`（`requires_human_approval|missing_evidence|policy_violation|...`）
- `DIALOG_CLOSED`：对话关闭（close）
- `DIALOG_FAILED`：对话失败（fail terminal）

实现落点（draft）：
- 事件落盘优先走 `FileTraceLogger.emit()`，以 JSONL 追加写入到 `data/traces/<trace_id>.jsonl`。
- 事件应在 `TraceEvent.event_type` 中编码，例如 `event_type="DIALOG_EVENT"`，并在 `data` 里携带 `dialog_event_type` 与字段。

## 持久化位置（Persistence Location）

本 spike 默认不引入新的顶层存储目录，复用 `data_dir` 下既有布局：

- 事件日志（event log）：
  - `data/traces/<trace_id>.jsonl`
  - 追加 `TraceEvent`（JSONL）条目表示状态机事件与转移
- 事件引用的证据（evidence）：
  - `data/evidence/blobs/<ref>`
  - `data/evidence/meta/<ref>.json`
- 可选快照（snapshot, optional for performance only）：
  - `data/evidence/...` 中增加一个 `kind=snapshot` 的 `dialog_state_snapshot` JSON（内容寻址 ref），并由对应 trace event 引用

不变量（invariants）：
- “源真相（source of truth）”为 event log + evidence blobs；快照仅是加速缓存，必须可丢弃并通过 replay 重建。

## Replay 语义（Replay Semantics）

定义两类 replay：

1. **状态重建 replay（rehydration）**：
   - 输入：`data/traces/<trace_id>.jsonl` + 被引用 evidence refs
   - 输出：确定性的 `DialogState`（对话当前状态）与 `TurnState` 概览
   - 语义：按 JSONL 行顺序应用事件（append-only order），不以 `ts` 排序（避免时钟与并发造成歧义）

2. **执行重放 replay-mode（execution replay, replay_mode=true）**：
   - 约束：不得产生新的远程依赖调用；不得引入新的副作用（no new side effects）
   - 策略（draft）：状态机允许“只读重放”（read-only replay）
     - 若某 turn 的关键 evidence（如 `TURN_ROUTED` 的 plan ref、`TURN_EXECUTION_FINISHED` 的结果 ref）缺失，则进入 `BLOCKED`，并标记 `reason=missing_evidence`

映射到现有系统语义：
- `trace_id` 作为对话/会话 id（dialog_id/session_id）。
- `turn_id/span_id` 使用既有稳定派生规则（例如 `mvp assistant-loop-stdio` 的 `_derive_replayable_id()`）。

## Acceptance（验收草案：测试/命令）

本 spike 的验收以“新增测试 + 不破坏既有测试”为主（no regressions），并已落地为自动化回归。

1. 新增单元测试（unittest，已落地）：
   - `tests/test_spike_p1_dialog_state_machine_replay.py`
   - 覆盖：
     - 事件追加写入后可重建状态（rehydration determinism）
     - 重放不依赖 wall-clock（忽略 `ts` 业务语义）
     - 缺证据（missing evidence）进入 `BLOCKED`

2. 端到端最小命令（不改 CLI 契约，已可复现）：
   - 运行已有 stdio 多轮命令产生 trace/evidence，然后用“重建器（rehydrator）”从 trace 读取并输出状态（重建器可以是库 API，被测试直接调用；不要求新增 CLI）

验收命令（命令级，可复现）：
- 基线（当前可执行，用于确保 thread/synthesis/decisions 合规且无回归）：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_admission_expert_collab_protocol.py' -v`
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- Spike 专用：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_p1_dialog_state_machine_replay.py' -v`

## Implementation（实现落点）

- `src/agentos_next/kernel/dialog_state_machine.py`：rehydration（只读重建）+ missing evidence fail-closed
- `src/agentos_next/cli.py`：在 `mvp assistant-loop-stdio` 追加 `DIALOG_EVENT` 写入（不改变 stdout JSON 字段集合）

## Spec（规范）

- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
