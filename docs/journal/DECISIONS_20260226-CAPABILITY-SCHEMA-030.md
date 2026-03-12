# DECISIONS: THREAD-030 Capability Schema v1（policy_context.capabilities[]）

- `thread_id`: `20260226-CAPABILITY-SCHEMA-030`
- `updated_at`: `2026-02-26`
- `status`: `proposed_for_acceptance`

## Decision 001: Capability Schema v1

- **状态**: `accepted`
- **结论**:
  - capability 通过 `policy_context.capabilities[]` 声明（machine-checkable）
  - 每项必须包含：
    - `name`（allowlist）
    - `scope`（`workspace|skill|turn`）
  - unknown capability name / 非法 schema：fail-closed
    - `E_CAPABILITY_SCHEMA_INVALID`

## Decision 002: PEP Default Deny

- **状态**: `accepted`
- **结论**:
  - 对需要 capability 的请求：缺失 required capability 必须拒绝
    - `E_CAPABILITY_DENY`
    - `reason_code=capability_missing`
  - 拒绝路径必须写 policy evidence + trace（可回放）

## Decision 003: Required Capability Mapping（v1）

- **状态**: `accepted`
- **结论**:
  - `builtin://memory.{write,delete,compact}` => `memory_write`
  - `builtin://scheduler.{at,cron}` => `scheduler_write`
  - `allow_network_egress=true` => `net_egress`
  - `remote_calls_armed=true` or `backend=codex_oauth` => `llm_remote`

## Decision 004: HITL 错误码复用

- **状态**: `accepted`
- **结论**:
  - 高风险审批复用 `E_HITL_REQUIRED`（不新增同义码）

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed 不降级
3. 回归全绿

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `tests/test_thread030_capability_schema.py` 通过
- 线程三件套存在：
  - `docs/journal/2026-02-26-expert-collab-thread-030.md`
  - `docs/journal/SYNTHESIS_20260226-CAPABILITY-SCHEMA-030.md`
  - `docs/journal/DECISIONS_20260226-CAPABILITY-SCHEMA-030.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

