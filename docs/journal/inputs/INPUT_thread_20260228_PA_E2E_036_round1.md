id: `20260228-pa-e2e-036-round1`
author: `gpt5_2`
topic: `THREAD-036 PA end-to-end chain test`
position: `Verify webhook->envelope->EV1->outbox->metering and dedup/replay invariants without adding features`
evidence: `tests/test_thread036_pa_e2e_chain.py; docs/specs/PA_EVENT_ENVELOPE_V0.md; src/agentos_next/apps/telegram_connector.py; src/agentos_next/pa/ev1_runtime.py`
tradeoffs: `Pros: catches interface drift early; Cons: tests are integration-ish and can be brittle if contracts drift (which is desired to detect)`
open_questions: `none`
proposal: `Add a single e2e test module that uses fixtures and the real CH1 adapter to feed EV1`
acceptance: `PYTHONPATH=src python3 -m unittest discover -s tests -v -p 'test_thread036_pa_e2e_chain.py'`
confidence: `high`

