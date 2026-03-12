# DECISIONS: THREAD-035 PA-MTR0（Metering Evidence v0）

- `thread_id`: `20260228-PA-MTR0-035`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Decision 001: Metering Evidence v0 (Evidence-Only)

- **状态**: `accepted`
- **结论**:
  - metering v0 只做 evidence，不做计费
  - evidence kind：复用 `snapshot`
  - payload type：`metering_v0`

## Decision 002: Required Fields (Replayable)

- **状态**: `accepted`
- **结论**:
  - metering evidence 必须包含：
    - `workspace_id`
    - `event_id`
    - `trace_id`
    - `turn_id`
    - `op`
    - `ok`
    - `error_code?`

## Decision 003: Replay-Mode Zero-Write

- **状态**: `accepted`
- **结论**:
  - replay-mode 下不落 metering evidence（zero-write）

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed 不降级
3. replay-mode 无新增副作用（zero-write）
4. 回归全绿 + thread gate 通过

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `tests/test_thread035_pa_mtr0_metering_evidence.py` 通过
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true
- 线程三件套存在：
  - `docs/journal/2026-02-28-expert-collab-thread-035.md`
  - `docs/journal/SYNTHESIS_20260228-PA-MTR0-035.md`
  - `docs/journal/DECISIONS_20260228-PA-MTR0-035.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
