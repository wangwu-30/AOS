id: `20260228-pa-tg1-042-round1`
author: `gpt5_2`
topic: `THREAD-042 PA TaskGraph (TG1) minimal mechanism`
position:
- Add a file-backed TaskGraph primitive (queued/running/succeeded/failed) with crash recovery helper (running->queued) and fingerprint-based cycle detection.
- Integrate minimally into EV1 so each inbound event produces a recoverable root task record.
evidence:
- docs/specs/MVP_042_PA_TASK_GRAPH.md
- src/agentos_next/pa/task_graph.py
- src/agentos_next/pa/ev1_runtime.py
- tests/test_thread042_pa_task_graph.py
tradeoffs:
- Pros: provides a recoverable substrate for dynamic task decomposition without requiring LLM planning; keeps kernel API stable.
- Cons: v1 is single-writer local store; no distributed concurrency or rich task scheduling.
open_questions: `none`
proposal:
- Land TaskGraph store + cycle guard + recovery helper + EV1 root integration, gated by THREAD-042 tests and thread_gate_check.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest tests/test_thread042_pa_task_graph.py -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
confidence: `high`

