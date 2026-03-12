# 2026-02-19 外部专家协作线程 008 (External Expert Collaboration Thread 008)

- `thread_id`: `20260219-SCHED1-008`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

实现 AgentOS Next 的 Scheduler P0 原语（Scheduler Primitives），使系统具备“可持久化的延迟/定时触发”（durable delayed trigger）能力，并且触发后执行语义完全复用现有 `Orchestrator.execute(ExecuteRequest)` 的 fail-closed、幂等（idempotency）与 evidence/trace 机制。

本线程对应 Spike：`Spike-SCHED1`。

## 范围 (In Scope)

- builtin 特权技能（privileged skills）：
  - `builtin://scheduler.at`
  - `builtin://scheduler.cron`
- Scheduler 数据持久化（durable persistence）：`data/scheduler/` 下的任务索引与任务定义
- 执行语义：按时触发 `ExecuteRequest`（或其草案），并调用 `Orchestrator.execute`
- 治理（governance）：严格遵守 `deadline_ms` 与 `policy_context` 约束；不得绕过 replay-mode 与双闸门（double-gating）

## 非范围 (Out of Scope)

- 生产级常驻 daemon、分布式一致性、跨机器抢占（leader election）
- 复杂 cron 兼容（仅实现子集）
- 远程沙箱执行的生产落地（本线程只要求语义对齐与可透传）

## 非协商约束 (Non-Negotiables)

- 不得破坏既有 CLI 稳定 JSON 输出与 evidence/trace schema（仅新增能力/命令/字段）。
- 所有触发与执行必须可审计、可回放（replayable）。
- replay-mode 下 MUST 禁远程；双闸门不降级。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): N/A（MVP 快速迭代：先落地再补交叉评审）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## 消息记录 (Message Log)

- ext_gpt5_2: 提议并落地 “builtin 创建任务 + 显式 tick runner 触发” 的 MVP 方案（见 inputs/specs）
- host: 强调 non-negotiables（fail-closed、deadline、evidence/trace、replay-mode 双闸门不降级）

## Evidence (Links)

- `docs/specs/MVP_012_SCHEDULER.md`（SCHED1 规范草案）
- `docs/specs/EXECUTOR_API.md`（ExecuteRequest/ExecuteResult 语义）
- `docs/specs/EVIDENCE_TRACE.md`（Evidence/Trace 可回放）
- `docs/specs/LLM_PROVIDER.md`（replay-mode 与 double-gating）
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`（thread/synthesis/decisions 协议）
- `docs/journal/inputs/INPUT_ext_gpt5_2.md`（message id: `20260219-ext_gpt5_2-008`）
- `src/agentos_next/kernel/scheduler_store.py`
- `src/agentos_next/runtime/builtin_scheduler.py`
- `src/agentos_next/apps/scheduler_tick.py`
- `tests/test_spike_sched1_scheduler.py`
- `docs/journal/SYNTHESIS_20260219-SCHED1-008.md`
- `docs/journal/DECISIONS_20260219-SCHED1-008.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_SCHED1_008_round2_cross_review.md`

