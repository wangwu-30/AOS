# 2026-02-24 外部专家协作线程 015 (External Expert Collaboration Thread 015)

- `thread_id`: `20260224-OPENCLAW-GAP-015`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-24`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

基于外部输入 `Implementation Plan by gemini-3.1`（OpenClaw 对标 gap 分析），发起一轮协作讨论：在不破坏 AgentOS Next 作为“安全、可审计的执行内核（Execution Kernel）”定位前提下，如何演进到 **OpenClaw 级别个人助理（personal assistant）** 的理想目标？

核心问题：

1. 目标定义（North Star）：什么叫 “OpenClaw 级别” 的个人助理？用哪些可验证指标衡量？
2. 路线图（Roadmap）：P0/P1 应该先补齐哪些能力？先做哪些 bounded spikes？
3. 架构分层（Layering）：哪些属于 Kernel（内核），哪些必须在上层 Agent Loop / App/UI 实现？

## 范围 (In Scope)

- 形成一份可执行的 gap→spike 映射清单（含验收标准 acceptance + kill criteria）。
- 明确 3-5 条架构不变量（invariants），作为后续实现的“防回归约束”。
- 对关键分歧给出 bounded spike 方案（含单一硬回退阈值 rollback trigger）。

## 非范围 (Out of Scope)

- 直接实现完整 OpenClaw 产品（本线程以 roadmap/决策为主）。
- 网络 marketplace/远程 registry 的落地实现（后续单独 thread）。
- 任何需要新增 ExecuteRequest 顶层字段（top-level API）的变更（除非出现内核级治理硬需求并经 bounded spike 裁决）。

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级（默认拒绝，越权/缺证据/不确定 MUST 拒绝并写 evidence）。
- replay-mode 无新副作用（no new side effects），不得触发远程执行（remote execution）。
- ExecuteRequest 顶层字段稳定（top-level API stable）；扩展点优先使用 `policy_context`。
- evidence-by-default：关键路径必须可审计、可回放（evidence/trace on-disk schema stable）。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 已完成
- Round 1 (独立提案): 已完成（已收到 ext_gpt5_3, ext_claude, host）
- Round 2 (交叉评审): 待开始
- Round 3 (综合): 已完成（synthesis）
- Round 4 (裁决): 已完成（decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `Implementation Plan by gemini-3.1`（OpenClaw gap 分析原文）
- `docs/journal/inputs/INPUT_ext_gemini_3_1.md`（归档后的外部输入）
- `docs/journal/inputs/INPUT_ext_gpt5_3_openclaw_gap_roadmap.md`
- `docs/journal/inputs/INPUT_ext_claude_openclaw_gap_roadmap.md`
- `docs/journal/inputs/INPUT_host_openclaw_gap_roadmap.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_ai_tutor_reference.md`
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`
- `docs/specs/MVP_010_MEMORY.md`
- `docs/specs/MVP_012_SCHEDULER.md`
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
- `docs/journal/SYNTHESIS_20260224-OPENCLAW-GAP-015.md`
- `docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260224_OPENCLAW_GAP_015_round2_cross_review.md`

