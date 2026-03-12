id: `20260228-pa-polling-044-round1`
author: `gpt5_3`
topic: `THREAD-044 local polling mode for PA`
position:
- Add local polling entry (`mvp pa-polling`) so PA can run without public webhook.
- Reuse existing CH1/EV1/reply components to keep semantics aligned and reduce drift risk.
- Preserve THREAD-043 memory-context options on polling path.
evidence:
- docs/specs/MVP_044_PA_POLLING_MODE.md
- src/agentos_next/apps/pa_polling_service.py
- src/agentos_next/cli.py
- tests/test_thread044_pa_polling.py
tradeoffs:
- Pros: no公网回调依赖，快速本地可用。
- Cons: polling 会引入周期性请求，不是 push 模式。
open_questions: `none`
proposal:
- Freeze polling as additive app command with stable JSON output and fail-closed semantics.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest tests/test_thread044_pa_polling.py -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check --thread-id 20260228-PA-POLLING-044`
confidence: `high`
