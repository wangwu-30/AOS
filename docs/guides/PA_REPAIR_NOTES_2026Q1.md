# PA 修复经验（Repair Notes）

本文记录 2026 Q1 期间 Telegram PA 的真实修复条目。重点不是“做了什么”，而是“问题如何暴露、根因是什么、以后怎么避免再犯”。

## 1. offset 未持久化导致历史消息回放

### 症状

- 重启 polling 后，旧的 Telegram update 又被重新处理。
- 用户看到“收到 update 但没回复”。

### 根因

- 轮询进程没有稳定持久化 `next_offset`。
- 重启后重新从旧 offset 拉取历史消息。
- 历史消息命中 dedup 后被跳过，表面上看像“没处理”。

### 修复

- 增加 offset 检查点文件存储。
- 启动时默认从已持久化 offset 续跑。
- offset 没变化时不再重复打日志。

### 经验

- 轮询系统没有 checkpoint，就谈不上稳定运维。
- dedup 命中必须与“历史回放”一起看，单看 dedup 很容易误判。

## 2. provider 错误只有裸 `E_PROVIDER_BAD_RESPONSE`

### 症状

- 用户只能看到 `E_PROVIDER_BAD_RESPONSE`。
- 终端无法区分 429、401、403、payload 格式问题或网络错误。

### 根因

- provider/backend 只抛稳定错误码，没有透出足够诊断细节。

### 修复

- 错误细节补充 `status`、`body_preview` 或 transport detail。
- PA 的兜底文案保持稳定，但终端与 evidence 保留足够诊断信息。

### 经验

- 用户提示可以简化，但运维证据不能简化。
- 稳定错误码与可诊断细节必须同时存在。

## 3. Telegram 流式卡顿并最终超时

### 症状

- 流式看起来越来越卡。
- 长一点的回复甚至触发 `E_TIMEOUT`。

### 根因

- provider SSE 读取与 Telegram `editMessageText` 在同一执行链上同步进行。
- 每次发一个 delta，都阻塞一次 Telegram HTTP 请求。
- 结果不是“模型慢”，而是“读取被出站 IO 拖慢”。

### 修复

- 把 Telegram 文本编辑移到后台发送线程。
- provider 流读取只负责收集 delta 与更新本地缓冲。
- 本地先缓冲多个 chunk，再分块刷新 Telegram。

### 经验

- 流式系统里最忌讳把“上游读取”和“下游展示”串成同步链。
- 如果用户说“像被限速”，先查本地显示链，不要先怪模型。

## 4. typing 状态提前结束

### 症状

- Telegram 很快就不显示 typing。
- 用户误以为系统已经停了。

### 根因

- 早期实现只是一次性发送 `sendChatAction`。
- 没有持续 typing 心跳。

### 修复

- 增加 `Typing Heartbeat` 会话。
- 从执行开始一直维持到完成、失败或最终收口。

### 经验

- typing 不是装饰，它是用户感知“系统还活着”的基础反馈。
- 会话级状态必须跟执行生命周期绑定。

## 5. 流式显示过碎，像一字一字蹦

### 症状

- 已经开始回复，但文本一字一字跳。
- 观感比一次性回复更差。

### 根因

- 刷新粒度过小。
- reply 与进度共用一套过于激进的刷新策略。

### 修复

- 引入本地 chunk 缓冲。
- 首屏设置最小可见阈值和最大等待时间。
- reply 模式与 progress 模式分离。

### 经验

- “尽快开始”不等于“任何碎片都立刻发”。
- 好的流式体验不是最快逐字，而是尽快、稳定、成块。

## 6. provider 流式首包前 TLS EOF

### 症状

- 终端出现：
  - `transport error: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] ...>`
- 用户最终只收到 provider 异常兜底。

### 根因

- 上游 TLS 连接瞬态断开。
- provider 层没有在“首个 delta 前”做自愈重试。

### 修复

- provider 层对“首个 delta 前”的瞬态网络错误增加一次短重试。
- 请求头增加 `Connection: close`，减少连接复用带来的 EOF。

### 经验

- 这类问题应该在 provider 层解决，不应该让 PA 层去猜。
- 但重试必须有边界：一旦已经流出任何内容，禁止重试。

## 7. 搜索能力暴露不一致

### 症状

- 用户让它搜网页，它表现得像没这个能力。
- 明明 runtime 支持，prompt 却没体现，或者 capability gate 不一致。

### 根因

- 运行时授予能力与 skill/prompt 暴露能力不一致。
- provider 路由和用户期望之间也缺少清晰提示。

### 修复

- 统一 runtime capability 与 prompt 暴露。
- 增加 `Brave Search API -> DuckDuckGo HTTP Search -> Browser-Assisted Search` 搜索 provider chain，并把浏览器搜索限定为 `web.search` 内部兜底实现。
- 对 `web.search` 增加严格健康门（Strict Health Gate）：至少一个搜索 provider 通过自检后，能力才会进入 `EffectiveRuntimeCapabilitiesV1`。
- 缺 Brave key、DuckDuckGo HTTP 不健康或 Playwright runtime 不可用时明确失败，不静默降级为假成功。

### 经验

- 能力存在于运行时，不存在于宣传文案。
- prompt 必须只声明当前轮真实可用的动作。
- 搜索 provider 是否存在不重要，provider 是否通过健康门才重要。

## 8. 维护规则沉淀

这几轮修复后，最重要的长期规则有五条：

1. 任何用户可见失败都必须带稳定兜底回复。
2. 任何运维可见失败都必须带足够诊断细节。
3. 任何流式展示链都不得阻塞上游 provider 读取。
4. 任何历史回放风险都必须有持久化断点续跑。
5. 任何不符合预期的降级都不能静默吞掉。

## 9. `开始 / OK / 继续` 被当成新任务原文执行

### 症状

- 用户上一轮刚描述完任务，下一轮只说“开始”“OK”“继续”。
- 系统没有稳定恢复上一任务，而是把这几个字当成新的原始任务处理。

### 根因

- 入口缺少显式意图恢复（Intent Recovery）阶段。
- 会话状态没有把 `last_pending_task`、`last_delivery_state` 这类最小槽位稳定落盘。
- 运行时过早把问题推给模型理解，工程判定层太薄。

### 修复

- 增加固定选项 + 可选备注的意图恢复层。
- 增加文件化会话状态存储，按 `workspace_id + conversation_id` 维度保存最小恢复信息。
- Query Compile 先做意图恢复，再做 Task Compile。

### 经验

- `开始 / OK / 继续` 不是自然语言任务，它们是状态机输入。
- 这类输入应先用工程规则解释，再决定是否让模型兜底。

## 10. 多模型问题先要有路由策略对象

### 症状

- 系统已经有 `backend / planner_backend / model` 参数，但没有统一的“为什么这轮该用哪种模型策略”解释。
- 闲聊、状态查询、复杂规划共用同一层低级参数，后续难以扩展。

### 根因

- 缺少交互模式（Interaction Mode）与模型路由策略（Model Routing Policy）这一层中间语义。

### 修复

- 在 Query Compile 中显式生成 `interaction_mode` 与 `model_routing_policy`。
- assistant plan 记录路由策略摘要，先作为审计对象，再为后续真实多模型调度铺路。

### 经验

- 多模型扩展不应该直接堆 backend 参数。
- 应先冻结“路由为什么这样选”的中间 contract，再逐步放开真实调度。
