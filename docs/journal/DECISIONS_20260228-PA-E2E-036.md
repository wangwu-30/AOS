# DECISIONS: THREAD-036 PA E2E（033+034+035）

- `thread_id`: `20260228-PA-E2E-036`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Decision 001: E2E Chain (Frozen)

- **状态**: `accepted`
- **结论**:
  - E2E 仅做一致性验证，不新增功能：
    - webhook -> envelope -> EV1 execute -> outbox -> metering evidence

## Decision 002: Idempotency (Frozen)

- **状态**: `accepted`
- **结论**:
  - same update_id => same event_id，EV1 dedup short-circuit（禁止二次执行副作用）

## Decision 003: Replay-Mode Double Zero Side Effects

- **状态**: `accepted`
- **结论**:
  - CH1 replay-mode：不 dispatch（无执行/无网络 side effects）
  - EV1 replay-mode：strict deny + zero-write（patch(Path.mkdir) 必须通过）

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed 不降级（错误路径稳定 error_code，无 traceback）
3. replay-mode 无新增副作用（zero-write）
4. 回归全绿 + thread gate 通过

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread036_pa_e2e_chain.py -v` 通过
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true
- 线程三件套存在：
  - `docs/journal/2026-02-28-expert-collab-thread-036.md`
  - `docs/journal/SYNTHESIS_20260228-PA-E2E-036.md`
  - `docs/journal/DECISIONS_20260228-PA-E2E-036.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
