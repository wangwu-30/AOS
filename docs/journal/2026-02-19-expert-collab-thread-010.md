# 2026-02-19 外部专家协作线程 010 (External Expert Collaboration Thread 010)

- `thread_id`: `20260219-P1-DIALOG-SM-010`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

起草 P1 “多轮对话状态机”（multi-turn dialog state machine, dialog state）spike 定义：在不改变既有 CLI 契约（CLI contract）的前提下，把“会话/回合/步骤”的状态与关键事件落盘为可回放证据（replayable evidence），并给出可执行验收（acceptance commands）。

当前已有：
- 单轮 assistant loop（`AssistantLoopRequest/Result`）
- stdio 多轮输入驱动（`mvp assistant-loop-stdio`）但缺少明确的“对话状态（dialog state）/事件（events）/重放（replay）”边界与最小状态集合定义

本 spike 目标是补齐“状态机定义 + 持久化 + replay 语义 + 验收测试/命令”，并明确 kill criteria（终止条件）。

## 范围 (In Scope)

- 最小状态集合（minimal state set）与状态转移事件（events）。
- 持久化位置（persistence location）：事件落盘与 evidence refs 关联。
- replay 语义（replay semantics）：从落盘事件重建状态；replay-mode 下的约束与 fail-closed 行为。
- 最小验收（acceptance）：新增测试设计 + 可复现命令（不要求本草案阶段立即实现）。

## 非范围 (Out of Scope)

- 新增/修改对外 CLI 子命令；新增/修改任何既有 CLI 输出 JSON 字段或退出码（exit code semantics）。
- 放宽 `replay_mode=true` 禁远程策略；引入新的远程依赖（remote dependency）。
- 全量“对话记忆产品化”（摘要、长期记忆治理、跨设备同步等）。

## 非协商约束 (Non-Negotiables)

- 不得破坏既有 CLI 契约与既有测试（尤其 `mvp channel-stdio`、`mvp assistant-loop-stdio`、`mvp run-package`）。
- `replay_mode=true` MUST 禁远程（remote LLM / network egress）；状态机必须支持离线重建（offline rehydration）。
- 落盘必须可审计（auditable）：关键转移应可由 trace + evidence 复核。
- 事件载荷尽量确定性（deterministic）：除 trace 的 `ts` 外，避免引入不可复现业务字段（例如 wall-clock 作为业务数据）。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成（本文件 + 目标/约束/验收口径已落盘）
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): N/A（MVP 快速迭代：先落地再补交叉评审）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`（thread/synthesis/decisions 协议）
- `docs/specs/EVIDENCE_TRACE.md`（evidence/trace/replay 语义）
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`（P1 多轮状态机规范）
- `src/agentos_next/apps/assistant_loop.py`（单轮执行与 replay_mode 约束）
- `src/agentos_next/cli.py`（`mvp assistant-loop-stdio` 多轮输入与可回放 id 派生）
- `src/agentos_next/kernel/dialog_state_machine.py`（rehydration：只读重建）
- `tests/test_spike_p1_dialog_state_machine_replay.py`
- `docs/journal/SYNTHESIS_20260219-P1-DIALOG-SM-010.md`
- `docs/journal/DECISIONS_20260219-P1-DIALOG-SM-010.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_P1_DIALOG_SM_010_round2_cross_review.md`

