# DECISIONS: HY2 Hybrid/Direct 语义等价

- `thread_id`: `20260224-HY2-HYBRID-EQUIVALENCE-017`
- `updated_at`: `2026-02-24`
- `status`: `accepted`

## Decision 001: 是否引入最小 Hybrid runtime 包装层

- **状态**: `accepted`
- **结论**: 接受（A）
  - 增加最小 event-dispatch shell；
  - 保留 direct fallback；
  - 不改变 assistant loop 既有执行语义与输出契约。

## Decision 002: HY2 等价门禁是否覆盖失败路径

- **状态**: `accepted`
- **结论**: 接受（A）
  - 必须覆盖：`HITL_BLOCK` / `REPLAY_BLOCK` / `SCHED_FOLLOWUP_SUCCESS` / `TOOL_FAIL`
  - 必须断言：`ok/error_code/step status` 与 trace 结构稳定键等价。

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 `policy_context`）。
2. replay-mode 无新副作用（禁止远程副作用）。
3. evidence refs 必须可追溯（meta/blob 均存在）。

## Acceptance

- `tests/test_spike_hy2_hybrid_equivalence.py` 通过
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

