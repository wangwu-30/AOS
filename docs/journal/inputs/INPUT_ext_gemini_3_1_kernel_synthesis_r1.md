# [INPUT] Round-1 Synthesis Response by ext_gemini_3_1

- **id**: 20260226-SYNTHESIS-R1-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Response to bus-kernel-research-synthesis-r1-001
- **position**: Support Capability-first and Token-based Resource Tree as P0 MUST. Strongly advocate for Evidence Integrity as the prerequisite for all governance.

## evidence
1.  **Architecture**: Current `ExecuteRequest` already uses `policy_context`, making it the natural extension point for Capabilities.
2.  **Research**: *deep-research-report.md* (Line 51/140) and *deep-research-report (1).md* (Line 9/174) both confirm Capability-based security as the prime factor for system scaling.
3.  **Baseline**: `unittest` (105/105) passing ensures we have a stable base for these P0 additions.

## tradeoffs
- **Capability Granularity**: Too fine-grained (per-file) increases latency; too coarse (per-directory) increases risk. Suggest "Namespace-scoped" handles.
- **Enforcement Overhead**: Real-time token tracking in the `PolicyEngine` must be non-blocking to avoid UX lag in streaming chat.

## open_questions
- If `tokens` is the only resource in V1, how do we handle non-LLM tool costs (e.g., search API credits)?
- Does the "Controller Loop" require a separate long-running daemon process or can it remain reactive within the Orchestrator?

## proposal

### A. Priority Mapping (5 Points)
- **P0**: Capability-first, Resource Tree (Tokens), Kernel Neutrality (Platform-first).
- **P1**: Layered Isolation (Container/microVM).
- **P2**: Declarative Control Loop (Move from reactive to proactive).

### B. Isolation Strategy
- **AGREE**: Container as default baseline (cgroups/namespaces/seccomp). 
- **UPGRADE**: Use microVM (Firecracker) ONLY for "High-Risk" skills (e.g., unverified 3rd-party code execution or arbitrary network access).

### C. Capability Model
- **FEASIBLE**: Use `policy_context` to pass "Capability Handles" (e.g., UUIDs mapping to kernel-side permission objects). 
- **INVARIANT**: The Orchestrator MUST be the only entity that can resolve a handle to a real resource (Skill/Data).

### D. Resource Tree Minimal Fields
- **V1 (P0)**: `tokens`.
- **V2 (P1)**: `cpu_ms`, `mem_bytes`, `network_mb`.

### E. Single Spike Priority
- **PRIORITY**: **Evidence Integrity (Signature)**. 
- **Justification**: Without tamper-proof evidence, any capability or budget enforcer can be bypassed or falsified in the trace record. It is the "Root of Trust".

## acceptance
- Proposal integrated into `MVP_0XX_KERNEL_GOVERNANCE_BASELINE.md`.
- Spike for Evidence Signing results in 0% bypass in local manipulation tests.

## confidence
high
