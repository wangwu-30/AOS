id: `20260228-pa-e2e-036-round2-cross-review`
author: `gpt5_2`
topic: `THREAD-036 cross review`
position: `Confirm thread strictly tests frozen contracts: envelope required fields, budget fallback rule, dedup by event_id, replay-mode double zero side effects`
evidence: `docs/journal/DECISIONS_20260228-PA-E2E-036.md; tests/test_thread036_pa_e2e_chain.py`
tradeoffs: `Strict replay test (patch mkdir) reduces false confidence about zero-write; may require occasional refactors if lower layers change`
open_questions: `none`
proposal: `Ship THREAD-036 as acceptance gate before adding TG1/MEM1`
acceptance: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

