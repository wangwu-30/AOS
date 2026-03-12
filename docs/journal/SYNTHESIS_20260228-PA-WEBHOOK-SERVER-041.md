# SYNTHESIS_20260228-PA-WEBHOOK-SERVER-041

- `thread_id`: `20260228-PA-WEBHOOK-SERVER-041`

## Topic

PA loopback webhook 服务化：将 THREAD-034/033/035 的链路落到可运行 HTTP 入口。

## Resolution

- 增加 `mvp pa-webhook-server` 命令，处理 `POST /v1/telegram/webhook`。
- 服务链路固定：`TelegramChannelAdapter -> EV1Runtime -> Outbox -> TelegramReplyAdapter`。
- 支持路由文件将 conversation/chat 映射到 `workspace_id` 与预算。
- 支持 THREAD-043 参数透传（`memory_context_*`）到 EV1。

## Key Behaviors

- host 非 loopback：拒绝并返回 `E_INPUT_SCHEMA`。
- replay-mode：返回 `E_PA_EV_REPLAY_DENY` 且 zero-write。
- memory_context 启用但 C0/C1 无效：fail-closed 返回 `E_PA_EV_CONTEXT_FAILED`。
