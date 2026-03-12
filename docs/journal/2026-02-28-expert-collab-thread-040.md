# THREAD-040: Telegram Reply Adapter (PA Demo E2E)

- `thread_id`: `20260228-PA-DEMO-040`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `ext_gemini_3_1`

## Goal
Provide the outbound "message out" half of the Telegram PA demo loop: read OutboxItem -> look up original EventEnvelope -> send reply to correct chat_id.

## Boundary
- Does NOT expand ExecuteRequest top-level fields.
- Does NOT alter Envelope v0 semantics.
- Replay mode: zero side-effects (outbound adapter is never invoked in replay).
- No new external dependencies (stdlib only).
- Outbox management remains PA-EV1's responsibility; this adapter is read-only consumer.

## Acceptance
- `PYTHONPATH=src python3 -m unittest tests/test_thread040_telegram_reply.py -v` -> OK
- `PYTHONPATH=src python3 -m unittest tests/test_thread040_pa_demo_visible_roundtrip.py -v` -> OK
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> OK
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` -> ok=true

## Rounds
- Round 0 (Scope): Host tasked reply adapter + E2E driver.
- Round 1 (Proposals): ext_gemini_3_1 submitted code.
- Round 2 (Review): Pending host review.
- Round 3 (Synthesis): Pending.
- Round 4 (Decision): Pending.

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_DEMO_040_round2_cross_review.md`

## Round 1 Input (Added)

- `docs/journal/inputs/INPUT_thread_20260228_PA_DEMO_040_round1.md`
