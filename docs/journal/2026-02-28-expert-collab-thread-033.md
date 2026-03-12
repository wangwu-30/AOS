# 2026-02-28 外部专家协作线程 033 (External Expert Collaboration Thread 033)

- `thread_id`: `20260228-PA-EV1-033`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

为“个人助理应用层（PA）”提供最小事件执行闭环：把来自渠道适配层的 `EventEnvelope v0` 写入事件日志，并通过 Kernel `Orchestrator.execute(ExecuteRequest)` 执行一次技能调用，最终落盘可回放的 outbox 结果；同时必须满足幂等去重与 replay-mode zero-write。

## 范围 (In Scope)

- EventEnvelope v0（shared truth source）
- EventLog（write-once per event_id）
- Outbox（write-once per event_id, short-circuit dedup）
- replay-mode：严格 zero-write（deny）
- 错误码冻结（app 层最小集合）：
  - `E_PA_EV_SCHEMA_INVALID`
  - `E_PA_EV_REPLAY_DENY`
  - `E_PA_EV_IO_FAILED`

## 非范围 (Out of Scope)

- 多渠道、多路由、多 skill 分发（P1）
- TG1 TaskGraph / ReAct 编排（P1）
- 计费（billing），本线程只做 metering evidence hook（由 THREAD-035 定义）

## 非协商约束 (Non-Negotiables)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## Evidence (Links)

- `docs/specs/PA_EVENT_ENVELOPE_V0.md`
- `src/agentos_next/pa/ev1_runtime.py`
- `src/agentos_next/pa/event_log.py`
- `src/agentos_next/pa/outbox_store.py`
- `tests/test_thread033_pa_ev1_runtime.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_EV1_033_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_EV1_033_round2_cross_review.md`
