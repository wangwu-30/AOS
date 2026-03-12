# PA 日志字段说明（Log Field Reference）

本文解释 Telegram PA 当前最常见的终端日志行、关键字段与推荐解读方式。目标不是穷举所有日志，而是覆盖值班和本地排障最常用的那部分。

## 1. 使用方式

看日志时，不要孤立看某一行。建议按这个顺序联读：

1. `Received Telegram Update`
2. `Reply sent` / `Reply streamed` / `Reply send failed`
3. `Offset checkpoint saved`
4. `error_code` / `error_detail`
5. `data/pa/outbox/local/<event_id>.json`

## 2. 入站相关日志

### 2.1 收到 Telegram 更新

示例：

```text
--- [PA] Received Telegram Update id=299891373 ---
```

含义：

- polling 已经成功从 Telegram `getUpdates` 拉到一条 update。
- 这里的 `id` 是 Telegram `update_id`，不是内部 trace id。

排障意义：

- 有这行，说明“完全没收到消息”不是当前问题。
- 没有这行，优先检查 polling/webhook 入站，而不是 canonical runtime、provider 或 Telegram 出站。

字段：

| 字段 | 含义 |
| --- | --- |
| `id` | Telegram `update_id` |

### 2.2 polling 错误返回

示例：

```json
{"error_code": "E_PA_POLLING_FAILED", "error_detail": "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)>", "next_offset": 299891318, "ok": false}
```

含义：

- polling 这一轮没成功完成。
- `next_offset` 表示当前准备继续尝试的位置，不代表本轮已成功消费。

字段：

| 字段 | 含义 |
| --- | --- |
| `error_code` | polling 层稳定错误码 |
| `error_detail` | 原始或压缩后的失败摘要 |
| `next_offset` | 下一轮继续尝试的 offset |
| `ok` | 本轮是否成功 |

高频判断：

- `UNEXPECTED_EOF_WHILE_READING`
  - 瞬态网络错误，不一定是逻辑 bug。
- `Remote end closed connection without response`
  - 同样偏向网络层瞬态失败。

## 3. offset 相关日志

### 3.1 断点续跑

示例：

```text
Resuming from persisted offset: 299891322
```

含义：

- 当前进程启动时，没有显式传 `--offset`，而是从持久化检查点续跑。

排障意义：

- 看见这行，说明旧消息重放风险下降。
- 看不见这行，不一定有问题，但要继续确认是不是显式传了 `--offset`。

### 3.2 offset 保存

示例：

```text
[PA] Offset checkpoint saved: next_offset=299891374
```

含义：

- 这一轮处理完成后，新的 `next_offset` 已写入持久化存储。

字段：

| 字段 | 含义 |
| --- | --- |
| `next_offset` | 下次 polling 默认续跑位置 |

判断规则：

- 同一个 `next_offset` 重复出现过去是噪音；当前实现中，未变化时不应重复打印。

## 4. 回复相关日志

### 4.1 直发成功

示例：

```text
[PA] Reply sent for update 299891380: execute_status=accepted
```

含义：

- 已通过 Outbox 直发链把消息发给 Telegram。

字段：

| 字段 | 含义 |
| --- | --- |
| `update 299891380` | 对应的 Telegram `update_id` |
| `execute_status` | 本轮底层执行状态 |

常见 `execute_status`：

- `accepted`
- `failed`
- `timeout`
- `rejected`
- `canceled`

注意：

- 即使 `execute_status=failed`，只要已经生成合法 OutboxItem，也可能出现 `Reply sent`，因为这是失败兜底回复。

### 4.2 流式成功

示例：

```text
[PA] Reply streamed for update 299891373: execute_status=failed; execute_error_code=E_PROVIDER_BAD_RESPONSE; detail=E_PROVIDER_BAD_RESPONSE; provider transport error: transport error: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)>
```

含义：

- 这轮对用户可见的回复，是通过 Telegram 流式链发出的，而不是 Outbox 直发。
- 后面的状态摘要是本轮执行收口结果，不代表“没给用户回”。

字段：

| 字段 | 含义 |
| --- | --- |
| `update ...` | 对应 Telegram `update_id` |
| `execute_status` | 底层执行收口状态 |
| `execute_error_code` | 执行错误码 |
| `detail` | 紧凑诊断细节，通常来自 evidence |

判断规则：

- `Reply streamed ... execute_status=failed`
  - 含义通常是“用户收到了失败兜底，但执行本身失败了”。
- 不应把它误读成“完全没回复”。

### 4.3 出站失败

示例：

```text
[PA] Reply send failed for update 299891380: execute_status=failed; execute_error_code=E_PROVIDER_BAD_RESPONSE; telegram=HTTP 400 Bad Request
```

含义：

- canonical runtime 已产出 outbox，但 Telegram 发送失败。

字段：

| 字段 | 含义 |
| --- | --- |
| `execute_status` | 底层执行状态 |
| `execute_error_code` | 若存在，为执行错误码 |
| `telegram` | Telegram 出站错误摘要 |

排障优先级：

- 看到这行，先查 TelegramReplyAdapter，不要先查 provider。

## 5. provider 相关日志字段

### 5.1 `E_PROVIDER_BAD_RESPONSE`

含义：

- LLM provider 返回了不可接受的结果。
- 这只是稳定错误码，真正根因要看 detail。

常见 detail 形式：

| detail 片段 | 含义 |
| --- | --- |
| `status=429` | 配额/额度问题 |
| `usage_limit_reached` | 额度已达上限 |
| `status=401` / `status=403` | token、授权或权限问题 |
| `transport error: ... EOF ...` | 瞬态 TLS/连接错误 |
| `body_preview=...` | provider 返回了可读错误体，可继续按 body 诊断 |

### 5.2 `E_TIMEOUT`

含义：

- 执行 deadline 命中。
- 这通常来自 Orchestrator 或 LocalExecutor，而不是 Telegram。

不要误判：

- 用户看到超时，不代表 Telegram 发不出去。
- 先区分“执行超时”还是“出站失败”。

## 6. Telegram adapter 相关日志

### 6.1 通用 Telegram 错误

示例：

```text
[Telegram] Telegram outbound send failed: HTTP 400
```

或：

```text
[Telegram] Telegram outbound send failed: network-down
```

含义：

- Telegram Reply Adapter 的底层发送失败。

排障意义：

- 说明问题已经落到出站层。
- 这类错误通常应与 `Reply send failed ...` 联读。

## 7. 如何从一行日志快速判断层级

| 日志特征 | 优先层级 |
| --- | --- |
| 没有 `Received Telegram Update` | 入站层 |
| 有 update，无 outbox | 执行层 |
| `Reply send failed` | Telegram 出站层 |
| `E_PROVIDER_BAD_RESPONSE` | provider 层 |
| `E_TIMEOUT` | 执行 deadline / 长任务层 |
| `Offset checkpoint saved` 异常重复 | offset / 日志噪音层 |

## 8. 建议联查文件

- [PA 值班速查卡](/Users/wangwu/codex/agentos-next/docs/guides/PA_ONCALL_QUICK_REFERENCE.md)
- [PA 排障手册](/Users/wangwu/codex/agentos-next/docs/guides/PA_TROUBLESHOOTING_RUNBOOK.md)
- [PA 架构总览](/Users/wangwu/codex/agentos-next/docs/guides/PA_ARCHITECTURE_OVERVIEW.md)
- [pa_polling_service.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/pa_polling_service.py)
- [telegram_reply.py](/Users/wangwu/codex/agentos-next/src/agentos_next/apps/telegram_reply.py)
- [openai_codex_oauth.py](/Users/wangwu/codex/agentos-next/src/agentos_next/llm/openai_codex_oauth.py)
