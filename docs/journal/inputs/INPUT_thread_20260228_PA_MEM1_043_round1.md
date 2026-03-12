id: `20260228-pa-mem1-043-round1`
author: `gpt5_3`
topic: `THREAD-043 PA-MEM1 progressive context pipeline`
position:
- Add app-level memory context compilation before EV1 execute using THREAD-032 context compiler.
- Inject compiled context into policy_context["memory_context"] only, without changing ExecuteRequest top-level fields.
evidence:
- docs/specs/MVP_043_PA_MEM1_CONTEXT_PIPELINE.md
- src/agentos_next/pa/memory_pipeline.py
- src/agentos_next/pa/ev1_runtime.py
- tests/test_thread043_pa_mem1_pipeline.py
tradeoffs:
- Pros: aligns with context-engineering architecture, keeps kernel API stable, and preserves fail-closed boundaries.
- Cons: additional compile step adds overhead and may fail if identity/capability refs are misconfigured.
open_questions: `none`
proposal:
- Land PA-MEM1 as opt-in (`memory_context_enabled=false` by default) and validate with dedicated tests plus full regression.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest tests/test_thread043_pa_mem1_pipeline.py -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
confidence: `high`
