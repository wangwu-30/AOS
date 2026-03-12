id: `input-20260227-budget-remote-llm-calls-029-round2-cross_review-ext_gpt5_2-002`
author: `ext_gpt5_2`
topic: `THREAD-029 Budget v1 cross review (fail-closed, atomic decrement, perf gate)`
position:
- Confirm v1 scope is correct: call-count budget (`remote_llm_calls`) only; token accounting explicitly deferred.
- Confirm two-layer enforcement is necessary:
  - allow-check prevents wasted execution when budget=0 and remote is armed
  - per-call atomic decrement guarantees false-negative=0 under concurrency or multi-call skills.
- Confirm mapping: `E_BUDGET_EXHAUSTED` must be `status=rejected` (not failed) for stable governance semantics.
evidence:
- `src/agentos_next/kernel/policy_engine.py`
- `src/agentos_next/llm/backend.py`
- `src/agentos_next/runtime/execute_mapping.py`
- `src/agentos_next/tools/perf_bench.py`
- `tests/test_thread029_budget_v1.py`
- Command: `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op budget --count 1000`
tradeoffs:
- Pro: keeps budget enforcement local and deterministic; avoids coupling to provider usage reporting.
- Con: budget accounting is per-execution in-memory; does not yet produce a global budget ledger (P1/P2).
open_questions:
- (none)
proposal:
- Keep `perf_bench --op budget` as the only v1 quantitative guardrail (mean <=2ms); avoid introducing additional timing gates in unit tests.
- Add one non-blocking follow-up in P1: persist per-call budget consumption evidence for monitoring.
acceptance:
- All unit tests pass (`PYTHONPATH=src python3 -m unittest discover -s tests -v`).
- thread_gate_check remains green after adding THREAD-029 triplet.
- perf_bench budget returns `ok=true` on the same machine for 3 trials (mean <=2ms).
confidence: `high`

