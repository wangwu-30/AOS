id: `20260228-pa-mtr0-035-round1`
author: `gpt5_2`
topic: `THREAD-035 metering evidence v0`
position: `Write metering evidence (snapshot/type=metering_v0) on outbox write; include trace_id/turn_id/event_id/workspace_id; replay-mode zero-write`
evidence: `src/agentos_next/pa/metering.py; src/agentos_next/pa/ev1_runtime.py; tests/test_thread035_pa_mtr0_metering_evidence.py`
tradeoffs: `Pros: auditable usage chain without billing; Cons: does not compute tokens/cost, only records`
open_questions: `none`
proposal: `Hook metering evidence emission at EV1 outbox write; keep schema stable and replayable`
acceptance: `PYTHONPATH=src python3 -m unittest discover -s tests -v -p 'test_thread035_pa_mtr0_metering_evidence.py'`
confidence: `high`
