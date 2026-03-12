# SYNTHESIS: THREAD-035 PA-MTR0（Metering Evidence v0）

- `thread_id`: `20260228-PA-MTR0-035`
- `updated_at`: `2026-02-28`
- `status`: `resolved`

## Summary

THREAD-035 定义并实现最小 metering evidence v0：

- 仅做 evidence（kind=snapshot，payload.type=metering_v0），不做计费
- 必须包含 trace_id/turn_id/event_id/workspace_id，支持回放审计
- replay-mode 下严格 zero-write
