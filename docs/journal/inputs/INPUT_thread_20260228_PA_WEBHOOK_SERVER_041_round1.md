id: `20260228-pa-webhook-server-041-round1`
author: `gpt5_3`
topic: `THREAD-041 PA webhook server loopback ingress`
position:
- Add `mvp pa-webhook-server` as loopback-only ingress service for Telegram webhook to drive PA runtime.
- Keep execution governance in Kernel/EV1; service layer only routes/parses and returns stable JSON.
- Integrate THREAD-043 memory context parameters so webhook ingress can enable context engineering path.
evidence:
- docs/specs/MVP_041_PA_WEBHOOK_SERVER.md
- src/agentos_next/apps/pa_webhook_server.py
- src/agentos_next/cli.py
- tests/test_thread041_pa_webhook_server.py
tradeoffs:
- Pros: converts fixture/demo chain into runnable local service with deterministic tests.
- Cons: still loopback-only and stub-first; public deployment hardening remains out-of-scope.
open_questions: `none`
proposal:
- Freeze loopback-only host policy, fail-closed error contract, replay zero-write, and MEM1 fail-closed behavior in one thread.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest tests/test_thread041_pa_webhook_server.py -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check --thread-id 20260228-PA-WEBHOOK-SERVER-041`
confidence: `high`
