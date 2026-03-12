# 2026-02-24 外部专家协作线程 018 (External Expert Collaboration Thread 018)

- `thread_id`: `20260224-GT2-GOLDEN-TRACE-GATE-018`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-24`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

落实 THREAD-016 的 gate-2：建立可操作（operational）的 Golden Trace 量化门禁，避免“表面通过、持续抖动（flaky）”。

## 范围 (In Scope)

- 定义 GT2 阈值与回退触发条件
- 提供本地 deterministic 量化评估逻辑
- 用固定场景回归验证阈值有效性

## 非范围 (Out of Scope)

- 线上遥测平台（online telemetry）
- 远程依赖与云端回放
- 改动 ExecuteRequest 顶层字段

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级
- replay-mode 无新增副作用
- evidence/trace schema 稳定

## 轮次进度 (Rounds)

- Round 0: 已完成
- Round 1: 已完成（阈值候选对齐）
- Round 2: 已完成（kill criteria 固化）
- Round 3: 已完成（实现与回归）
- Round 4: 已完成（accepted）

## Evidence (Links)

- `src/agentos_next/apps/golden_trace_gate.py`
- `tests/test_spike_gt2_golden_trace_gate.py`
- `tests/hybrid_gate_helpers.py`
- `docs/journal/SYNTHESIS_20260224-GT2-GOLDEN-TRACE-GATE-018.md`
- `docs/journal/DECISIONS_20260224-GT2-GOLDEN-TRACE-GATE-018.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260224_GT2_GOLDEN_TRACE_GATE_018_round2_cross_review.md`

