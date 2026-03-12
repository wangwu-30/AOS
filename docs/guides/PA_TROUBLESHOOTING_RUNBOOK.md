# PA 排障手册（Troubleshooting Runbook）

本文按“症状 -> 根因判断 -> 证据位置 -> 修复动作”组织，优先解决 Telegram PA 的高频问题。

## 1. 快速分诊顺序

遇到问题时，不要先猜模型，也不要先猜 Telegram。按下面顺序看：

1. 终端日志
2. `data/pa/outbox/local/<event_id>.json`
3. `data/traces/tr_pa_<event_id>.jsonl`
4. `data/pa/events/local/<event_id>.json`
5. `data/pa/polling_offsets/*.json`

如果第 2 步没有 outbox，说明问题在执行前或执行中。
如果第 2 步有 outbox 但用户没收到，说明问题在出站层。

## 2. 常见故障模式（Failure Mode）

| 症状 | 高概率根因 | 先看哪里 | 处理动作 |
| --- | --- | --- | --- |
| Telegram 完全没回复 | polling 没拿到 update，或 update 没进入 canonical runtime | 终端日志、`events/` | 先确认是否打印 `Received Telegram Update` |
| 终端显示收到 update，但用户没看到回复 | outbox 未生成，或 Telegram 出站失败 | `outbox/`、`Telegram` 日志 | 区分“执行没产出”与“产出了但没发出去” |
| 重启后旧消息又被处理 | offset 未持久化或未续跑 | `polling_offsets/` | 检查 `Resuming from persisted offset` |
| 返回 `E_PROVIDER_BAD_RESPONSE` | provider HTTP/transport 错误 | `outbox/`、trace、provider detail | 看 `status`、`body_preview` 或 transport detail |
| 流式越来越卡，最后超时 | Telegram 编辑阻塞了 provider 流读取 | trace、终端流式日志 | 检查是否还是旧进程；升级到异步发送版 |
| typing 很快消失 | 没有持续 typing 心跳 | 终端日志、`telegram_reply.py` 行为 | 检查是否启用了 runtime typing session |
| 让它搜东西却反复失败 | 搜索 capability 暴露不一致，或严格健康门裁掉了全部搜索 provider | 终端日志、skill prompt、能力列表 | 确认 `web_browse/web_search`、Brave key、DuckDuckGo HTTP Search / Browser-Assisted Search 健康状态 |
| 明明处理过的消息又出现在日志里 | 历史 update 回放，被 dedup 命中 | `events/`、`outbox/`、offset checkpoint | 不一定是 bug，先判断是不是旧 update |

## 3. 具体排障流程

### 3.1 “收到 update，但没有任何回复”

检查项：

1. 终端是否出现：
   - `--- [PA] Received Telegram Update id=... ---`
2. `data/pa/outbox/local/tg_update_<id>.json` 是否存在。
3. 若存在，查看：
   - `execute_status`
   - `execute_error_code`
   - `reply_text`
   - `reply_sent_live`

判断：

- 没有 outbox：问题在 canonical runtime 或更前面。
- 有 outbox，但没发送：问题在 Telegram 出站。
- 有 outbox 且 `reply_sent_live=true`：说明已经尝试走流式，后续 polling/webhook 会跳过重复直发。

建议动作：

- 若是旧 update，被 dedup 静默跳过，先确认 offset 是否正确续跑。
- 若是新 update 且 `reply_text` 为空，继续查 trace。

### 3.2 “收到 update，但只返回 `E_PROVIDER_BAD_RESPONSE`”

看两处：

1. 终端日志里的 `detail=...`
2. outbox 对应 evidence 的错误详情

如何解读：

- `status=429` / `usage_limit_reached`
  - 账号或额度问题，不是 PA 逻辑 bug。
- `transport error: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] ...>`
  - 瞬态 TLS EOF。
  - 当前实现会在首个 delta 前自动重试一次。
- `401` / `403`
  - token、授权或 endpoint 配置错误。

建议动作：

- 先确认是 transport 类错误还是业务状态码。
- 如果 transport 类错误仍频繁出现，优先检查网络环境，而不是继续改 Telegram 层。

### 3.3 “流式开始了，但像一字一字蹦出来”

这类问题通常不是模型慢，而是展示层刷新过碎。

检查项：

1. 是否运行的是最新进程。
2. `telegram_reply.py` 中是否已经是“本地 chunk 缓冲 + 后台 sender thread”实现。
3. 是否仍然看到频繁 `editMessageText` 导致的节流抖动。

当前正确行为：

- provider delta 在本地先缓冲。
- Telegram 文本编辑由后台线程异步发送。
- reply 应表现为短块补齐，而不是逐字跳。

### 3.4 “流式一段时间后直接超时”

先区分两种超时：

- `E_TIMEOUT`
  - 执行器或编排器 deadline 命中。
- Telegram 发不出去
  - 这是出站错误，不应该表现为 `E_TIMEOUT`。

排查点：

1. `data/traces/tr_pa_<event_id>.jsonl`
2. `src/agentos_next/runtime/local_executor.py`
3. `src/agentos_next/kernel/orchestrator.py`

如果是长回复触发超时，重点看：

- provider 流读取是否被其他同步 IO 阻塞。
- task graph 是否本身过长。
- 搜索/网络工具是否反复重试。

### 3.5 “重启后又处理了旧消息”

先看：

- `data/pa/polling_offsets/*.json`
- 启动日志是否有：
  - `Resuming from persisted offset: ...`

判断逻辑：

- 如果没有 offset checkpoint，旧消息重放是预期风险。
- 如果已有 checkpoint 但仍回放，检查是不是显式传了更旧的 `--offset`。

### 3.6 “搜索能力像没接上”

先看这几件事：

1. 本轮 capabilities 是否真的授予了搜索能力。
2. prompt 中是否暴露了实际可用动作。
3. provider 路由配置是否存在。

当前搜索路径：

- `Brave Search API`
- `DuckDuckGo HTTP Search`
- `Browser-Assisted Search`（仅作为 `web.search` 内部兜底，不是 public primitive）

当前能力判定：

- `web_search` 采用严格健康门（Strict Health Gate）。
- 只有至少一个搜索 provider 自检通过时，`web_search` 才会进入 effective capabilities。
- `web_browse` 仍单独依赖 Playwright Browser Runtime，不与 `web_search` 共用健康判定。

若期望页面验证或引用抽取：

- 必须明确授予 `web_browse`，并保证 Playwright Browser Runtime 可用。
- 缺 Playwright 时必须显式报错，不能把 browse 失败伪装成 search 成功。

## 4. 建议的日志阅读顺序

### 4.1 入站是否正常

看：

- `Received Telegram Update id=...`
- `Offset checkpoint saved: next_offset=...`

### 4.2 执行是否正常

看 outbox 里的：

- `execute_status`
- `execute_error_code`
- `evidence_refs`

### 4.3 出站是否正常

看：

- `[PA] Reply sent for update ...`
- `[PA] Reply streamed for update ...`
- `[PA] Reply send failed for update ...`
- `[Telegram] ...`

## 5. 落盘文件速查

| 位置 | 作用 |
| --- | --- |
| `data/pa/events/local/` | 原始 Telegram 入站事件 |
| `data/pa/outbox/local/` | 对用户可见的最终回复或兜底回复 |
| `data/traces/` | 执行时间线 |
| `data/pa/polling_offsets/` | 轮询断点续跑状态 |
| `data/evidence/` | 结构化错误与执行证据 |

## 6. 修复动作优先级

排障时按这三层切：

1. 通道层
   - Telegram 是否收到 update、能否出站发送
2. 执行层
   - Canonical Runtime Facade / Orchestrator / Executor 是否产出 outbox
3. provider 层
   - 模型服务是否返回业务错误、网络错误或流式异常

不要一上来就改 prompt。先证明问题在 prompt，再动 prompt。

## 7. 关联文档

- [PA 架构总览](/Users/wangwu/codex/agentos-next/docs/guides/PA_ARCHITECTURE_OVERVIEW.md)
- [PA 修复经验](/Users/wangwu/codex/agentos-next/docs/guides/PA_REPAIR_NOTES_2026Q1.md)
- [变更记录](/Users/wangwu/codex/agentos-next/CHANGELOG.md)
