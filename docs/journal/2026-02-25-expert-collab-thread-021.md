# 2026-02-25 外部专家协作线程 021 (External Expert Collaboration Thread 021)

- `thread_id`: `20260225-UI1-021`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-25`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

基于 THREAD-026 Kernel Policy Engine 边界定义，构建最小 TUI + HITL 审批 + trace/evidence 可视化验收壳。

## 范围 (In Scope)

- 最小 TUI 交互入口（任务输入/状态展示）
- HITL 审批视图（pending/approved/rejected + reason + evidence_refs）
- trace/evidence 可视化最小闭环

## 非协商约束 (Non-Negotiables)

- fail-closed、double-gating、replay-mode zero-write
- 不新增 ExecuteRequest 顶层字段（policy_context-only）

## 决策 (Decision)

- UI 仅展示与交互，不拥有 allow/deny 最终裁决权
- 裁决权归属：Kernel Policy Engine（PEP）

## 轮次进度 (Rounds)

- Round 0-3: 已完成
- Round 4: 已完成（accepted）

## Evidence (Links)

- docs/journal/inputs/INPUT_ext_claude_ui1_round1.md
- docs/journal/inputs/INPUT_ext_claude_thread021_r2.md
- docs/journal/inputs/INPUT_ext_claude_thread021_r3.md

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260225_UI1_021_round2_cross_review.md`
