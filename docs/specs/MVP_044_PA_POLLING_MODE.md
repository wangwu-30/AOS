# MVP_044_PA_POLLING_MODE

- 状态（Status）：Draft
- 日期（Date）：2026-03-10
- 目标版本（Target）：MVP_044
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/RELEASE_CRITERIA.md`

## 目的（Purpose）

定义个人助理（Personal Assistant）在本地长轮询（Long Polling）模式下的唯一 canonical 主链：

`Telegram Submitter Adapter -> Canonical Task Ingress -> Query-Gated Runtime -> Assistant Loop -> Consumer Adapter`

本规范不得（MUST NOT）引入第二套 runtime 语义。

## 默认值（Defaults）

- `timeout_seconds = 20`
- `limit = 20`
- `max_cycles = 1`
- `message_input_key = "request"`
- `scheduler_auto_tick_enabled = true`
- `scheduler_tick_max_fires = 20`
- `offset_checkpoint_enabled = true`
- `webhook_conflict_auto_recover = true`
- `transient_network_retry_attempts = 2`

## 核心行为（Core Behavior）

- polling 启动时必须（MUST）一次性构建 `EffectiveRuntimeCapabilitiesV1`。
- 后续 prompt、planner、executor、consumer 必须（MUST）只读这一个对象。
- polling 不得（MUST NOT）再维护 `effective_capabilities tuple + capability_runtime_hints dict` 双轨状态。
- Submitter Adapter 只负责 Telegram 入站归一化；Consumer Adapter 只负责把 `builtin://channel.send_message` 投影到 Telegram `sendMessage`。
- polling 主链中不得（MUST NOT）向模型暴露 Telegram-specific builtin。

## 能力与交付（Capabilities and Delivery）

- `telegram_send_document` 不再属于 canonical capability。
- polling 可请求的 canonical capability 至少包括：
  - `fs_read`
  - `fs_write`
  - `shell_exec`
  - `memory_write`
  - `memory_search`
  - `web_search`
  - `web_browse`
  - `channel_send`
- Telegram 文件或消息发送必须（MUST）由 Consumer Adapter 决定；模型不得（MUST NOT）直接生成 `builtin://telegram.*`。

## 边界条件（Boundary Conditions）

- 非文本更新必须（MUST）被忽略，且不得（MUST NOT）触发 runtime 执行。
- dedup 以 `event_id` 为准；命中后不得（MUST NOT）重复发送 reply。
- replay-mode 下必须（MUST）零副作用。
- scheduler auto tick 失败必须（MUST）返回稳定统计字段。
- 出站失败时必须（MUST）打印稳定诊断并保留 outbox 事实。
- 人工介入（Human-in-the-loop, HITL）导致 `delivery_state = hold` 时，PA 必须（MUST）仍然生成至少一条用户可见 delivery；不得（MUST NOT）因为 communicator 被跳过而留下空 `reply_text` 与空 `deliveries`。
- 当 runtime 返回 `hold` 且未给出显式 `builtin://channel.send_message` 时，Consumer Adapter 必须（MUST）合成一条 Telegram 可发送的保底消息。

## 错误码（Error Codes）

- `E_PA_POLLING_FAILED`
- `E_PA_POLLING_PAYLOAD_INVALID`
- `E_PA_WORKSPACE_UNMAPPED`
- `E_PA_POLLING_WEBHOOK_CONFLICT`
- `E_PA_POLLING_TRANSIENT_NETWORK`
- `E_PA_RUNTIME_FAILED`
- `E_PA_EV_REPLAY_DENY`
- `E_PA_EV_CONTEXT_FAILED`

## 兼容策略（Compatibility）

- 本规范绑定 CLI 命令 `mvp pa-polling`。
- 历史 `telegram_send_document` 请求可在入站层被视为已失效配置；runtime 不再保证兼容。
- 轮询 offset checkpoint 与既有事件信封（event envelope）格式保持兼容。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. polling 启动时产出 `EffectiveRuntimeCapabilitiesV1`。
2. capability summary 仅反映 `web_search/web_browse/channel_send` 等 canonical capability。
3. polling happy path 必须完成 `getUpdates -> canonical runtime -> channel delivery -> Telegram reply`。
4. scheduler auto tick 产出的提醒任务必须使用 `builtin://channel.send_message`。
5. `delivery_state = hold` 且 runtime 无显式 delivery 时，polling 仍必须完成 Telegram reply。
6. 非文本更新忽略、webhook 冲突恢复、瞬态网络重试、offset checkpoint 恢复必须通过。

发布门（MUST）：
- `tests.test_thread044_pa_polling` 是统一 runtime 的发布门（release gate）。
- 只有该门通过，才可以（MAY）表述“统一 runtime 验证通过”。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
