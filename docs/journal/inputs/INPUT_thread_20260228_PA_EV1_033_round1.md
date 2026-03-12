id: `20260228-pa-ev1-033-round1`
author: `gpt5_2`
topic: `THREAD-033 PA-EV1 minimal runtime`
position: `EventEnvelope v0 -> write-once eventlog -> kernel execute -> write-once outbox; dedup by event_id; replay-mode strict deny`
evidence: `docs/specs/PA_EVENT_ENVELOPE_V0.md; src/agentos_next/pa/ev1_runtime.py; src/agentos_next/pa/event_log.py; src/agentos_next/pa/outbox_store.py; tests/test_thread033_pa_ev1_runtime.py`
tradeoffs: `Pros: fastest IM loop reuse, deterministic replay, minimal new surface; Cons: single skill_ref routing, no streaming, no multi-channel yet`
open_questions: `none`
proposal: `Implement EV1Runtime with strict schema validation (event_id/idempotency_key REQUIRED), outbox existence short-circuit, replay-mode zero-write deny`
acceptance: `PYTHONPATH=src python3 -m unittest discover -s tests -v -p 'test_thread033_pa_ev1_runtime.py'`
confidence: `high`
