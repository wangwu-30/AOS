# ADR-0011 Playwright 浏览器运行时与系统面收紧（Playwright Browser Runtime and Runtime Surface Tightening）

- 状态（Status）：Superseded by ADR-0013
- 日期（Date）：2026-03-10
- 相关规范（Related Specs）：
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_044_PA_POLLING_MODE.md`
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`

## 背景（Context）

此前 runtime surface 存在四类分叉：
- web 搜索同时暴露 Brave、BrowserUse、`ddg_html` 与显式 provider 选择；
- prompt、polling、executor 各自判断 capability 与 provider；
- ActionGraph 仍接受 alias、模板字符串与多套字段名；
- Telegram primitive 仍泄漏到模型侧与 active path。

这些分叉让“模型是查询引擎，agent 是约束与编排层”的设计哲学无法稳定落地。

## 决策（Decision）

1. 采用 Playwright 浏览器运行时（Playwright Browser Runtime）作为 canonical web backend。
2. `builtin://web.search` 的内部顺序曾固定为 `Brave -> Playwright`；该决定已被 ADR-0013 替换为 `Brave -> DuckDuckGo HTML Search`。
3. 删除 BrowserUse、`ddg_html` 与 provider 暴露，不再允许模型选择 backend。
4. 引入 `EffectiveRuntimeCapabilitiesV1` 作为唯一能力真相。
5. 收紧 `ActionGraphV1` 为 `action_id / operator_ref / arguments / depends_on` 与结构化 `$from_action`。
6. 删除模型侧 `builtin://telegram.*` 原语，渠道投影全部下沉到 Consumer Adapter。
7. 将 `pa-polling` 端到端测试提升为统一 runtime 的发布门。

## 备选方案（Alternatives）

### 1. 继续保留 BrowserUse 与 provider 暴露

不采纳。

原因：
- 模型面更大；
- backend 细节泄漏到 prompt；
- 与“agent 负责约束、runtime 拥有 wiring”相冲突。

### 2. 仅切 Playwright，不收紧能力快照与 ActionGraph

不采纳。

原因：
- 只能换实现，不能解决能力真相分叉与动作解释分叉。

### 3. 保留 Telegram primitive 作为快捷路径

不采纳。

原因：
- 破坏渠道与交付语义分离；
- consumer adapter 无法成为唯一渠道投影层。

## 取舍（Tradeoffs）

- 收益：
  - runtime 更小、更确定、更可审计；
  - prompt surface 与执行面保持一致；
  - Playwright 更适合被 fail-closed、trace、fixture 测试与发布门治理。
- 代价：
  - 放弃 BrowserUse 与旧 provider 参数；
  - 需要安装 Playwright 与 Chromium；
  - 旧 ActionGraph / Telegram / provider 相关测试与示例包必须同步改写。

## 后果（Consequences）

- BrowserUse 不再是 canonical runtime 的一部分。
- Telegram 只作为 consumer adapter 的目标渠道存在。
- `EffectiveRuntimeCapabilitiesV1` 成为 prompt、planner、executor、consumer 的共同真相源。
- `pa-polling` 的通过与否直接决定是否能宣称“统一 runtime 验证通过”。
- Search Primitive 与 Browse Runtime 的进一步拆分见 ADR-0013。

## 风险与缓解（Risks & Mitigations）

- 风险：Playwright 安装失败或 Chromium 缺失导致 web runtime 不可用。
  - 缓解：统一返回 `E_WEB_RUNTIME_UNAVAILABLE`，并在文档与发布门中固定安装前置步骤。
- 风险：外部真实搜索结果波动导致测试不稳定。
  - 缓解：发布门与集成测试只使用本地 fixture 或 mock。
- 风险：旧示例包与旧测试继续宣称 BrowserUse/Telegram/provider 语义。
  - 缓解：同步改写 specs、README、example skill、回归测试。

## 可观测与验收（Metrics & Acceptance）

- prompt 不再出现 BrowserUse、Telegram primitive 或 provider 枚举。
- `EffectiveRuntimeCapabilitiesV1` 在 polling 与 assistant loop 中可回放。
- `ActionGraphV1` 对 alias/template 稳定拒绝。
- `tests.test_thread044_pa_polling` 成为发布门并通过。

## 后续工作（Follow-ups）

- 为 Playwright browse/search 增加更多本地 fixture 覆盖。
- 若未来需要更强 browser automation，仅允许作为 Playwright 扩展，不再重新引入 BrowserUse。
