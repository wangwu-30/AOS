# ADR-0012 运行时策略包吸收产品面策略（Runtime Policy Bundle for Product-Plane Policies）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-10
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_051_RUNTIME_POLICY_BUNDLE.md`

## 背景（Context）

当前 canonical runtime 已经收敛出 `AgentProfileV2`、`SoulProfileV2`、`ContextGraphV1`、`PromptCompilationV1` 与 `EffectiveRuntimeCapabilitiesV1`，但仍缺少一层产品面默认策略，用来承接：

- 用户偏好画像（User Preference Profile）
- 执行模式策略（Execution Mode Policy）
- 数据敏感度策略（Data Sensitivity Policy）
- 主动策略（Proactivity Policy）

若继续把这些信息散落在 prompt、聊天上下文或 ad-hoc CLI 参数中，会出现：

- 用户偏好无法形成稳定、可审计的默认值
- “省钱优先 / 平衡 / 高质量 / 闲聊优先”无法进入统一 model routing
- 主动性与数据敏感度只有理念，没有 runtime 对象
- 为吸收产品面策略而重新发明一套 router/runtime 的风险上升

## 决策（Decision）

采用 `RuntimePolicyBundleV1` 作为产品面策略的唯一运行时入口，并冻结以下决定：

- Runtime Policy Bundle 必须（MUST）按 `workspace_id` 装配，作为工作区级默认策略对象。
- Runtime Policy Bundle 不得（MUST NOT）新增 `ExecuteRequest` 顶层字段；必须通过 query 产物、context planes 与 `policy_context` 增量透传。
- Query Compile 必须（MUST）消费 `RuntimePolicyBundleV1`，并至少完成：
  - `communication_style -> communication_plane / active_style_pack`
  - `response_language -> prompt compilation default`
  - `default_mode -> model_routing_policy.execution_mode`
  - `risk_tolerance / default_level / proactivity_enabled -> 可审计 query facts`
- 数据敏感度与主动性首版只作为声明性策略对象进入 runtime；不得（MUST NOT）在阈值、权限与调度治理冻结前直接触发强主动 side effect。
- Runtime Policy Bundle 只负责产品面默认值；不得（MUST NOT）覆盖 `AgentProfileV2.execution_axioms`、`SoulProfileV2.global_soul` 或 `EffectiveRuntimeCapabilitiesV1` 的 canonical 语义。

## 备选方案（Alternatives）

1. 直接把用户偏好塞进 `AgentProfileV2` 或 `SoulProfileV2`
   - 不采纳。
   - 原因：会把执行公理/身份语义与产品面偏好混在一起，破坏对象边界。

2. 新开一套产品 router/executor 层
   - 不采纳。
   - 原因：会重新引入双 runtime，与 canonical prompt profiles 冲突。

3. 只在 prompt 或 memory 中临时拼接偏好
   - 不采纳。
   - 原因：缺乏 schema、默认值、可审计性与兼容治理。

## 取舍（Tradeoffs）

- 代价：
  - 运行时对象增加一层 bundle/store；
  - Query Compile 需要新增默认值装配逻辑。
- 收益：
  - 产品面策略进入 canonical runtime，而不是停留在文档理念；
  - 用户偏好与 model routing 之间出现稳定中间层；
  - 为后续主动性、敏感度与用户控制面保留统一扩展点。

## 后果（Consequences）

- repo 需要提供默认 `RuntimePolicyBundleV1` 配置。
- Query Compile 产物需要显式包含 runtime policy bundle 或等价摘要。
- 工作区可通过 data override 提供局部 policy bundle，而无需改动 agent/soul profile。
- 后续若扩展强主动行为、外发裁决或用户 UI 控制面，应优先挂在 Runtime Policy Bundle，而不是新增并行 runtime。

## 风险与缓解（Risks & Mitigations）

- 风险：Runtime Policy Bundle 与 `AgentProfileV2.policy_defaults` 语义重叠。
  - 缓解：前者只承接产品面偏好，后者仍保持 agent/runtime 默认执行政策。

- 风险：主动性策略过早变成自动 side effect。
  - 缓解：首版仅做声明性投影；任何主动外发都必须后续附规范与验收门。

- 风险：工作区 bundle 损坏导致主链失败。
  - 缓解：无效 bundle 回退默认 bundle，不新增阻断主链错误码。

## 可观测与验收（Metrics & Acceptance）

- Query Compile 结果中必须能观察到：
  - `execution_mode`
  - `risk_tolerance`
  - `data_default_level`
  - `active_style_pack`
  - `active_response_language`
- 单元测试必须覆盖：
  - repo 默认 bundle 回退
  - workspace override 生效
  - 非法 `default_mode` 被拒绝并回退

## 后续工作（Follow-ups）

- 将 `RuntimeSnapshotV1` 与 follow-up / scheduler 回流接上 Runtime Policy Bundle 的跨轮偏好继承。
- 将 `DataSensitivityPolicy` 与 `PolicyEngine` 做硬裁决对接。
- 将 `ProactivityPolicy` 与调度/通知阈值治理对接。
