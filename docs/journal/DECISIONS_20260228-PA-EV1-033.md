# DECISIONS: THREAD-033 PA-EV1（EventEnvelope/EventLog/Outbox/Dedup）

- `thread_id`: `20260228-PA-EV1-033`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Decision 001: EventEnvelope v0 Single Source of Truth

- **状态**: `accepted`
- **结论**:
  - 共享 spec：`docs/specs/PA_EVENT_ENVELOPE_V0.md`
  - `event_id` 与 `idempotency_key` 必填（REQUIRED）
  - EV1 不推导补全，只做校验与透传（缺失 => fail-closed）

## Decision 002: Dedup Semantics

- **状态**: `accepted`
- **结论**:
  - dedup 主键：`event_id`
  - 若 outbox 已存在：必须 short-circuit 返回同 outbox，不允许二次执行

## Decision 003: Replay-Mode Strict Zero-Write

- **状态**: `accepted`
- **结论**:
  - replay-mode 下：
    - 禁止写 `pa/events` / `pa/outbox` / `pa/dedup`
    - 禁止写 metering evidence
    - 禁止执行 Orchestrator
  - 返回稳定错误码：`E_PA_EV_REPLAY_DENY`

## Decision 004: Error Codes (v0)

- **状态**: `accepted`
- **结论**:
  - `E_PA_EV_SCHEMA_INVALID`
  - `E_PA_EV_REPLAY_DENY`
  - `E_PA_EV_IO_FAILED`

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed 不降级（拒绝路径无 traceback，稳定 error_code）
3. replay-mode 无新增副作用（zero-write）
4. 回归全绿 + thread gate 通过

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `tests/test_thread033_pa_ev1_runtime.py` 通过
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true
- 线程三件套存在：
  - `docs/journal/2026-02-28-expert-collab-thread-033.md`
  - `docs/journal/SYNTHESIS_20260228-PA-EV1-033.md`
  - `docs/journal/DECISIONS_20260228-PA-EV1-033.md`

## 语义不变更说明（Evidence-Based Evolution）

- 本线程新增 PA 层实现，不改动 Kernel `ExecuteRequest/ExecuteResult` 顶层字段与语义（`top_level_api_stable`）。
- replay-mode 下严格 zero-write：EV1 在入口处直接拒绝，不创建任何 File*Store（避免 mkdir 副作用）。
- outbox/dedup 落盘采用 resolved root，避免 macOS `/var` -> `/private/var` 软链接导致的相对路径计算异常（内部实现修复，不改变外部契约）。

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
