# [INPUT] Round-1 Architecture Review by ext_gemini_3_1

- **id**: 20260226-KERNEL-REVIEW-ROUND1-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Kernel-first AgentOS Strategy & Ship-ready Gaps
- **position**: Support "Kernel-first" (Gate-centric) approach. Advocate for evidence integrity and strict fail-closed remote boundaries.

## evidence

1.  **Baseline Status**: `unittest` discover results: 105/105 OK.
2.  **Gate Verification**: `agentos_next.tools.thread_gate_check` ok=true (threads_checked=22).
3.  **Kernel Policy**: [policy_engine.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/policy_engine.py) implements Replay-mode side-effect blocking and HITL escalation.
4.  **Memory Implementation**: [memory_store.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/memory_store.py) (Addressing Gap A in previous plan).
5.  **Scheduler/Daemon**: [scheduler_store.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/scheduler_store.py) and [dm2_daemon_round1](file:///Users/wangwu/codex/agentos-next/docs/journal/DECISIONS_20260225-DM2-DAEMON-019.md) (Addressing Gap C/D).
6.  **UI/App Layer**: [ui1.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/apps/ui1.py) (Addressing Gap D).

## tradeoffs

- **Fail-closed vs User Friction**: Strict rejection on policy mismatch or missing evidence increases "safety" but may break flows if policy configuration is too rigid.
- **Top-level API Stability vs Feature Creep**: Keeping `ExecuteRequest` immutable forces complex logic into `policy_context`, which may become a "dumping ground" for loosely typed extensions.
- **Local-first vs Remote-parity**: Heavy investment in Local Gateway ([CH1](file:///Users/wangwu/codex/agentos-next/docs/journal/DECISIONS_20260225-CH1-LOCAL-GATEWAY-020.md)) ensures privacy but delays robust multi-tenant Remote Sandbox features.

## open_questions

1.  How do we handle "Evidence Truncation" for long-running agents without losing the trust chain?
2.  Is there a clear "Migration Path" when a field in `policy_context` reaches critical mass and needs to be promoted to a top-level `ExecuteRequest` field?

## proposal

### 1. Gap Status Update (Resolved Gaps)
- **Gap A (Memory)**: RESOLVED via `MemoryStore` + `ThreadID` scoping (Ref: [memory_store.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/memory_store.py)).
- **Gap C (Event Triggers)**: RESOLVED via `SchedulerStore` + Daemon mode (Ref: [THREAD-019](file:///Users/wangwu/codex/agentos-next/docs/journal/2026-02-25-expert-collab-thread-019.md)).
- **Gap D (UI/App)**: RESOLVED via `UI1` shell for HITL and Replay visualization (Ref: [THREAD-021](file:///Users/wangwu/codex/agentos-next/docs/journal/2026-02-25-expert-collab-thread-021.md)).

### 2. Top-3 Gaps for "Ship-ready Kernel"

#### Gap #1: Evidence Integrity & Non-Repudiation (The "Evidence Gate" Spike)
- **Bounded Spike**: Implement a signing layer where Evidence blobs are hashed and signed by the Kernel before storage.
- **Kill Criteria**: Latency overhead > 15% on standard file writes; failure to verify 100% of local "Golden Traces".
- **Acceptance**: `python3 -m agentos_next.tools.verify_evidence <trace_id>` returns `verified=true` for all events.

#### Gap #2: Mandatory Resource Budgeting (The "Budget Slice" Spike)
- **Bounded Spike**: Enforce `budget_slice` in `ExecuteRequest` at the `PolicyEngine` level.
- **Kill Criteria**: Inability to estimate budget for standard "Browser Use" skills; deadlock in credit-return flow.
- **Acceptance**: Request with `budget_slice=0` is rejected with `E_BUDGET_EXHAUSTED`.

#### Gap #3: Remote/Local Policy Dual-Acceptance (The "Remote Guardrail" Spike)
- **Bounded Spike**: Ensure `RemoteExecutor` refuses to execute if the remote-derived `policy_context` lacks a kernel-signed "Security Token".
- **Kill Criteria**: Remote execution failure due to clock skew > 5s; protocol mismatch errors > 2% in high-concurrency tests.
- **Acceptance**: A remote tool call without a valid token results in `E_SANDBOX_DENY`.

### 3. Remote/API Boundary Recommendations
- **Immutable**: `workspace_id`, `skill_ref`, `idempotency_key`, `trace` MUST NOT be altered.
- **Stay in `policy_context`**: 
    - `hitl_mode` (human-in-the-loop preference)
    - `sandbox_level` (ephemeral vs persistent)
    - `model_routing_hints` (expert overrides)
- **Upgrade Criteria**: Only promote to `ExecuteRequest` if the field is required for **Routing Decision** (e.g., if any Orchestrator MUST read it to decide local vs remote).

## acceptance

1.  `INPUT_ext_gemini_3_1_kernel_review_round1.md` created with all fields.
2.  File passes `thread_gate_check`.
3.  Top-3 gaps clearly defined with measurable Spike criteria.

## confidence

high
