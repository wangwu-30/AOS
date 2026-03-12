# SYNTHESIS: THREAD-029 Budget v1（remote_llm_calls）

- `thread_id`: `20260227-BUDGET-REMOTE-LLM-CALLS-029`
- `updated_at`: `2026-02-27`
- `status`: `resolved`

## 综合结论

- v1 预算治理聚焦最小闭环：`ExecuteRequest.budget_slice` 固定解释为 `remote_llm_calls`（不做 token 精算）。
- allow-check 在 Kernel PEP 统一执行：budget schema 非法与 budget=0 的 armed remote LLM 直接拒绝（stable error_code + policy evidence + trace）。
- per-call atomic decrement 在远程 backend 入口执行：每次 `CodexOAuthLLMBackend.complete_json` 调用前扣减 1，(N+1) 次调用必拦截且不得触发 transport（false-negative=0）。
- perf_bench `--op budget` 用于 v1 allow-check 开销守门：mean ≤ 2ms/req。

## v1 关键冻结点

- 语义：
  - `budget_slice=None`：不启用预算限制
  - `budget_slice=int>=0`：允许的 remote LLM 调用次数上限
- 错误码（MUST）：
  - `E_BUDGET_EXHAUSTED`
  - `E_BUDGET_SCHEMA_INVALID`
- 关键落点：
  - allow-check：`src/agentos_next/kernel/policy_engine.py`
  - per-call：`src/agentos_next/llm/backend.py`
  - status 映射：`src/agentos_next/runtime/execute_mapping.py`（budget exhausted => rejected）
  - perf：`src/agentos_next/tools/perf_bench.py`

## Gate（通过条件）

1. 不新增 ExecuteRequest 顶层字段（policy_context-only 扩展保持）
2. 拒绝路径稳定 error_code + evidence + trace（无 traceback）
3. (N+1) remote LLM 调用必须拦截（false-negative=0）
4. perf_bench allow-check mean ≤ 2ms/req
5. 回归全绿

## 验收锚点

- `tests/test_thread029_budget_v1.py`
- `docs/specs/MVP_029_BUDGET.md`

