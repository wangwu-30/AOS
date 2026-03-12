id: `20260228-pa-mtr0-035-round2-cross-review`
author: `gpt5_2`
topic: `THREAD-035 cross review`
position: `Confirm metering evidence is evidence-only (no billing), includes trace_id/turn_id, and is suppressed in replay-mode`
evidence: `docs/journal/DECISIONS_20260228-PA-MTR0-035.md; src/agentos_next/pa/metering.py; tests/test_thread035_pa_mtr0_metering_evidence.py`
tradeoffs: `Keeping metering minimal avoids cost-model debates; later billing can consume evidence chain`
open_questions: `none`
proposal: `Ship MTR0 v0 now, keep token accounting for P1`
acceptance: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

