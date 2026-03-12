# 2026-02-28 外部专家协作线程 036 (External Expert Collaboration Thread 036)

- `thread_id`: `20260228-PA-E2E-036`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

对 THREAD-033/034/035 做端到端一致性验证：从 Telegram webhook fixture 触发 CH1 产出 EventEnvelope v0，再由 EV1 执行并写 outbox，同时写 metering evidence，并验证幂等去重与 replay-mode 双零副作用。

## 范围 (In Scope)

- 端到端最小链路：webhook -> envelope -> EV1 execute -> outbox -> metering evidence
- 幂等：same update_id => dedup short-circuit
- replay-mode：CH1 不 dispatch，EV1 strict deny zero-write

## 非范围 (Out of Scope)

- 不新增功能
- 不改 PA_EVENT_ENVELOPE_V0.md 语义
- 不引入任何网络 side effects

## 非协商约束 (Non-Negotiables)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## Evidence (Links)

- `docs/specs/PA_EVENT_ENVELOPE_V0.md`
- `src/agentos_next/apps/telegram_connector.py`
- `src/agentos_next/pa/ev1_runtime.py`
- `tests/test_thread036_pa_e2e_chain.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_E2E_036_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_E2E_036_round2_cross_review.md`
