# ADR-0013 搜索原语与单 Runtime 收口（Search Primitive and Single Runtime Cleanup）

- 状态（Status）：Accepted；其中关于 `web.search` 禁止 Playwright 搜索 fallback 的子结论已被 `ADR-0014-hidden-browser-assisted-search-and-strict-health-gate.md` 部分替代
- 日期（Date）：2026-03-10
- 相关规范（Related Specs）：
  - `docs/specs/MVP_041_PA_WEBHOOK_SERVER.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_051_RUNTIME_POLICY_BUNDLE.md`

## 背景（Context）

当前项目已经把现役主链收敛到 `Canonical Task Ingress -> Query Compile -> Assistant Loop -> Verify -> Consumer Adapter`，但仍存在两类偏差：

- `builtin://web.search` 仍夹带浏览器 fallback 语义，导致“搜索原语（Search Primitive）”与“浏览验证（Browse Verification）”边界混乱。
- webhook / polling / demo 等现役路径仍有少量 `EV1Runtime` 依赖或命名残留，削弱了 single runtime 叙事与发布门可信度。

同时，外部研究型任务需要多轮 `search -> browse -> compare -> cite`，但这些能力应该进入现有 canonical runtime，而不是再长出第二套 runtime。

## 决策（Decision）

冻结以下决定：

- `builtin://web.search` 必须（MUST）回归纯搜索原语，只负责候选结果或稳定无结果/失败。
- `builtin://web.search` 的 provider chain 必须（MUST）是 `Brave Search API -> DuckDuckGo HTML Search`；不得（MUST NOT）再把 Playwright 作为搜索 fallback。
- Playwright 只允许（MUST）用于 `builtin://web.browse` 与研究教义（Research Doctrine）内部的页面验证。
- 多轮 `search -> browse -> compare -> cite` 必须（MUST）通过 `ResearchDoctrineV1` 在同一 canonical runtime 内组织。
- Query Compile 必须（MUST）显式生成 `research_required`、`research_depth`、`selected_doctrine_pack`、`evidence_expectation`、`citation_required` 等研究事实。
- `browser_research_mode` 与 `self_adversarial_mode` 必须（MUST）作为 doctrine packs 下沉到 `SoulProfileV2` / prompt compilation，而不是新增并行 planner/runtime。
- webhook、polling、CLI demo 等现役路径不得（MUST NOT）再导入 `EV1Runtime`；若保留 `ev1`，只能（MAY）作为兼容响应别名或 legacy 隔离对象。

## 备选方案（Alternatives）

1. 保留 `web.search = Brave -> Playwright`
   - 不采纳。
   - 原因：把搜索原语与浏览器交互混为一谈，失败语义不稳定，且与 research doctrine 分层冲突。

2. 新建一套“研究 runtime”处理多步外部研究
   - 不采纳。
   - 原因：会破坏 single runtime 目标，并复制 planner/executor/verifier 语义。

3. 彻底删除 EV1 所有代码与测试
   - 暂不采纳。
   - 原因：历史线程与 regression 仍需要 legacy 隔离区；当前目标是清出现役路径，而不是一次性删除全部历史债。

## 取舍（Tradeoffs）

- 代价：
  - search / browse 代码与测试要重写；
  - doctrine 与 query compile 字段增多；
  - 兼容 alias 与 legacy 边界要额外维护。
- 收益：
  - 搜索、浏览、研究三者边界更清晰；
  - single runtime 叙事与代码路径一致；
  - verifier / communicator 可消费结构化研究证据包，便于审计与 blocker 解释。

## 后果（Consequences）

- `web.search` 失败时会保留 provider attempts，但不再执行浏览器交互补救。
- 研究任务会显式进入 `browser_research_mode` 或 `self_adversarial_mode`，并生成研究证据包（Research Evidence Pack）。
- 现役 CLI/service/help text 会改为 canonical runtime 口径。
- `RuntimePolicyBundleV1` 明确只承接产品面偏好，不承接 research/adversarial 算法。

## 风险与缓解（Risks & Mitigations）

- 风险：DuckDuckGo HTML Search 页面结构波动，导致结果提取脆弱。
  - 缓解：将门户页、空壳页稳定归类为 `E_WEB_SEARCH_NO_RESULTS`，并保留 provider attempts 供 communicator 解释。

- 风险：research doctrine 变相长成第二套 runtime。
  - 缓解：所有 research/adversarial 行为只能通过现有 prompt profiles、ActionGraph 与 builtin operators 实现。

- 风险：现役路径清理 EV1 时破坏兼容响应。
  - 缓解：保留 `ev1` 作为顶层响应别名，不保留 EV1 作为执行入口。

## 可观测与验收（Metrics & Acceptance）

- `tests.test_thread047_runtime_capabilities_and_web` 必须（MUST）证明：
  - `web.search` fallback 不触发 Playwright browse
  - DuckDuckGo 门户页稳定映射为 `E_WEB_SEARCH_NO_RESULTS`
- `tests.test_thread045_query_gated_runtime` 必须（MUST）证明：
  - quick lookup 与 research doctrine 被区分
  - research 任务生成 `ResearchEvidencePackV1`
  - 观察学习候选（Observation Learning Candidate）只以候选形式产出
- `tests.test_thread041_pa_webhook_server`、`tests.test_thread044_pa_polling` 与 `tests.test_thread040_pa_demo_visible_roundtrip` 必须（MUST）继续通过，且现役入口不再导入 `EV1Runtime`。

## 后续工作（Follow-ups）

- 清理 guides / README 中仍描述现役 EV1 主链的内容。
- 继续收掉 legacy EV1 在 release gate 外的残余演示与帮助文本。
- 为 research doctrine 补预算上限、source diversity 与 HITL 升级阈值的更细规范。
