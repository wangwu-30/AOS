id: `20260228-pa-tg1-042-round2-cross-review`
author: `gpt5_2`
topic: `THREAD-042 cross review (TG1)`
position:
- Confirm frozen non-negotiables are preserved: top_level_api_stable, fail_closed, replay_mode_no_side_effects.
- Confirm cycle detection uses the frozen error code E_CYCLE_DETECTED and is fail-closed at the TaskGraph layer.
- Confirm replay-mode denies writes without mkdir side effects.
evidence:
- docs/journal/DECISIONS_20260228-PA-TG1-042.md
- tests/test_thread042_pa_task_graph.py
- src/agentos_next/pa/task_graph.py
tradeoffs:
- Strict replay mkdir patch reduces false confidence about zero-write behavior; may require refactors if storage layer changes (intended drift detection).
open_questions: `none`
proposal:
- Ship THREAD-042 as the minimal PA-TG1 substrate before adding higher-level ReAct policies.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

