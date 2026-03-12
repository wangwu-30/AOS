# [INPUT] Round-2 Synthesis Input by ext_gemini_3_1

- **id**: 20260226-SYNTHESIS-R2-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Round-2 Refinement (028/029 + Capability/Budget)
- **position**: Support Decision B for all items. Prioritize Evidence Integrity (028) as the Root of Trust.

## evidence

1.  **Baseline Verification**: `PYTHONPATH=src python3 -m unittest discover -s tests -v` output: `Ran 105 tests in 4.540s ... OK`.
2.  **Thread Gate Status**: `python3 -m agentos_next.tools.thread_gate_check` output: `ok=true (threads_checked=22, errors=0)`.
3.  **Kernel Policy Logic**: `src/agentos_next/kernel/policy_engine.py` (Line 40-120) implements Replay-mode side-effect blocking and HITL escalation.
4.  **Memory Store Scoping**: `src/agentos_next/kernel/memory_store.py` (Line 15-45) shows `ThreadID` based isolation.
5.  **Executor Interface**: `src/agentos_next/kernel/executor.py` (Line 12-25) defines `ExecuteRequest` with `policy_context`.

## tradeoffs

- **Signing Performance**: HSM/KMS calls add ~50-100ms per signature. 
    - *Mitigation*: Batching signatures for non-critical TraceEvents at Turn boundaries.
- **Budget Granularity**: Call-count (Step budget) is easier to enforce but less accurate for cost; Token精算 is accurate but adds latency.
    - *Mitigation*: Support Decision 002-B (Call budget v1, Token P1).

## open_questions

- Will the `Capability Schema` support dynamic delegation (transferring a sub-handle) during an execution turn?
- For `Decision 003-B`, should `concurrency` be per-workspace or per-trace?

## proposal (Refined 028/029)

### 1. THREAD-028: Evidence Integrity (Signature)
- **Mechanism**: Ed25519 signature of `EvidenceRef.ref` + `content_hash`.
- **Quantitative Kill Criteria**: 
    - Signing Overhead: > 10% latency increase for standard tool calls.
    - Consistency: > 0.1% signature mismatch in high-concurrency (10 agents/sec) stress tests.
- **Acceptance**: `agentos_next.tools.verify_evidence <trace_id>` verifies 100% of stored events without false negatives.

### 2. THREAD-029: Resource Tree (Budget)
- **Mechanism**: Implement `StepBudget` (call count) in `PolicyEngine`.
- **Quantitative Kill Criteria**: 
    - Performance: > 5ms additional delay per `ExecuteRequest` check.
    - Precision: Failure to block the 11th call when `step_budget=10`.
- **Acceptance**: Request with `step_budget=1` is rejected on the second sub-tool call with `E_BUDGET_EXHAUSTED`.

## acceptance

- `INPUT_ext_gemini_3_1_kernel_synthesis_r2.md` passing `thread_gate_check`.
- Alignment with Decision B for 001/002/003.

## confidence

high
