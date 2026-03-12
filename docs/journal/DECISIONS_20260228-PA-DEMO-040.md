# DECISIONS_20260228-PA-DEMO-040

- `thread_id`: `20260228-PA-DEMO-040`

## Frozen Decisions
1. **top_level_api_stable**: No ExecuteRequest field changes.
2. **fail_closed**: Missing event log entry -> adapter returns False, no reply sent.
3. **replay_mode_no_side_effects**: Adapter is never invoked in replay path.
4. **Pluggable send**: Default stub prints to stdout; real HTTP injected via send_func.

## Acceptance Commands
- `PYTHONPATH=src python3 -m unittest tests/test_thread040_telegram_reply.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_thread040_pa_demo_visible_roundtrip.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
