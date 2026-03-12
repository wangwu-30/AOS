# ADR-0019 显式调研工具与有界外部证据编排（Explicit Research Tool and Bounded External Evidence Orchestration）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-12
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_051_RUNTIME_POLICY_BUNDLE.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`

## 背景（Context）

项目此前同时存在两类偏差：

- `web.search` 曾承载 topic-aware 结果调优语义，试图在搜索层直接修补特定主题的来源可用性问题；
- 普通外部信息查询与深入调研查询之间缺少清晰 public contract，导致 “普通 search/browse 失败后是否自动升级 research doctrine” 的边界不稳定。

这两类偏差会带来三个问题：

- 搜索原语（Search Primitive）的语义被主题补丁污染，难以审计与复用；
- 普通查询失败容易被误表述为“search runtime 需要修复”，而实际问题常常是候选来源不可读或预算耗尽；
- 研究教义（Research Doctrine）容易从内部方法论演变成隐式自动兜底，破坏显式工具边界。

## 决策（Decision）

冻结以下决定：

- `builtin://web.search` 必须（MUST）保持通用候选发现原语，不再承载 topic-aware 重排、过滤或 provider 拒收。
- 普通外部信息查询必须（MUST）在查询门控运行时（Query-Gated Runtime）内通过有界外部证据编排（Bounded External Evidence Orchestration）完成，即多轮 `web.search + web.browse` 组合。
- 普通外部证据路径的预算默认值必须（MUST）由 `RuntimePolicyBundleV1.external_evidence_policy` 提供，并允许单次请求覆盖。
- 显式调研（Explicit Research）必须（MUST）通过新增 public capability `research_run` 与 operator `builtin://research.run` 暴露。
- `builtin://research.run` 只能（MUST）在用户明确表达深入调研、调研报告、多来源对比、带引用结论或等价结构化 research 意图时启用。
- 普通 `search + browse` 失败、候选耗尽或预算耗尽不得（MUST NOT）自动升级为 `builtin://research.run`。
- 失败语义必须（MUST）稳定区分：
  - search runtime unavailable
  - ordinary external evidence candidate/source exhausted
  - explicit research blocked or incomplete

## 备选方案（Alternatives）

1. 继续在 `web.search` 层增加主题定制补丁
   - 不采纳。
   - 原因：会持续污染搜索原语合同，且每个主题都可能引入新的站点特判。

2. 普通查询失败后自动升级到 research doctrine
   - 不采纳。
   - 原因：会把调研成本和报告语义隐式扩散到普通查询，破坏用户意图与 operator 边界。

3. 为调研新建第二套 runtime
   - 不采纳。
   - 原因：与 single runtime 原则冲突，并复制 planner / verifier / consumer 语义。

## 取舍（Tradeoffs）

- 代价：
  - Assistant Loop 需要承担候选消费编排，而不能把问题全部推给 `web.search`；
  - capability schema、policy bundle 与 prompt surface 需要新增 `research_run` 与预算策略；
  - verifier / communicator 需要处理更细的失败分类。
- 收益：
  - `web.search` 重新收口为稳定、可审计的通用原语；
  - 普通查询与深入调研的用户意图边界清晰；
  - 失败解释更贴近真实根因，避免把来源不可读误诊为 search runtime defect。

## 后果（Consequences）

- topic-specific `search_weather` 一类 public tool 不再允许存在。
- `builtin://web.search` 的成功结果不再为了特定主题改变 provider 接纳逻辑。
- 普通外部查询会在预算内重试更多候选 URL，但不会自动生成调研报告。
- `builtin://research.run` 成为唯一显式调研入口，并要求成功时交付摘要、报告、引用与来源。

## 风险与缓解（Risks & Mitigations）

- 风险：普通查询的多轮 `search + browse` 编排导致 runtime 步数增加。
  - 缓解：通过 `external_evidence_policy` 设定有界预算，并允许单次请求收紧或放宽。

- 风险：显式 research capability 被误暴露给普通查询。
  - 缓解：要求 `research_required=true` 与 `research_run` capability 同时成立后才允许 prompt 暴露。

- 风险：显式 research 输出未被 verifier / communicator 统一消费。
  - 缓解：要求 research 输出进入结构化研究事实或研究证据包（Research Evidence Pack）收口。

## 可观测与验收（Metrics & Acceptance）

- `tests.test_thread047_runtime_capabilities_and_web` 必须（MUST）证明：
  - `web.search` 不再做 topic-aware reranking；
  - `builtin://research.run` 成功时产出摘要、报告与引用。
- `tests.test_thread045_query_gated_runtime` 必须（MUST）证明：
  - 普通查询在默认预算内执行多轮 `search + browse`；
  - 首个候选失败、后续候选成功时系统继续恢复；
  - 候选耗尽时映射为 `external_evidence_candidate_exhausted`；
  - 普通查询不会自动升级为 explicit research。
- `tests.test_thread030_capability_schema` 必须（MUST）证明：
  - `research_run` 缺失时 `builtin://research.run` 被拒绝。

## 关联与替代（Relations）

- 本 ADR 不替代 ADR-0014 关于隐藏式 Browser-Assisted Search 与严格健康门的结论。
- 本 ADR 收紧了 ADR-0013 / ADR-0014 之后仍残留的两类模糊点：
  - `web.search` 不再允许 topic-aware 结果补丁；
  - ordinary external evidence 与 explicit research 的 public boundary 改为显式 capability + operator。
