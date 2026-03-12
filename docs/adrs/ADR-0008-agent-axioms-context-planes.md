# ADR-0008 代理行为公理与上下文平面分层（Agent Axioms and Context Planes）

- 状态（Status）：Proposed
- 日期（Date）：2026-03-07
- 相关规范（Related Specs）：`docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`、`docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`

## 背景（Context）

当前系统已经具备查询门控运行时（Query-Gated Runtime）、上下文编译（Context Compiler）与复盘闭环，但仍缺少一层稳定的“代理宪法”：
- 哪些原则属于长期稳定的行为公理（Behavior Axiom）
- 哪些要求属于会变化的现实约束（Reality Constraint）
- 执行上下文、沟通上下文、失败经验上下文是否应该长期混在同一个 prompt 中
- 代理能力是否应该被近似为工具列表，还是应先解析为技能（Skill）及其组合

若不把这些边界显式化，系统会持续出现：
- 角色设定污染执行 prompt
- 历史失败经验无法进入下一轮避免重复踩坑
- 能力选择直接退化到“工具列表驱动”
- 新增现实约束时对原有行为原则的覆盖缺乏审计

## 决策（Decision）

采用“行为公理 + 现实约束 + 上下文平面 + 假设闭环”的分层模型：

- 引入 AgentProfileV1：
  - `axioms[]` 表示长期稳定、优先级最高的行为公理
  - `reality_constraints[]` 表示当前生效、允许变化的现实约束
  - 运行时按 `agent_id` 加载对应 profile，缺失时回退默认 profile
  - 公理治理受元公理（Meta-Axioms）约束：系统必须承认变化存在，且公理修订必须由约束压力驱动
- 引入 ContextPlanePackV1：
  - `execution_plane`
  - `communication_plane`
  - `retrospective_plane`
  - `constraint_plane`
  - 允许缓存稳定平面（communication/retrospective/constraint），但 execution_plane 必须按当前任务重建
- 采用 `skill-first` 能力解析：
  - 优先技能（Skill）
  - 次选技能组合
  - 最后才退化到工具组合
- 强制每一轮非平凡执行写入 HypothesisRecordV1，落实“假设 -> 验证 -> 修正”
- 当现实约束和失败压力达到阈值时，生成 `axiom_review_candidate`，显式暴露 `meta_axioms`、`pressure` 与 `recommended_action`，提示是否需要重审公理层

## 备选方案（Alternatives）

1. 继续把角色、约束、失败经验全部拼进一个长期 prompt：
   - 实现最省事，但边界混乱，难以治理与缓存。
2. 只保留 Query-Gated Runtime，不增加 AgentProfile 层：
   - 能继续运行，但缺少“稳定原则 vs 动态约束”的显式模型。
3. 将能力简单视为工具清单：
   - 实现直接，但会弱化技能复用与组合规划能力。

## 取舍（Tradeoffs）

- 增加了一个配置/编译层，短期内实现复杂度上升。
- 换来的好处是：
  - 上下文可按平面缓存与失效
  - 失败经验可结构化进入下一轮
  - 角色润色不再污染执行上下文
  - 新增约束对行为原则的影响可审计

## 后果（Consequences）

- 后续 Query Compile 需要读取 AgentProfileV1 与 ContextPlanePackV1。
- Context Compiler 与 Memory Pipeline 后续应对齐“上下文平面”装配语义。
- 技能注册与能力解析逻辑后续应增加 `skill-first` 的显式证据与日志。

## 风险与缓解（Risks & Mitigations）

- 风险：公理定义过多，最终退化为另一组动态约束。
- 缓解：规范要求 `axioms` 数量上限为 `12`，并要求长期稳定。

- 风险：把“公理可修订”误实现成“任何压力都可即时改公理”，导致运行时漂移。
- 缓解：公理修订必须由 `constraint pressure` 与 `failure pressure` 的结构化证据触发，并保留可回放候选记录。

- 风险：上下文平面过细，导致实现成本高或装配变慢。
- 缓解：MVP 只冻结 4 个平面；后续扩展必须附带净收益说明。

- 风险：`skill-first` 误伤某些直接工具更优的场景。
- 缓解：允许在无技能或技能组合不足时退化到工具组合，但必须保留可观测决策。

## 可观测与验收（Metrics & Acceptance）

- 能在一次执行记录中区分：
  - 生效的行为公理
  - 生效的现实约束
  - 当前使用的上下文平面
  - 当前选择的是技能还是工具组合
- 能在一次执行记录中看到是否触发 `axiom_review_candidate`、触发原因与建议动作
- 已失败的假设能在下一轮被读取并避免无依据重复尝试。

## 后续工作（Follow-ups）

- 在运行时引入 AgentProfile/ContextPlanePack 的实际装配实现。
- 在 Query 编译与 Loop 阶段补充 HypothesisRecordV1 写入。
- 在技能解析链路中补充 `skill-first` 决策 evidence。
