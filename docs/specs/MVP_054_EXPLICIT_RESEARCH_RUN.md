# MVP_054_EXPLICIT_RESEARCH_RUN

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_054
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_051_RUNTIME_POLICY_BUNDLE.md`

## 目的（Purpose）

定义显式调研运行（Explicit Research Run）的 public capability 与 operator 合同，确保普通外部信息查询继续使用通用 `web.search + web.browse` 编排，而显式调研请求统一经 `builtin://research.run` 生成调研报告（Research Report）、摘要与引用。

## 范围（Scope）

本规范覆盖：
- capability：`research_run`
- operator：`builtin://research.run`
- 输入输出合同
- 错误码、默认值、边界条件、兼容策略、测试与验收

本规范不覆盖：
- `builtin://web.search` provider chain 细节
- `builtin://web.browse` 页面抽取细节
- 非显式调研任务的 ordinary search/browse 编排

## 接口/数据结构（Interfaces/Data）

### ResearchRunInputV1（MUST）

```json
{
  "objective": "string",
  "depth": "standard",
  "report_format": "markdown",
  "min_sources": 3
}
```

默认值（MUST）：
- `depth = "standard"`
- `report_format = "markdown"`
- `min_sources = 3`

约束（MUST）：
- `objective` 必须（MUST）为非空字符串。
- `depth` 只能（MUST）为 `standard|deep`；非法值必须（MUST）规范化为 `standard`。
- `report_format` 当前只能（MUST）为 `markdown`；其他值必须（MUST）fail-closed。
- `min_sources` 必须（MUST）被限制在 `1..8`；非整数或非正值必须（MUST）回退到默认值 `3`。

### ResearchRunOutputV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "ok": true,
  "objective": "string",
  "depth": "standard|deep",
  "report_format": "markdown",
  "min_sources": 3,
  "summary": "string",
  "report": "string",
  "citations": [
    {
      "id": "[1]",
      "title": "string",
      "url": "string"
    }
  ],
  "sources": [
    {
      "title": "string",
      "url": "string",
      "excerpt": "string",
      "search_query": "string",
      "search_rank": 1
    }
  ],
  "visited_sources": [
    {
      "url": "string",
      "title": "string",
      "status": "accepted|failed",
      "search_query": "string",
      "search_rank": 1,
      "error_code": "string"
    }
  ],
  "search_queries": [
    {
      "query": "string",
      "provider_used": "string",
      "result_count": 5,
      "degraded": false
    }
  ],
  "provider_attempts": [
    {
      "provider": "string",
      "variant": "string",
      "status": "ok|failed",
      "error_code": "string",
      "detail": "string"
    }
  ],
  "notices": ["string"]
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `ok = true`
- `depth = "standard"` 若输入缺失或非法
- `report_format = "markdown"`

约束（MUST）：
- 成功输出必须（MUST）同时包含 `summary`、`report`、`citations` 与 `sources`。
- 成功输出中的 `sources` 数量必须（MUST）大于等于 `min_sources`。
- `report` 必须（MUST）为 Markdown 文本。
- `citations` 中的每个条目必须（MUST）至少包含 `id` 与 `url`。
- `visited_sources`、`search_queries`、`provider_attempts` 与 `notices` 可以（MAY）作为审计字段扩展，但成功输出不得（MUST NOT）缺失四个核心交付字段。

## 语义（Semantics）

### Capability / Operator Gating（MUST）

- `builtin://research.run` 只能（MUST）在 `research_run` 已进入 `effective_capabilities` 时执行。
- `research_run` 必须（MUST）依赖 `web_search + web_browse` 同时可用。
- Query Compile 只有在 `research_required=true` 时才可以（MUST）向模型暴露 `builtin://research.run`。
- 普通外部信息查询不得（MUST NOT）因为 `web.search` / `web.browse` 失败、候选耗尽或预算耗尽而自动升级为 `builtin://research.run`。

### Internal Execution Boundary（MUST）

- `builtin://research.run` 可以（MAY）在内部复用通用 `web.search` provider chain 与 `web.browse` 页面抽取能力。
- `builtin://research.run` 的内部实现不得（MUST NOT）扩张 `builtin://web.search` 的 public 语义。
- `builtin://research.run` 成功时必须（MUST）同时交付：
  - 面向用户的摘要
  - Markdown 调研报告
  - 有界引用集合
  - 已接受来源列表
- `builtin://research.run` 的内部搜索与浏览轨迹必须（MUST）保留为结构化审计字段，供 verifier / communicator 消费。

### Research Report Contract（MUST）

- 调研报告（Research Report）必须（MUST）可直接交付给用户。
- 调研报告必须（MUST）至少包含：
  - 目标
  - 来源摘录或等价证据摘要
  - 引用列表
- `summary` 必须（MUST）是 `report` 的简洁摘要，而不是另一个空壳字段。
- `citations` 与 `sources` 必须（MUST）对应到实际已读来源，而不是仅来自搜索结果标题。

## 错误码（Error Codes）

- `E_RESEARCH_SEARCH_UNAVAILABLE`
- `E_RESEARCH_INCOMPLETE`
- `E_CAPABILITY_DENY`
- `E_EXECUTION_FAILED`

错误细化（MUST）：
- 当未取得任何可用搜索候选时，必须（MUST）返回 `E_RESEARCH_SEARCH_UNAVAILABLE`。
- 当已执行有界搜索/浏览但可接受来源数仍低于 `min_sources` 时，必须（MUST）返回 `E_RESEARCH_INCOMPLETE`。
- 当输入非法且当前实现未提供更细 validation code 时，可以（MAY）回退到 `E_EXECUTION_FAILED`，但不得（MUST NOT）伪造成功结果。

## 边界条件（Boundary Conditions）

- 当 `allow_network_egress=false` 时，`research_run` 必须（MUST）不可用。
- 当 `web_search` 或 `web_browse` 任一被严格健康门裁剪时，`research_run` 必须（MUST）不可用。
- `builtin://research.run` 不得（MUST NOT）在 `research_required=false` 的普通查询里作为 prompt-visible operator。
- 成功输出不得（MUST NOT）出现 `sources=[]`、`citations=[]` 或空 `report`。
- `report_format` 当前不得（MUST NOT）接受 `markdown` 之外的值。

## 兼容策略（Compatibility）

- `builtin://research.run` 是新增 public operator；不得（MUST NOT）替代 `builtin://web.search` 或 `builtin://web.browse` 的普通查询职责。
- 内部 provider 名称、provider variant 与浏览器 fallback 只允许（MUST）出现在审计对象中；不得（MUST NOT）被声明为新的 public operator。
- 旧的“普通查询失败后自动 research doctrine 升级”语义不再兼容。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. 当 `research_run` capability 缺失时，`builtin://research.run` 必须被拒绝。
2. 当 `research_required=true` 且运行时具备 `web_search + web_browse` 时，prompt 必须暴露 `builtin://research.run(objective, depth?, report_format?, min_sources?)`。
3. `builtin://research.run` 成功时必须返回 `summary + report + citations + sources`。
4. 普通天气/新闻/价格类查询不得自动调用 `builtin://research.run`。
5. 普通 `search + browse` 预算耗尽时，不得自动切换为 `builtin://research.run`。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread030_capability_schema -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
