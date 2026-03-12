# 2026-02-24 外部专家协作线程 017 (External Expert Collaboration Thread 017)

- `thread_id`: `20260224-HY2-HYBRID-EQUIVALENCE-017`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-24`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

落实 THREAD-016 的 gate-1：实现并验证 Hybrid runtime 与 direct fallback 的语义等价（semantic equivalence），避免双路径漂移（dual-path drift）。

## 范围 (In Scope)

- 增加最小 Hybrid runtime 包装层（event-dispatch shell + direct fallback）
- 覆盖 4 个关键场景：`HITL_BLOCK` / `REPLAY_BLOCK` / `SCHED_FOLLOWUP_SUCCESS` / `TOOL_FAIL`
- 断言稳定键等价与 trace 结构等价

## 非范围 (Out of Scope)

- 完整插件系统（plugin/hook）
- 新增 ExecuteRequest 顶层字段
- 引入远程依赖

## 非协商约束 (Non-Negotiables)

- fail-closed / replay-mode / double-gating 不降级
- `policy_context` 扩展边界不变
- evidence/trace 可回放、可追溯

## 轮次进度 (Rounds)

- Round 0: 已完成
- Round 1: 已完成（方案确认）
- Round 2: 已完成（失败路径等价约束）
- Round 3: 已完成（实现与测试）
- Round 4: 已完成（accepted）

## Evidence (Links)

- `src/agentos_next/apps/assistant_runtime.py`
- `src/agentos_next/cli.py`
- `tests/hybrid_gate_helpers.py`
- `tests/test_spike_hy2_hybrid_equivalence.py`
- `docs/journal/SYNTHESIS_20260224-HY2-HYBRID-EQUIVALENCE-017.md`
- `docs/journal/DECISIONS_20260224-HY2-HYBRID-EQUIVALENCE-017.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260224_HY2_HYBRID_EQUIVALENCE_017_round2_cross_review.md`

