# DECISIONS: THREAD-029 Budget v1（remote_llm_calls）

- `thread_id`: `20260227-BUDGET-REMOTE-LLM-CALLS-029`
- `updated_at`: `2026-02-27`
- `status`: `proposed_for_acceptance`

## Decision 001: budget_slice v1 语义冻结

- **状态**: `accepted`
- **结论**:
  - `ExecuteRequest.budget_slice` v1 固定解释为：`remote_llm_calls`
  - `None` = unlimited（不启用预算限制）
  - `int >= 0` = 本次执行允许的远程 LLM 调用次数上限

## Decision 002: allow-check（Kernel PEP）冻结

- **状态**: `accepted`
- **结论**:
  - schema 非法 -> 拒绝：`E_BUDGET_SCHEMA_INVALID`
  - armed remote LLM（`backend=codex_oauth` 且 double-gate armed）且 budget<=0 -> 拒绝：`E_BUDGET_EXHAUSTED`

## Decision 003: per-call atomic decrement（LLM backend）冻结

- **状态**: `accepted`
- **结论**:
  - 每次远程 LLM 调用前原子扣减 1
  - (N+1) 次调用必须 100% 拦截为 `E_BUDGET_EXHAUSTED`
  - 预算耗尽不得触发 transport（no remote side effects）

## Decision 004: perf_bench v1 阈值冻结

- **状态**: `accepted`
- **结论**:
  - allow-check mean ≤ 2ms/req（`perf_bench --op budget --count 1000`，连续 3 次均值）

## Gate

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed 不降级
3. replay-mode 无新增副作用
4. 回归全绿

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` 输出 `ok=true`
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op budget --count 1000` 输出 `ok=true`
- `tests/test_thread029_budget_v1.py` 通过
- 线程三件套存在：
  - `docs/journal/2026-02-27-expert-collab-thread-029.md`
  - `docs/journal/SYNTHESIS_20260227-BUDGET-REMOTE-LLM-CALLS-029.md`
  - `docs/journal/DECISIONS_20260227-BUDGET-REMOTE-LLM-CALLS-029.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

