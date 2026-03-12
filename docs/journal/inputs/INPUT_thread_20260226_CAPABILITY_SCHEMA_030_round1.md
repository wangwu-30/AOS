id: `input-20260226-capability-schema-030-round1-ext_gpt5_2-001`
author: `ext_gpt5_2`
topic: `THREAD-030 Capability Schema v1 (policy_context.capabilities[])`
position:
- Enforce explicit capability handles in Kernel PEP (default deny for privileged operations).
- Represent capabilities as `policy_context.capabilities[]` with machine-checkable schema (name/scope/constraints?).
- Keep high-risk approval path unchanged: reuse `E_HITL_REQUIRED` (no new synonym codes).
evidence:
- `src/agentos_next/kernel/capabilities.py`
- `src/agentos_next/kernel/policy_engine.py`
- `tests/test_thread030_capability_schema.py`
- Command: `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` (112/112 OK)
tradeoffs:
- Pro: least-privilege by construction; callers must declare intent; deny reasons are auditable via policy evidence.
- Con: requires updating call sites/tests to attach capabilities; missing capability becomes a new class of rejection (`E_CAPABILITY_DENY`).
open_questions:
- Should we introduce per-skill scoped capabilities (scope=skill) in P1 for tighter confinement? (out of v1)
proposal:
- v1 required capability mapping (frozen):
  - `builtin://memory.{write,delete,compact}` => `memory_write`
  - `builtin://scheduler.{at,cron}` => `scheduler_write`
  - `allow_network_egress=true` => `net_egress`
  - `remote_calls_armed=true` or `backend=codex_oauth` => `llm_remote`
- Keep capability names restricted to allowlist (fail-closed on unknown).
acceptance:
- `tests/test_thread030_capability_schema.py` passes.
- Missing/invalid capabilities must be rejected with stable error_code:
  - missing => `E_CAPABILITY_DENY`
  - invalid schema => `E_CAPABILITY_SCHEMA_INVALID`
confidence: `high`

