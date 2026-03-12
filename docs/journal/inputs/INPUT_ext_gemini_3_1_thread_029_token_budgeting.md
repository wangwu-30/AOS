# [INPUT] THREAD-029: Token Budgeting (Resource Slice)

- **id**: 20260226-THREAD-029-PROPOSAL-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Token Budgeting (Simplified Resource Model)
- **position**: Enforce `budget_slice` (tokens only) at the Kernel Policy Gate to prevent cost runaway.

## evidence
1.  **Current API**: `ExecuteRequest` already has an optional `budget_slice` field ([executor.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/executor.py)).
2.  **Implementation Gap**: `PolicyEngine` (Line 40+) does not currently decrement or verify this slice against LLM usage.
3.  **Report Insight**: *deep-research-report.md* (Line 128) notes `cgroups v2` as the gold standard for hierarchical resource allocation.

## tradeoffs
- **Precision vs Speed**: Tracking every token in real-time requires tight coupling with the LLM Provider stream.
- **Fail-closed Strategy**: If an Agent exceeds its slice mid-stream, cutting the connection immediately may result in a loss of "Final Thought" evidence.

## open_questions
- How do we handle "Budget Inheritance" when a Root Agent delegates to a Child Agent?
- Should the Kernel "lock" tokens from the User's balance before execution, or only audit after?

## proposal
### Bounded Spike: Token Budget Enforcer
1.  Update `PolicyEngine` to treat `budget_slice` as "Max Allowed Tokens" for the current `ExecuteRequest`.
2.  Intercept LLM response metadata to update the remaining slice in the current `TraceContext`.
3.  Reject any sub-request if the parent `budget_slice` is exhausted.

## acceptance
- `ExecuteRequest` with `budget_slice=10` and an LLM task requiring 50 tokens results in `E_BUDGET_EXHAUSTED`.
- Evidence shows exact token consumption per turn.

## confidence
high
