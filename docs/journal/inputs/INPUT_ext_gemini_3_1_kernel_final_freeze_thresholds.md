# [INPUT] Final Performance Threshold Review (Guardrail Baseline) by ext_gemini_3_1

- **id**: 20260227-FINAL-FREEZE-THRESHOLDS-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Performance Guardrails for THREAD-028 / THREAD-029
- **position**: Finalize quantitative thresholds to be enforced by the `thread_gate_check` during implementation.

## 1. THREAD-028: Evidence Integrity (v1)

- **Signing Latency (P95)**: 
    - **Threshold**: < 50ms per `TraceEvent`.
    - **Guardrail**: If implementation uses synchronous Ed25519, any tool call chain exceeding 10 steps must not show a total signing overhead > 500ms.
- **Verification Performance**:
    - **Threshold**: `verify_evidence` tool must process 1000 events in < 2 seconds.
- **Reliability (Hard Invariant)**:
    - **Mismatch Rate**: 0% allowed. Any signature mismatch results in immediate `fail_closed` of the turn.

## 2. THREAD-029: Budget v1 (Remote LLM Calls)

- **Enforcement Latency**:
    - **Threshold**: < 2ms per `remote_llm_call` check (local counter decrement).
- **Correctness (Hard Invariant)**:
    - **Leaking**: 0.0% false negatives. If `budget_slice=N`, the (N+1)th call MUST target `E_BUDGET_EXHAUSTED`.
- **Inheritance Safety**:
    - **Guardrail**: Delegation to child agents MUST NOT "double-spend" tokens. Total tree consumption must be <= Root `budget_slice`.

## 3. Implementation Guardrail Checklist (For ext_gpt5_3)

- [ ] **Zero-Side-Effect Replay**: `verify_evidence` MUST NOT write any logs or temp files during checking.
- [ ] **Stable Error Codes**: All 028/029 failures MUST map exactly to the frozen `E_*` codes defined in Round-4.
- [ ] **Evidence Lineage**: Each `E_BUDGET_EXHAUSTED` or `E_EVIDENCE_VERIFY_FAILED` MUST be paired with a `TraceEvent` of `event_type=ERROR` with associated refs.

## confidence
high
