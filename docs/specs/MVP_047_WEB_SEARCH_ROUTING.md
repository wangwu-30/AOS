# MVP_047_WEB_SEARCH_ROUTING

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_047
- 相关规范（Related Specs）：
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`

## 目的（Purpose）

定义 `builtin://web.search` 与 `builtin://web.browse` 的 canonical 语义，冻结搜索提供方链（Search Provider Chain）、浏览器辅助搜索（Browser-Assisted Search）与严格健康门（Strict Health Gate）的职责边界。

## 范围（Scope）

本规范覆盖：
- `builtin://web.search(query, limit?)`
- `builtin://web.browse(url)`
- 搜索提供方链 `Brave Search API -> DuckDuckGo HTTP Search -> Browser-Assisted Search`
- 普通外部证据的有界外部证据编排（Bounded External Evidence Orchestration）边界
- 门户页、空壳页、无结果与 provider 健康探测语义
- 错误码、默认值、边界条件、兼容策略、测试与验收

本规范不覆盖：
- 账号登录、表单提交、截图、录屏
- 任意多轮浏览器代理
- `builtin://research.run` 的输入输出合同细节

## 接口/数据结构（Interfaces/Data）

### SearchInputV2（MUST）

```json
{
  "query": "string",
  "limit": 5
}
```

默认值（MUST）：
- `limit = 5`

约束（MUST）：
- `query` 必须（MUST）为非空字符串。
- `limit` 必须（MUST）被限制在 `1..10`。
- 调用方不得（MUST NOT）传入 `provider`、`provider_variant` 或任何浏览器控制参数。

### SearchOutputV2（MUST）

```json
{
  "schema_version": "1.0.0",
  "ok": true,
  "provider_used": "brave|duckduckgo_html|playwright_search",
  "provider_variant": "html|lite",
  "degraded": false,
  "expectation_mismatch": false,
  "provider_attempts": [
    {
      "provider": "brave|duckduckgo_html|playwright_search",
      "variant": "html|lite",
      "status": "ok|failed",
      "error_code": "string",
      "detail": "string"
    }
  ],
  "results": [
    {
      "title": "string",
      "snippet": "string",
      "url": "string"
    }
  ],
  "notices": ["string"]
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `degraded = false`
- `expectation_mismatch = false`
- `provider_variant` 缺省时可以（MAY）省略
- `notices = []` 可以（MAY）省略

### SearchFailureOutputV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "ok": false,
  "operator_ref": "builtin://web.search",
  "error_code": "E_WEB_SEARCH_NO_RESULTS|E_WEB_RUNTIME_UNAVAILABLE|E_EXECUTION_FAILED",
  "message": "string",
  "query": "string",
  "limit": 5,
  "degraded": false,
  "expectation_mismatch": true,
  "provider_attempts": [
    {
      "provider": "brave|duckduckgo_html|playwright_search",
      "variant": "html|lite",
      "status": "failed",
      "error_code": "string",
      "detail": "string"
    }
  ],
  "results": [],
  "notices": ["string"]
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `ok = false`
- `degraded = false`
- `expectation_mismatch = true`
- `results = []`

### BrowseOutputV2（MUST）

```json
{
  "schema_version": "1.0.0",
  "ok": true,
  "provider_used": "playwright",
  "url": "string",
  "final_url": "string",
  "title": "string",
  "output": {
    "reply": "string",
    "url": "string",
    "title": "string"
  }
}
```

## 语义（Semantics）

### Canonical Operator Surface（MUST）

- 模型侧只允许（MUST）看到：
  - `builtin://web.search(query, limit?)`
  - `builtin://web.browse(url)`
- 模型侧不得（MUST NOT）看到：
  - `builtin://browseruse.search`
  - `playwright_search`
  - `provider=...`
  - `provider_variant=...`
  - Browser Use Bridge（Browser Use Bridge）或任何浏览器搜索控制参数

### Search Primitive（MUST）

- `builtin://web.search` 必须（MUST）是只读、低副作用、候选发现型原语。
- `builtin://web.search` 只负责：
  - 返回候选结果列表；或
  - 返回稳定“无结果/失败”对象。
- `builtin://web.search` 不得（MUST NOT）把浏览器动作暴露给模型或 prompt。
- provider 选择必须（MUST）由 runtime 内部完成；调用方与 prompt 不得（MUST NOT）控制 provider。

### 通用候选发现（Generic Candidate Discovery）（MUST）

- `builtin://web.search` 只能（MUST）执行通用候选发现；不得（MUST NOT）基于 query 主题、站点类型、业务语义或推断时间属性做 topic-aware 重排、过滤或 provider 拒收。
- `builtin://web.search` 可以（MAY）做与主题无关的通用规范化，包括：
  - 重定向 URL 规范化
  - 空标题/空 URL 结果剔除
  - 完全重复 URL 去重
  - 结果条目裁切到 `limit`
- provider 一旦返回非空规范化候选列表，就必须（MUST）被视为 search success；后续 browse 是否成功不影响该 provider 的 success 判定。
- `builtin://web.search` 不得（MUST NOT）因为候选页看起来像月归档、历史页、聚合页或其他主题相关页面模式而把 provider 重新判定为失败。

### Search Provider Chain（MUST）

- `builtin://web.search` 必须（MUST）按固定顺序尝试：
  1. Brave Search API
  2. DuckDuckGo HTTP Search
  3. Browser-Assisted Search
- DuckDuckGo HTTP Search 必须（MUST）保持 `provider=duckduckgo_html` 的审计身份，并按固定顺序尝试：
  1. `html.duckduckgo.com/html/`
  2. `lite.duckduckgo.com/lite/`
- DuckDuckGo HTTP Search 的变体只能（MUST）通过 `provider_attempts[].variant` 或 `provider_variant` 进入审计对象；不得（MUST NOT）进入模型面 surface。
- Browser-Assisted Search 必须（MUST）保持 `provider=playwright_search` 的内部审计身份，但不得（MUST NOT）作为 public primitive 出现。
- 当 Brave 失败且后续 provider 成功时，`degraded` 必须（MUST）为 `true`。
- 当所有 provider 都失败时，运行时必须（MUST）返回稳定失败；不得（MUST NOT）伪造空成功结果。
- `provider_attempts` 与 `notices` 必须（MUST）保留完整 provider 链失败摘要，禁止静默降级。

### DuckDuckGo HTTP Search（MUST）

- DuckDuckGo HTTP Search 必须（MUST）通过纯 HTTP 获取结果页 HTML；不得（MUST NOT）拉起浏览器。
- 结果抽取必须（MUST）支持 HTML 入口与 Lite 入口的不同结构。
- DuckDuckGo 重定向链接必须（MUST）被规范化为最终外部 URL 后再参与可用结果判定。
- 当 HTML 入口返回门户页、主页、登录页、空壳页或其他无结果页面时，运行时必须（MUST）继续尝试 Lite 入口，而不是立即宣告 provider 成功。

### Browser-Assisted Search（MUST）

- Browser-Assisted Search 只能（MUST）作为 `builtin://web.search` 的内部兜底实现。
- Browser-Assisted Search 仅在 Brave 与 DuckDuckGo HTTP Search 全失败后才可（MUST）触发。
- Browser-Assisted Search 的单次调用预算必须（MUST）受限为：
  - 最多 1 次页面打开
  - 最多 1 次 query 重提
  - 最多 1 页结果抽取
- Browser-Assisted Search 不得（MUST NOT）调用 public `builtin://web.browse`。
- Browser-Assisted Search 不得（MUST NOT）执行多轮研究、页面比较、跨站浏览或表单自动化。
- 当浏览器首次落到 DuckDuckGo 门户页且检测到搜索框与未提交态时，运行时可以（MAY）自动补提一次原 query。
- 补提一次后仍无结果时，必须（MUST）稳定返回 `E_WEB_SEARCH_NO_RESULTS`。

### Portal / Empty Shell Handling（MUST）

- 当 provider 返回门户页、主页、登录页、空壳页或其他无结果页面时，必须（MUST）视为 provider failure。
- DuckDuckGo 门户页不得（MUST NOT）被当作成功搜索结果。
- 目标站点本身的归档页、历史页、聚合页或其他候选落地页模式，不得（MUST NOT）仅凭 topic-specific 规则在 search 层被判定为 provider failure。
- SearchFailureOutputV1 在“provider 链耗尽且未取得可用结果”场景下，`error_code` 必须（MUST）稳定为 `E_WEB_SEARCH_NO_RESULTS` 或更底层 runtime 不可用错误码。

### Browse Routing（MUST）

- `builtin://web.browse` 必须（MUST）只通过 Playwright 浏览器运行时（Playwright Browser Runtime）执行导航与文本抽取。
- `builtin://web.browse` 不得（MUST NOT）与 `builtin://web.search` 共享 public provider 语义。
- `builtin://web.browse` 可以（MAY）与 Browser-Assisted Search 共享 Playwright runtime 实现，但不得（MUST NOT）共享 public operator surface。

### Strict Health Gate（MUST）

- `web.search` 必须（MUST）经过严格健康门后才能进入 `EffectiveRuntimeCapabilitiesV1`。
- 严格健康门必须（MUST）按 provider 链顺序探测 Brave、DuckDuckGo HTTP Search 与 Browser-Assisted Search。
- provider health probe 的成功条件必须（MUST）是“返回至少一个可用结果”，而不是仅检查网络开关、代码路径或依赖安装存在。
- provider health probe 结果必须（MUST）在进程内缓存。

默认值（MUST）：
- `strict_health_gate = true`
- `provider_probe_ttl_seconds = 600`
- `provider_probe_limit = 1`

额外规则（MUST）：
- 当 provider 在真实搜索调用中失败时，运行时必须（MUST）允许提前失效该 provider 的缓存探测结果。
- 当所有 search providers 均 unhealthy 时，`web.search` 必须（MUST）从 `effective_capabilities` 中移除。
- `web_browse` 必须（MUST）继续由独立的 Playwright browse probe 决定，不得（MUST NOT）与 search health 混淆。

### Research Doctrine Boundary（MUST）

- `web.search` 只产出候选；`web.browse` 才承担页面验证与引用抽取。
- 对普通外部信息查询，多轮 `search -> browse` 必须（MUST）由查询门控运行时（Query-Gated Runtime）在有界外部证据编排内完成；不得（MUST NOT）把该职责压回 `web.search`。
- 显式调研（Explicit Research）只能（MUST）通过 `builtin://research.run` 进入模型面；普通 `search + browse` 失败不得（MUST NOT）自动升级为调研工具调用。
- Browser-Assisted Search 只是搜索 provider 实现细节，不得（MUST NOT）被当作调研工具或 research doctrine 替代物。

### 有界外部证据编排边界（Bounded External Evidence Orchestration Boundary）（MUST）

- 普通外部证据候选消费必须（MUST）发生在 `builtin://web.search` 之外。
- Assistant Loop / verifier / replanner 可以（MAY）在 `external_evidence_policy_v1` 预算内消费同一次或多次 search 产生的候选 URL。
- 候选消费失败不得（MUST NOT）回写为 `web.search` runtime unavailable。
- 当 search 已成功返回候选但下游 browse 在预算内未形成可接受证据时，系统必须（MUST）把该情形归类为候选/来源耗尽（Candidate/Source Exhaustion）。

### Capability Exposure（MUST）

- 运行时必须（MUST）从 `EffectiveRuntimeCapabilitiesV1` 读取 `web.search_enabled`、`web.browse_enabled` 与 provider 健康结果。
- Prompt、planner、executor、consumer 不得（MUST NOT）重复探测 Brave、DuckDuckGo HTTP Search、Browser-Assisted Search、Playwright 或网络条件。
- 当 `web_browse` 已授予时，运行时必须（MUST）同时视 `web_search` 为兼容可用能力；但 `web.search` 仍必须（MUST）通过严格健康门。

## 错误码（Error Codes）

- `E_WEB_RUNTIME_UNAVAILABLE`
- `E_WEB_NAVIGATION_FAILED`
- `E_WEB_SEARCH_NO_RESULTS`
- `E_EXECUTION_FAILED`
- `E_CAPABILITY_DENY`

错误细化（SHOULD）：
- Brave key 缺失时，错误消息应该（SHOULD）包含 `BRAVE_SEARCH_API_KEY`。
- Playwright 不可用时，错误消息应该（SHOULD）包含安装提示：
  - `python3 -m pip install playwright`
  - `python3 -m playwright install chromium`

## 边界条件（Boundary Conditions）

- 当 `allow_network_egress=false` 时，`web.search` 与 `web.browse` 必须（MUST）同时不可用。
- 当 Brave 不可用但 DuckDuckGo HTTP Search 或 Browser-Assisted Search 可用时，`web.search` 可以（MAY）保持可用。
- 当 Playwright 不可用但 Brave 或 DuckDuckGo HTTP Search 可用时，`web.search` 可以（MAY）保持可用；`web.browse` 必须（MUST）不可用。
- 当 Playwright 可用但 Brave 与 DuckDuckGo HTTP Search 均不可用时，`web.search` 可以（MAY）仅依赖 Browser-Assisted Search 保持可用。
- 当 `web.search` 已成功返回候选而 browse 预算耗尽时，该失败必须（MUST）归属普通外部证据候选耗尽，而不是 `E_WEB_SEARCH_NO_RESULTS`。
- `limit<=0`、空 `query`、空 `url` 必须（MUST）按输入错误 fail-closed。

## 兼容策略（Compatibility）

- `provider` 参数已废弃；新调用方不得（MUST NOT）继续发送该字段。
- `builtin://browseruse.search` 已删除；新调用方不得（MUST NOT）再引用。
- `playwright_search` 只允许（MUST）出现在 runtime 审计对象中；新调用方与 prompt 不得（MUST NOT）直接引用。
- 旧版“public browser-based search shim 已删除”的兼容约束只对 public surface 继续成立；runtime 内部可以（MAY）使用 Browser-Assisted Search。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. Brave key 存在且 Brave 成功时，`builtin://web.search` 必须只尝试 Brave。
2. Brave 失败且 DuckDuckGo HTTP Search 成功时，`provider_used=duckduckgo_html` 且 `degraded=true`。
3. DuckDuckGo HTML 入口返回门户页时，运行时必须继续尝试 Lite 入口。
4. Brave 与 DuckDuckGo HTTP Search 全失败时，运行时必须允许进入 Browser-Assisted Search。
5. Browser-Assisted Search 落到门户页时，可以（MAY）自动补提一次 query；成功后必须返回结果。
6. Browser-Assisted Search 补提一次后仍无结果时，必须稳定返回 `E_WEB_SEARCH_NO_RESULTS`。
7. `provider_attempts` 必须保留 Brave、DuckDuckGo 与 Browser-Assisted Search 的完整失败链。
8. 严格健康门下，全部 provider unhealthy 时，`web_search` 必须从 `effective_capabilities` 中裁掉。
9. 严格健康门下，Brave 与 DuckDuckGo HTTP Search 不可用但 Browser-Assisted Search healthy 时，`web_search` 仍必须可用。
10. Prompt 不得暴露 `provider=`、`provider_variant=`、`builtin://browseruse.search` 或 `playwright_search`。
11. 发布门测试不得依赖公网真实搜索结果；必须（MUST）使用本地 fixture 或 mock。
12. 当 provider 返回“归档页 + 可用页”混合候选时，`builtin://web.search` 必须保留 provider 规范化后的原始候选顺序；候选适配由后续 browse 编排负责。
13. 当第一个候选 browse 失败、后续候选 browse 成功时，系统必须通过普通 `search + browse` 编排恢复，而不是要求 search 层 topic-aware 重排。
14. 当 search 已成功返回候选但 browse 预算耗尽时，失败摘要必须映射到普通外部证据候选耗尽，而不是 `E_WEB_SEARCH_NO_RESULTS`。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
