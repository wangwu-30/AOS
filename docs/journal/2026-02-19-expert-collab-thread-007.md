# 2026-02-19 外部专家协作线程 007 (External Expert Collaboration Thread 007)

- `thread_id`: `20260219-FU1-FOLLOWUP-007`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

在 assistant loop 内引入 “follow-up / 主动跟进” 的最小闭环：只产出 plan（plan-only），不做真实调度执行（no side effects），验证其可审计与可回放语义。

## 范围 (In Scope)

- 生成 follow-up plan（bounded <= 5）
- follow-up plan 落 evidence（不含 timestamp，保证 deterministic）
- assistant-loop 输出包含 follow-up plan 的 ref（便于上层消费）

## 非范围 (Out of Scope)

- 真实 scheduler/cron 执行
- push 通知

## 非协商约束 (Non-Negotiables)

- 不得引入远程依赖；replay-mode 仍必须禁远程。
- 不得破坏既有 CLI/evidence/trace 契约（仅新增 assistant-loop 的输出字段）。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（实现落地）
- Round 2 (交叉评审): 完成（回归覆盖）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/journal/2026-02-19-expert-collab-thread-003.md`（OpenCLAW P0: Follow-up）
- `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md`（assistant loop gate）
- `docs/journal/SYNTHESIS_20260219-FU1-FOLLOWUP-007.md`
- `docs/journal/DECISIONS_20260219-FU1-FOLLOWUP-007.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_FU1_FOLLOWUP_007_round2_cross_review.md`

