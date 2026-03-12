# PA 值班速查卡（On-Call Quick Reference）

这份文档只保留最短路径，目标是在 5 分钟内把问题切到正确层级。

## 1. 先判断是哪一层坏了

按顺序看：

1. 终端日志
2. `data/pa/outbox/local/tg_update_<id>.json`
3. `data/traces/tr_pa_tg_update_<id>.jsonl`
4. `data/pa/polling_offsets/*.json`

结论规则：

- 没有 `Received Telegram Update`
  - 入站层问题。
- 有 update，没有 outbox
  - 执行层问题。
- 有 outbox，用户没收到
  - Telegram 出站层问题。
- outbox 里是 `E_PROVIDER_BAD_RESPONSE`
  - provider 层问题。

## 2. 高频症状速查

### 2.1 收到 update，但没回复

看：

- 终端是否有 `Reply sent` / `Reply streamed` / `Reply send failed`
- outbox 是否存在

快速判断：

- 无 outbox：查 canonical runtime / trace
- 有 outbox 无发送：查 TelegramReplyAdapter
- `reply_sent_live=true`：说明走过流式链，不应再期待 polling 直发

### 2.2 重启后又处理旧消息

看：

- 启动日志是否有 `Resuming from persisted offset: ...`
- `data/pa/polling_offsets/*.json`

结论：

- 没有 checkpoint：高概率是旧消息回放
- 有 checkpoint 但仍回放：先排查是否传了旧 `--offset`

### 2.3 用户看到“远端模型服务返回异常”

看：

- outbox 的 `execute_error_code`
- 日志里的 `detail=...`

快速归因：

- `status=429`：额度问题
- `401/403`：token 或权限问题
- `SSL: UNEXPECTED_EOF_WHILE_READING`：瞬态 TLS EOF

### 2.4 流式很卡或最后超时

先区分：

- 开始晚：更可能是 provider 首字慢或 reply 可见点太晚
- 开始后逐字蹦：更可能是展示层刷新过碎
- 越流越卡最后超时：优先怀疑 Telegram 编辑阻塞 provider 流读取

看：

- trace
- `telegram_reply.py`
- `openai_codex_oauth.py`

## 3. 值班最常用文件

| 文件 | 用途 |
| --- | --- |
| [pa_polling_service.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/pa_polling_service.py) | 看 offset、polling、出站收口 |
| [telegram_reply.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/telegram_reply.py) | 看 typing、流式、Telegram 出站 |
| [query_gated_runtime.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/query_gated_runtime.py) | 看 Query Compile、capability gate、research/doctrine 选择 |
| [assistant_loop.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/assistant_loop.py) | 看 assistant loop、verification、evidence/outbox 前收口 |
| [backend.py](/Users/wangwu/codex/agentos-next/src/agentos_next/llm/backend.py) | 看 provider 错误包装 |
| [openai_codex_oauth.py](/Users/wangwu/codex/agentos-next/src/agentos_next/llm/openai_codex_oauth.py) | 看 Codex OAuth、SSE、transport retry |

## 4. 不要一上来就做的事

- 不要先改 prompt。
- 不要先改 Telegram。
- 不要把 provider 错误误判成 PA 主流程错误。
- 不要忽略 `offset` 与历史回放。

## 5. 需要深入时再看

- [PA 排障手册](/Users/wangwu/codex/agentos-next/docs/guides/PA_TROUBLESHOOTING_RUNBOOK.md)
- [PA 架构总览](/Users/wangwu/codex/agentos-next/docs/guides/PA_ARCHITECTURE_OVERVIEW.md)
- [PA 修复经验](/Users/wangwu/codex/agentos-next/docs/guides/PA_REPAIR_NOTES_2026Q1.md)
