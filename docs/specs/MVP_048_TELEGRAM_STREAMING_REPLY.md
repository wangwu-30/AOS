# MVP_048_TELEGRAM_STREAMING_REPLY

- 状态（Status）：Draft
- 日期（Date）：2026-03-07
- 目标版本（Target）：MVP_048
- 相关规范（Related Specs）：
  - `docs/specs/MVP_044_PA_POLLING_MODE.md`
  - `docs/specs/MVP_041_PA_WEBHOOK_SERVER.md`
  - `docs/specs/LLM_PROVIDER.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`

## 目的（Purpose）

定义 Telegram 流式回复（Streaming Reply）的最小运行时契约，使 PA 在支持增量输出的 LLM provider 上，可以先发占位消息，再通过 `editMessageText` 持续刷新回复，同时避免最终 outbox 重复发送。

## 范围（Scope）

本规范覆盖：
- Provider 增量事件如何传递到 Telegram 回复适配器。
- Telegram 占位消息、增量编辑、最终收口的最小语义。
- Telegram 输入中期间的输入中指示（Typing Heartbeat）语义。
- 无 `reply` 时的工具/阶段进度流，以及 `reply` 出现后的覆盖优先级。
- `reply_sent_live` 与 `reply_delivery_mode` 的 outbox 语义。
- 错误处理、边界条件、兼容策略、测试与验收。

本规范不覆盖：
- Telegram 客户端 UI 展示差异。
- 非 Telegram 渠道的流式回复协议。
- 模型内部推理流的展示。

## 接口/数据结构（Interfaces/Data）

### LLM Stream Event（MUST）

运行时必须（MUST）支持以下最小事件：

```json
{"type":"start"}
{"type":"delta","delta":"string"}
{"type":"completed"}
```

约束（MUST）：
- `delta` 必须（MUST）表示模型输出文本的增量片段。
- provider 可以（MAY）补充额外字段，但不得（MUST NOT）破坏上述最小字段。

### OutboxItem 扩展字段（MUST）

```json
{
  "reply_sent_live": true,
  "reply_delivery_mode": "telegram_stream"
}
```

默认值（MUST）：
- `reply_sent_live = false`
- `reply_delivery_mode = null`

### Telegram 流式节流默认值（MUST）

默认值（MUST）：
- 输入中指示（Typing Heartbeat）间隔默认值为 `4.0s`
- reply 模式最小刷新间隔默认值为 `0.30s`
- reply 模式最小字符增量默认值为 `12`
- 首个 reply 分块最小字符数默认值为 `8`
- 首个 reply 分块最大等待时间默认值为 `0.35s`
- 首个 reply 分块缓冲 chunk 数默认值为 `3`
- 持续 reply 分块缓冲 chunk 数默认值为 `2`

## 语义（Semantics）

### 启动流式回复（MUST）

- 当满足以下条件时，PA 应该（SHOULD）启动 Telegram 流式回复：
  - 当前渠道为 Telegram
  - 当前 backend 支持增量输出
  - 当前 reply adapter 可用
- 启动时必须（MUST）先发送一条占位消息。
- 启动处理后，运行时必须（MUST）发送并维持输入中指示（Typing Heartbeat），直到本轮回复完成或失败收口。

### 增量编辑（MUST）

- 占位消息发送成功后，运行时必须（MUST）使用 `editMessageText` 编辑同一条消息，而不是不断发送新消息。
- 增量编辑必须（MUST）以用户可见 `reply` 文本为目标，不得把原始 JSON、工具输出或内部推理直接暴露给用户。
- 当 provider 仅能提供 JSON 文本流时，运行时可以（MAY）通过部分解析提取 `reply` 字段进行增量展示。
- reply 模式必须（MUST）使用独立于进度消息的低延迟节流，不得沿用较慢的进度刷新节流。
- 运行时应该（SHOULD）在本地缓冲多个增量 chunk 后再刷新 Telegram，以避免用户感知到逐字抖动式更新。
- 首个 `reply` 片段一旦可见，运行时必须（MUST）在本地缓冲阈值或最大等待时间满足后立即刷新到 Telegram，不得被额外的常规节流窗口继续延后。
- 对要求 JSON 输出的技能，运行时应该（SHOULD）通过 prompt 约束模型以 `reply` 作为首个键开始输出，并默认省略非必需的可选字段，以降低首个可见回复延迟。

### 进度优先级（MUST）

- 当尚未解析出任何 `reply` 片段时，运行时可以（MAY）流式展示工具执行进度或阶段进度。
- 一旦解析出首个 `reply` 片段，运行时必须（MUST）切换到 `reply` 模式。
- 进入 `reply` 模式后，后续进度更新不得（MUST NOT）覆盖已经开始展示的 `reply`。

### 最终收口（MUST）

- 最终结果生成后，运行时必须（MUST）将最终显式 `send_message` 交付文本刷新到同一条 Telegram 消息，或在不支持编辑时退化为一条新的最终消息。
- 若流式发送已成功完成，outbox 必须（MUST）写入：
  - `reply_sent_live = true`
  - `reply_delivery_mode = "telegram_stream"`
- PA polling/webhook 服务看到 `reply_sent_live=true` 时，必须（MUST）跳过后续 outbox 直发，避免重复回复。

### 失败与降级（MUST）

- 若占位消息发送失败，运行时可以（MAY）回退为传统一次性 outbox 发送。
- 若流式编辑失败，但最终一次性发送可行，运行时应该（SHOULD）尝试最终一次性发送。
- 对 `editMessageText` 返回的 `HTTP 400` 且描述为 `message is not modified` 的情况，运行时必须（MUST）视为幂等成功，不得（MUST NOT）记录为出站失败。
- 任何降级都不得（MUST NOT）静默发生；日志必须（MUST）可观测。

## 边界条件（Boundary Conditions）

- 对纯工具 action 任务，运行时应该（SHOULD）禁用流式回调，避免无意义编辑。
- 对 reasoning / aggregate_reasoning 任务，运行时可以（MAY）复用同一流式消息继续编辑。
- 当 reply adapter 无法拿到 `message_id` 时，运行时不得（MUST NOT）假装支持编辑；应回退为最终一次性发送。

## 错误码（Error Codes）

- `E_PROVIDER_BAD_RESPONSE`
- `E_EXECUTION_FAILED`
- `E_PA_POLLING_FAILED`
- `E_PA_WEBHOOK_FAILED`

## 兼容策略（Compatibility）

- 本规范为 additive change。
- 旧 outbox 仍可读取；缺失 `reply_sent_live/reply_delivery_mode` 时必须（MUST）按默认值处理。
- 不支持流式 provider 的 backend 保持兼容，继续一次性回复。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. Provider 回调：
   - SSE delta 必须触发 `start/delta/completed` 事件。
2. Telegram adapter：
   - 必须先 `sendMessage`，后 `editMessageText`。
   - 必须维持输入中指示（Typing Heartbeat），直到执行结束。
   - 首个 `reply` 片段不得被常规节流延后。
   - `message is not modified` 不得被记为失败。
3. PA 服务：
   - `reply_sent_live=true` 时，不得重复执行 outbox 发送。
4. 回归命令：
   - `PYTHONPATH=src:tests python3 -m unittest tests.test_openai_codex_oauth_provider tests.test_thread040_telegram_reply tests.test_thread044_pa_polling tests.test_thread041_pa_webhook_server -v`
