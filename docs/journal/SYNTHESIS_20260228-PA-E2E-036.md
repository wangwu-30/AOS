# SYNTHESIS: THREAD-036 PA E2E（033+034+035）

- `thread_id`: `20260228-PA-E2E-036`
- `updated_at`: `2026-02-28`
- `status`: `resolved`

## Summary

THREAD-036 通过单测将 CH1/EV1/MTR0 串联：

- webhook fixture -> TelegramChannelAdapter 产出 envelope（或 replay-mode 下不 dispatch）
- EV1 执行并落 outbox + metering evidence
- same update_id => dedup short-circuit
- replay-mode 双零副作用（CH1 不 dispatch，EV1 strict deny zero-write）
