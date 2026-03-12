# ADR-0014 隐藏式浏览器辅助搜索与严格健康门（Hidden Browser-Assisted Search and Strict Health Gate）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-11
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`

## 背景（Context）

ADR-0013 已经冻结：

- `builtin://web.search` 必须（MUST）保持单一 public 搜索原语；
- 现役路径必须（MUST）保持 single runtime；
- Playwright 不得（MUST NOT）再以 public browser search shim 形式暴露。

但实际运行暴露出新的问题：

- `Brave Search API -> DuckDuckGo HTTP Search` 的纯 HTTP 链在真实环境下并不稳定，尤其 DuckDuckGo 容易返回门户页、空壳页或结构波动页面；
- 运行时此前只根据“网络开关 + 代码路径存在”推断 search 可用，导致 capability self-check 过于乐观；
- 对个人助理（PA）与 assistant-loop 场景而言，搜索功能不可用属于 P0 可用性缺陷，而不是单纯 blocker 文案问题。

因此，项目需要在不破坏 single runtime 与 public operator surface 的前提下，允许更强的 runtime 内部搜索实现。

## 决策（Decision）

冻结以下决定：

- `builtin://web.search` 继续（MUST）保持单一 public 搜索原语；模型、prompt 与调用方不得（MUST NOT）直接看到内部 provider 或浏览器搜索 operator。
- `builtin://web.search` 的 runtime 内部 provider chain 改为：
  1. `Brave Search API`
  2. `DuckDuckGo HTTP Search`
  3. `Browser-Assisted Search`
- `DuckDuckGo HTTP Search` 必须（MUST）保持 `provider=duckduckgo_html` 的审计身份，但可以（MAY）在内部按 `html -> lite` 顺序尝试多个纯 HTTP 变体。
- `Browser-Assisted Search` 只能（MUST）作为 runtime 内部兜底实现；不得（MUST NOT）成为 public primitive、prompt-visible operator 或 planner-selectable provider。
- `Browser-Assisted Search` 必须（MUST）受强边界约束：
  - 最多 1 次页面打开
  - 最多 1 次 query 重提
  - 最多 1 页结果抽取
  - 不得（MUST NOT）替代 `web.browse` 或 research doctrine
- `web.search` 必须（MUST）经过严格健康门（Strict Health Gate）后才能进入 `EffectiveRuntimeCapabilitiesV1`。
- 严格健康门必须（MUST）默认启用，并按 provider 链顺序探测可用性；成功条件必须（MUST）是“返回至少一个可用结果”，而不是静态配置存在。
- provider probe 结果必须（MUST）进程内缓存；默认 TTL 必须（MUST）为 600 秒；真实调用失败时必须（MUST）允许提前失效缓存。

## 与 ADR-0013 的关系（Relation to ADR-0013）

- ADR-0013 关于 single runtime、research doctrine、EV1 退出现役路径的结论继续有效。
- ADR-0013 中“`web.search` 不得再把 Playwright 作为搜索 fallback”这一条，从 2026-03-11 起由本 ADR 替代。
- 替代范围仅限搜索实现策略；不改变 `web.search` 的 public primitive 语义，也不恢复任何 public browser search shim。

## 备选方案（Alternatives）

1. 保持纯 HTTP provider 链，不允许任何浏览器兜底
   - 不采纳。
   - 原因：无法解决真实环境下 DuckDuckGo 门户页/空壳页带来的可用性缺陷，search 仍会长期处于“看起来可用、实际经常挂”的状态。

2. 暴露新的 public browser search primitive
   - 不采纳。
   - 原因：会破坏 canonical operator surface，并让 planner / prompt 再次看到实现细节。

3. 强制要求 Brave key，移除 HTTP fallback 与浏览器兜底
   - 不采纳。
   - 原因：把 search 可用性绑定到单一外部配置，会让默认体验过于脆弱。

## 取舍（Tradeoffs）

- 代价：
  - 搜索 runtime、spec 与测试需要重写；
  - capability self-check 从静态判断变成带缓存的主动探测；
  - 审计对象要新增 provider variant 与内部 fallback 记录。
- 收益：
  - `web.search` 的真实可用性显著提升；
  - capability self-check 不再乐观撒谎；
  - public operator surface 仍保持单一、稳定、可审计。

## 后果（Consequences）

- `web.search` 成功对象可能（MAY）出现 `provider_used=playwright_search`，但该值只属于 runtime 审计层。
- `provider_attempts` 会记录 Brave、DuckDuckGo HTTP 与 Browser-Assisted Search 的完整失败链。
- `web.search` 失败时，`user_facing_failure_summary_v1` 与 prompt-visible 文案不得（MUST NOT）把内部 provider 标识暴露成 public operator 或用户行动指令。
- `EffectiveRuntimeCapabilitiesV1` 中的 `web_search` 可用性将更严格，也更贴近真实运行状态。

## 风险与缓解（Risks & Mitigations）

- 风险：隐藏式浏览器搜索重新把 `web.search` 做成通用 browser agent。
  - 缓解：固定单次页面打开、单次 query 重提、单页抽取预算；禁止 public 暴露与 research 扩张。

- 风险：严格健康门导致启动探测变慢。
  - 缓解：限定 probe 结果缓存 TTL，并允许真实失败提前失效缓存，而不是每次重复探测。

- 风险：prompt 或 communicator 泄漏内部 provider 名称。
  - 缓解：在 MVP_045 与 MVP_047 中同步冻结 provider visibility 规则，要求 public surface 与用户可见文案都隐藏内部 fallback 标识。

## 可观测与验收（Metrics & Acceptance）

- `tests.test_thread047_runtime_capabilities_and_web` 必须（MUST）证明：
  - Brave -> DuckDuckGo HTTP -> Browser-Assisted Search 的链路顺序；
  - DuckDuckGo HTML 入口失败后继续尝试 Lite；
  - Browser-Assisted Search 可以在门户页场景下补提一次 query；
  - 严格健康门会裁剪全部 unhealthy 的 search providers。
- `tests.test_thread045_query_gated_runtime` 必须（MUST）证明：
  - prompt 不暴露 `playwright_search`、`provider=` 或 `provider_variant=`；
  - 失败摘要继续受 `user_facing_failure_summary_v1` 约束。
- `tests.test_thread044_pa_polling` 必须（MUST）证明：
  - capability self-check 反映真实 search health，而不是仅反映网络开关。

## 后续工作（Follow-ups）

- 继续收紧 `assistant_loop` 的 observation capsule，避免把内部 provider 细节泄漏到模型面。
- 为 Browser-Assisted Search 增加更细的时间预算与 source-domain 审计字段，但不改变其 hidden implementation 属性。
