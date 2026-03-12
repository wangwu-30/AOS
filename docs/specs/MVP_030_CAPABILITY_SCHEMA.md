# MVP_030_CAPABILITY_SCHEMA

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_030
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`

## 目的（Purpose）

把有效运行时能力（Effective Runtime Capabilities）固定为 Kernel 的唯一能力真相，确保权限解析、prompt 暴露、planner、executor 与 consumer 对同一对象达成一致。

## 接口/数据结构（Interfaces/Data）

canonical 位置：
- `ExecuteRequest.policy_context.effective_runtime_capabilities`

最小字段（MUST）：

```json
{
  "schema_version": "1.0.0",
  "type": "effective_runtime_capabilities_v1",
  "requested_capabilities": ["string"],
  "effective_capabilities": ["string"],
  "disabled_capabilities": [
    {
      "name": "string",
      "reason": "string"
    }
  ],
  "web": {
    "web_search_enabled": true,
    "web_browse_enabled": true,
    "backends": {
      "available": ["brave", "playwright"],
      "unavailable": {
        "brave": "string",
        "playwright": "string"
      },
      "default": "brave|playwright|null"
    }
  },
  "delivery": {
    "channel_message_enabled": true,
    "adapter_mode": "string"
  },
  "summary_lines": ["string"]
}
```

派生字段（MUST）：
- `policy_context.capabilities[]` 若存在，只能（MUST）视为从 `effective_capabilities` 机械派生的投影。
- `parse_capabilities()` 必须（MUST）优先读取 `effective_runtime_capabilities`。

## Allowed Names（Allowlist）

v1 固定 allowlist：
- `fs_read`
- `fs_write`
- `net_egress`
- `llm_remote`
- `scheduler_write`
- `memory_write`
- `memory_search`
- `memory_compact`
- `memory_delete`
- `registry_write`
- `channel_send`
- `time_read`
- `shell_exec`
- `web_search`
- `web_browse`
- `research_run`
- `assistant_runtime_submit`

禁止（MUST NOT）：
- `telegram_send_document`

## Enforcement（PEP 行为）

- 缺能力必须（MUST）返回 `E_CAPABILITY_DENY`。
- schema 非法必须（MUST）返回 `E_CAPABILITY_SCHEMA_INVALID`。
- 当 `web_browse` 已授权时，运行时必须（MUST）同时视 `web_search` 为兼容可用能力。
- 当请求 `research_run` 时，运行时必须（MUST）同时验证 `web_search` 与 `web_browse` 已进入 `effective_capabilities`；任一缺失时，`research_run` 必须（MUST）进入 `disabled_capabilities`。
- 高层模块不得（MUST NOT）绕过 `effective_runtime_capabilities` 自行探测 backend 或 provider。

## 默认值（Defaults）

- `requested_capabilities = []`
- `effective_capabilities = []`
- `disabled_capabilities = []`
- `web.backends.available = []`
- `web.backends.default = null`

## 边界条件（Boundary Conditions）

- 当 `allow_network_egress=false` 时，`web_search` 与 `web_browse` 必须（MUST）都被裁剪。
- 当 Playwright 不可用时，`web_browse` 必须（MUST）被裁剪。
- 当 `web_search` 或 `web_browse` 任一不可用时，`research_run` 必须（MUST）被裁剪。
- 当请求中包含未知 capability 时，必须（MUST）进入 `disabled_capabilities`，不得静默忽略。

## 兼容策略（Compatibility）

- `ExecuteRequest` 顶层字段保持不变。
- `policy_context.capabilities[]` 仅保留为派生视图；调用方不得（MUST NOT）把它当作事实来源。
- 历史 `telegram_send_document` capability 已删除；新调用方不得（MUST NOT）继续请求。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. `effective_runtime_capabilities` 成为 prompt、planner、executor、consumer 的唯一能力输入。
2. `policy_context.capabilities[]` 若存在，必须与 `effective_capabilities` 一致。
3. `web_browse` 隐式包含 `web_search`。
4. `research_run` 只有在 `web_search + web_browse` 同时可用时才能进入 `effective_capabilities`。
5. Telegram capability 不得再出现在 allowlist 或 prompt 中。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread030_capability_schema -v`
