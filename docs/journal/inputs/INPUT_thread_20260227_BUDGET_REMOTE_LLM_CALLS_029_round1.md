id: `input-20260227-budget-remote-llm-calls-029-round1-ext_gpt5_2-001`
author: `ext_gpt5_2`
topic: `THREAD-029 Budget v1 (ExecuteRequest.budget_slice=remote_llm_calls)`
position:
- Define `ExecuteRequest.budget_slice` v1 meaning as `remote_llm_calls` (call-count budget), not token accounting.
- Enforce budget in two layers:
  - allow-check in Kernel PolicyEngine (schema + pre-deny when armed remote backend)
  - per-call atomic decrement in `CodexOAuthLLMBackend.complete_json` (block (N+1)th call with `E_BUDGET_EXHAUSTED` and no transport).
- Keep top-level API stable (no new ExecuteRequest fields) and preserve replay/fail-closed semantics.
evidence:
- `docs/specs/MVP_029_BUDGET.md`
- `src/agentos_next/kernel/policy_engine.py`
- `src/agentos_next/llm/backend.py`
- `src/agentos_next/runtime/execute_mapping.py`
- `src/agentos_next/tools/perf_bench.py`
- `tests/test_thread029_budget_v1.py`
- Command: `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` (115/115 OK)
tradeoffs:
- Pro: deterministic, auditable, and easy to enforce without provider usage integration; blocks budget leaks with atomic decrement.
- Con: v1 only governs remote LLM call count; token-level cost control deferred to P1; policy pre-deny only triggers when remote backend is armed.
open_questions:
- Should we persist budget consumption into evidence for post-hoc analysis in P1? (out of v1)
proposal:
- Freeze error codes:
  - `E_BUDGET_SCHEMA_INVALID` for invalid budget_slice types/values
  - `E_BUDGET_EXHAUSTED` for exhausted remote LLM call budget
- Add CLI support: `mvp exec --budget-slice <int>` to exercise the feature.
acceptance:
- `tests/test_thread029_budget_v1.py` passes:
  - schema invalid -> `E_BUDGET_SCHEMA_INVALID`
  - budget=0 (armed remote) -> `E_BUDGET_EXHAUSTED`
  - second remote call blocked -> `E_BUDGET_EXHAUSTED` and no extra transport request
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op budget --count 1000` returns `ok=true`.
confidence: `high`

