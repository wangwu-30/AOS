# 2026-02-28 外部专家协作线程 035 (External Expert Collaboration Thread 035)

- `thread_id`: `20260228-PA-MTR0-035`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

为个人助理应用层提供最小“使用量证据化（metering evidence）”能力：在不引入计费（billing）的前提下，把关键操作（v0: outbox write）落盘为可回放 evidence，并与 trace_id/turn_id 关联。

## 范围 (In Scope)

- metering evidence v0（evidence-only）
- 与 THREAD-033 的 outbox 写入点集成（hook）
- replay-mode：严格 zero-write

## 非范围 (Out of Scope)

- 计费、配额结算（billing）
- token 精算（P1）
- 多维资源树（P2）

## 非协商约束 (Non-Negotiables)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## Evidence (Links)

- `docs/specs/PA_EVENT_ENVELOPE_V0.md`
- `src/agentos_next/pa/metering.py`
- `tests/test_thread035_pa_mtr0_metering_evidence.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_MTR0_035_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_MTR0_035_round2_cross_review.md`
