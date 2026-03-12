# 2026-02-20 外部专家协作线程 012 (External Expert Collaboration Thread 012)

- `thread_id`: `20260220-FU2-FOLLOWUP-SCHED-012`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-20`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

立项 FU2：把 FU1 的 plan-only follow-up（主动跟进计划）升级为“可调度执行（schedulable execution）”，完成 assistant loop × scheduler 的最小闭环：

- 用户显式请求 follow-up（通过 CLI flag）时，assistant loop 负责创建 `builtin://scheduler.at` 任务
- 到期后由 `scheduler-tick` 触发执行，并通过 SM2 写入 dialog 的 `DIALOG_EVENT`（可回放）

目标：从“功能型助手”推进到“可持续运转的 OS 循环（OS loop）”，但仍保持：
- ExecuteRequest 顶层字段稳定（top-level API stable）
- 所有扩展继续走 `policy_context`（forward-compatible）
- replay-mode 下不产生新副作用（no new side effects）

## 范围 (In Scope)

- 为 `mvp assistant-loop` 与 `mvp assistant-loop-stdio` 增加显式 follow-up 调度入口：
  - `--followup-at <UTC ISO>`（可选）
- assistant loop 在 `ok=true` 且 `replay_mode=false` 时，通过 Orchestrator 执行 `builtin://scheduler.at` 创建任务（利用 Orchestrator 的 idempotency_store 避免重复创建）。
- 任务的 `execute_request.policy_context` MUST 注入：
  - `dialog_trace_id=<session trace_id>`（用于 SM2 写 dialog 事件）
- 新增回归测试：
  - 能创建 follow-up 任务，并可用 `scheduler-tick` 触发执行
  - 缺证据（missing evidence）时 rehydration 必须进入 `BLOCKED`

## 非范围 (Out of Scope)

- push 通知通道（Telegram/Discord）
- follow-up 的复杂重试、退避、跨设备同步
- 将 trigger 升格为 ExecuteRequest 顶层字段（除非出现内核级配额拦截硬需求）

## 非协商约束 (Non-Negotiables)

- 不得破坏既有 CLI 稳定 JSON 输出字段集合（仅新增 flag、追加 evidence/trace）。
- fail-closed 不降级：replay-mode 禁远程；double-gating 不降级。
- scheduler 创建必须走 Orchestrator（以 idempotency_key 去重），避免重复副作用。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): N/A（MVP 快速迭代：先落地再补交叉评审）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`（FU1 followup_plan_ref）
- `docs/specs/MVP_012_SCHEDULER.md`（scheduler.at + scheduler-tick）
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`（rehydration / BLOCKED）
- `docs/specs/MVP_015_SCHEDULER_DIALOG_LINK.md`（SM2：dialog_trace_id + trigger）
- `docs/specs/MVP_016_FOLLOWUP_SCHEDULING.md`（FU2：本 spike 规范）
- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/apps/scheduler_tick.py`
- `tests/test_spike_fu2_followup_scheduling.py`
- `docs/journal/SYNTHESIS_20260220-FU2-FOLLOWUP-SCHED-012.md`
- `docs/journal/DECISIONS_20260220-FU2-FOLLOWUP-SCHED-012.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260220_FU2_FOLLOWUP_SCHED_012_round2_cross_review.md`

