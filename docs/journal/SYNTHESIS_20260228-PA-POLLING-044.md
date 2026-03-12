# SYNTHESIS_20260228-PA-POLLING-044

- `thread_id`: `20260228-PA-POLLING-044`

## Topic

PA 本地轮询入口（polling mode）用于替代 webhook 公网依赖。

## Resolution

- 增加 `mvp pa-polling` 命令，调用 Telegram `getUpdates`。
- 每条 update 复用 PA-CH1 解析与 EV1 执行链路。
- 维持 outbox + reply + dedup 语义一致。
- 保持 THREAD-043 的 `memory_context_*` 入口参数。

## Key Behaviors

- `--bot-token` 必填；缺失返回 `E_INPUT_SCHEMA`。
- 同一 update 重放命中 dedup，不重复 reply。
- replay-mode 严格零副作用。
