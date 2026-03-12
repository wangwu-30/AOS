id: `20260228-pa-demo-040-round1`
author: `gpt5_2`
topic: `THREAD-040 visible PA roundtrip (Telegram webhook -> outbox -> reply stub)`
position:
- Add a minimal CLI demo (`mvp pa-demo`) that drives the already-accepted CH1/EV1/MTR0 chain and invokes the THREAD-040 TelegramReplyAdapter stub, so a developer can see an end-to-end message roundtrip in one command.
- Add an automated "visible roundtrip" test to prevent contract drift across 033/034/035/040.
evidence:
- src/agentos_next/cli.py
- src/agentos_next/apps/telegram_connector.py
- src/agentos_next/apps/telegram_reply.py
- src/agentos_next/pa/ev1_runtime.py
- tests/test_thread040_pa_demo_visible_roundtrip.py
- docs/specs/PA_EVENT_ENVELOPE_V0.md
tradeoffs:
- Pros: converts the PA chain into a developer-visible loop (message in -> reply out) without network side effects; keeps replay/idem semantics unchanged.
- Cons: the reply send is stubbed (stdout) by default; real Telegram send remains out-of-scope for this thread.
open_questions: `none`
proposal:
- Implement `mvp pa-demo` that reads a Telegram webhook JSON payload, runs EV1 to write outbox + metering, then uses TelegramReplyAdapter (stub) to emit a visible outbound send.
- Add `tests/test_thread040_pa_demo_visible_roundtrip.py` to lock the roundtrip behavior.
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest tests/test_thread040_pa_demo_visible_roundtrip.py -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
confidence: `high`

