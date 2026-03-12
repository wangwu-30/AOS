# MVP_041_PA_WEBHOOK_SERVER

## 目标（Goal）

个人助理（Personal Assistant）必须提供可运行的本地回路（loopback webhook）：

- 入站：Telegram Webhook `POST /v1/telegram/webhook`
- 执行：Canonical Task Ingress（Canonical Task Ingress）→ Query-Gated Runtime（Query-Gated Runtime）→ Assistant Loop（Assistant Loop）
- 出站：OutboxItem → Telegram Reply Adapter（默认 stub）

本规范只定义应用层服务形态，不变更 Kernel 执行接口；历史 `ev1` 仅作为响应体兼容别名。

## 非协商约束（Non-negotiables）

- `top_level_api_stable`：禁止新增 `ExecuteRequest` 顶层字段。
- `fail_closed`：校验失败必须稳定返回错误码，不得泄漏 traceback。
- `replay_mode_no_side_effects`：`replay-mode` 下禁止写盘与网络副作用。

## 默认值（Defaults）

- `host`：`127.0.0.1`（MUST，P0 仅 loopback）
- `port`：`8089`
- `path`：`/v1/telegram/webhook`
- `message_input_key`：`request`
- `bot_token`：`stub-token`（默认 stub send）
- `verify_asvp`：`true`
- `memory_context_enabled`：`false`
- `memory_context_retrieval_limit`：`8`
- `memory_context_include_stale`：`false`
- `memory_context_continuity_event_limit`：`50`
- `memory_context_audit_mode`：`false`
- `budget_slice_remote_llm_calls`：
  - 缺失（missing）→ fallback `10`
  - 显式 `null` 或非法值 → 拒绝（deny）

## 边界条件（Boundary）

- Webhook header `X-Telegram-Bot-Api-Secret-Token` 必须校验，失败必须 `401/E_AUTH_FAILED`。
- 仅处理 `POST <path>`；其他 path 必须 `404/E_BAD_CHANNEL_INPUT`。
- 去重（dedup）以 `event_id` 为准；若命中去重，MUST 不重复发送 reply。
- `policy_context` 只能透传，MUST NOT 在应用层做 allow/deny 最终裁决。
- 当 `memory_context_enabled=true` 时，MUST 通过 THREAD-043 V2 装配 `policy_context["memory_context"]`；若 `memory_context_retrieval_limit<=0` 或作用域输入非法，MUST fail-closed 返回 `E_PA_EV_CONTEXT_FAILED`。
- 当 canonical runtime 返回 `ok=false` 但 outbox 中已存在合法 `send_message` 交付对象时，webhook 必须（MUST）继续发送该 fallback reply；不得（MUST NOT）因为 runtime 失败而丢弃已生成的用户可见兜底消息。
- 响应体中的 `runtime` 必须（MUST）为 canonical runtime 输出；`ev1` 可以（MAY）作为同值兼容别名保留。

## 错误码（Error Codes）

- 入站层（CH1）：
  - `E_AUTH_FAILED`
  - `E_CHANNEL_PAYLOAD_INVALID`
  - `E_BUDGET_REJECTED`
- 服务层（041）：
  - `E_PA_WEBHOOK_FAILED`
  - `E_PA_WEBHOOK_DISPATCH_MISSING`
  - `E_PA_WEBHOOK_OUTBOX_INVALID`
- 回放拒绝（Runtime Compatibility Alias）：
  - `E_PA_EV_REPLAY_DENY`
  - `E_PA_EV_CONTEXT_FAILED`

## 兼容策略（Compatibility）

- 本规范为增量命令（additive CLI command）；`mvp pa-demo` 与 `mvp pa-webhook-server` 必须（MUST）走 canonical runtime，`ev1` 只能（MAY）保留响应兼容别名。
- 不变更 `PA_EVENT_ENVELOPE_V0` 字段定义；字段漂移必须先更新该规范。

## 测试与验收（Tests & Acceptance）

### 必测（MUST）

1. 正常回路：webhook → canonical runtime → outbox → reply 成功。
2. 同一 `update_id` 重放：命中 dedup，禁止重复 reply。
3. `replay-mode`：拒绝并零副作用。
4. `memory_context_enabled=true` 且 memory V2 配置非法：`200 + E_PA_EV_CONTEXT_FAILED`，且不得写入 outbox。
5. canonical runtime 失败但生成了合法 fallback `send_message` 时，webhook 必须（MUST）仍然发送 reply，且顶层 `error_code` 必须（MUST）为 `null`。

### 验收命令（Acceptance Commands）

- `PYTHONPATH=src python3 -m unittest tests/test_thread041_pa_webhook_server.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
