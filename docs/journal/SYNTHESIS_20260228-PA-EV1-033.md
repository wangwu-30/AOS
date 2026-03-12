# SYNTHESIS: THREAD-033 PA-EV1（EventEnvelope/EventLog/Outbox/Dedup）

- `thread_id`: `20260228-PA-EV1-033`
- `updated_at`: `2026-02-28`
- `status`: `resolved`

## Summary

THREAD-033 以 EventEnvelope v0 为输入，提供最小“事件 -> 执行 -> outbox”闭环，满足：

- dedup：以 `event_id` 为主键，outbox existence short-circuit，禁止二次执行
- replay-mode：严格 zero-write，返回稳定拒绝错误码
- 不扩张 ExecuteRequest 顶层字段；只是在 app 层构造 ExecuteRequest 调用 Kernel

## Key Decisions

- EventEnvelope v0 共享真相源：`docs/specs/PA_EVENT_ENVELOPE_V0.md`
- EV1 错误码集合冻结为 3 个（避免扩散）
- outbox 与 dedup marker 落盘路径：`pa/outbox` / `pa/dedup`
