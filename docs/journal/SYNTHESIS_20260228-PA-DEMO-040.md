# SYNTHESIS_20260228-PA-DEMO-040

- `thread_id`: `20260228-PA-DEMO-040`

## Topic
Telegram outbound reply adapter for PA Demo end-to-end visibility.

## Resolution
- TelegramReplyAdapter reads OutboxItem + original EventEnvelope to extract conversation_id.
- Supports pluggable send_func (real HTTP or stub for dev/test).
- Demo driver wires CH1 inbound -> EV1 -> Outbox -> Reply outbound in one command (`mvp pa-demo`).

## Demo Command (One-Liner)

- `cd agentos-next && PYTHONPATH=src python3 -m agentos_next.cli mvp pa-demo --data-dir /tmp/agentos_next_pa_demo/data --workspace-id local --expected-secret-token demo-secret --secret-token demo-secret`
  - Uses the sample webhook payload: `examples/fixtures/telegram_webhook_sample.json`
