# ADR-0009 任务系统导向的代理操作模型（Task-System-Oriented Agent Operating Model）

- 状态（Status）：Proposed
- 日期（Date）：2026-03-07
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_010_MEMORY.md`
  - `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
  - `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`
  - `docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md`

## 背景（Context）

当前仓库已经具备查询门控运行时（Query-Gated Runtime）、代理行为公理（Agent Axioms）、多轮对话状态机（Dialog State Machine）与记忆系统（Memory System）的基础能力，但系统边界仍存在以下模糊点：

- 入口仍容易被理解为“聊天请求”，而非“待交付任务”
- 多个外部接入面容易被误读为“多个 runtime 入口”，而不是同一个 runtime 的不同 adapter
- 原始用户输入（Raw Input）与运行时执行对象之间缺少明确编译边界
- 长对话仍可能退化为 transcript 堆叠，而不是状态机 + 证据引用
- 记忆已有 L0/L1/L2 存储分层，但缺少“工作/情景/语义/程序性”认知语义口径
- 失败复盘虽已存在，但尚未被统一定义为避免重复算力浪费的核心机制
- 用户可见过程状态缺少统一契约，复杂任务可能出现“默默执行、默默失败”

若继续以“聊天轮次 + prompt 堆叠”隐式驱动系统，后续能力增长会导致：

- 任务目标与话术风格混写
- 一句简短回复触发歧义执行
- 检索与写入优先级失衡
- 复盘经验无法稳定回流到下一轮执行
- 行为公理与现实约束的冲突无法被审计

## 决策（Decision）

采用“任务系统导向（Task-System-Oriented）”作为 AgentOS Next 的上层操作模型，并冻结以下决定：

- Agent 必须（MUST）被定义为任务系统（Task System），而不是聊天机器人（Chatbot）；对话仅作为入口协议。
- 内核必须（MUST）收敛为单一运行时（Single Runtime）与单一规范任务入口（Canonical Task Ingress）；不得演化为多套并行 runtime。
- CLI、HTTP、Scheduler、Polling、Channel 等只能作为提交适配器（Submitter Adapter）；CLI stdout、Webhook、IM Reply、Artifact Store 等只能作为消费适配器（Consumer Adapter）。
- Submitter Adapter 与 Consumer Adapter 不得（MUST NOT）持有独立的验收闭环、任务状态机或记忆写入语义。
- 运行时必须（MUST）先把原始用户输入编译为任务信封（Task Envelope），再进入查询编译（Query Compile）与执行链路。
- 运行时必须（MUST）在计划前先求解一次解决方案查询（Solution Query），用于从状态、继续合同与本地操作符线索推导“先怎么解决”，不得直接从原始文本展开计划。
- Prompt 在内部必须（MUST）被视为结构化查询（Structured Query）与最小上下文信封（Minimal Context Envelope）的组合，而不是承载全部状态的长篇说明书。
- 对 `开始 / OK / 继续 / 结果呢` 一类上下文依赖输入，系统必须（MUST）优先使用固定选项 + 可选备注的意图恢复层，而不是直接把原文交给执行内核猜测。
- 非平凡任务必须（MUST）绑定交付合同（Delivery Contract）或等价对象，用于定义 done、verify、repair 与用户可见进度语义。
- 长任务必须（MUST）通过状态机（State Machine）与证据引用（Evidence Reference）维护，不得依赖“全历史 transcript 持续塞给模型”。
- 记忆系统必须（MUST）同时支持两种视图：
  - 存储分层：L0/L1/L2
  - 认知分层：工作记忆（Working Memory）、情景记忆（Situational Memory）、语义记忆（Semantic Memory）、程序性记忆（Procedural Memory）
- 检索优先（Retrieval First）必须（MUST）优先于常态化写入；非显式要求下，运行时应（SHOULD）先取对信息，再决定是否写入。
- 执行闭环必须（MUST）绑定验收标准（Acceptance Criteria）；未达标时进入修正循环，预算耗尽或不可解时终止并解释。
- 成功路径必须（MUST）沉淀 SOP；失败路径必须（MUST）沉淀 anti-pattern 或 filter，用于避免重复试错。
- 对用户可见的复杂任务流程必须（MUST）采用 `ack -> progress -> blocker -> done` 的有限状态契约。
- 当现实约束压力与失败模式累计到阈值时，运行时应该（SHOULD）生成公理修订候选（Axiom Revision Candidate），而不是仅在实现层继续堆补丁。
- 公理比约束更稳定，但不得（MUST NOT）被视为永久不变；当约束压力长期累积时，系统必须（MUST）允许受治理的公理修订候选进入复审链。

## 备选方案（Alternatives）

1. 保持“聊天导向”模型，只在现有 prompt 上追加规则：
   - 改动最小，但无法建立清晰的接口边界与状态机语义。
2. 只增加任务编排，不引入任务信封：
   - 能改善一部分执行组织，但原始输入歧义仍会泄漏到运行时。
3. 只扩展记忆系统，不调整运行时与交付模型：
   - 记忆会变复杂，但任务系统核心仍然是聊天驱动。

## 取舍（Tradeoffs）

- 引入任务信封、交付状态与认知分层后，概念数量上升，短期实现成本更高。
- 需要在 Query Compile、Dialog State Machine、Memory 与 Retrospective 之间新增对齐工作。
- 换来的收益是：
  - 执行对象更稳定
  - 长对话更可审计
  - 检索与写入的优先级更清晰
  - 失败经验可以结构化复用
  - 用户对复杂任务的过程感知更一致

## 后果（Consequences）

- Query-Gated Runtime 后续需要显式生成 `TaskEnvelopeV1` 或等价结构。
- Query-Gated Runtime 后续需要显式生成 `SolutionQueryV1` 或等价结构，并要求 planner 与 step expansion 以其为前置。
- Query-Gated Runtime 后续需要显式生成 `DeliveryContractV1` 或等价结构，并在 Verify 阶段绑定验收闭环。
- scheduler、CLI、polling、channel、HTTP 等外部接入面后续需要收敛为 Submitter Adapter / Consumer Adapter，而不是继续扩散 runtime 分叉。
- Agent Axioms 规范需要承接“任务优先、最小上下文、过程可见”的行为约束。
- Memory 规范需要在保持 L0/L1/L2 兼容的同时，引入认知分层语义与冲突治理。
- Dialog State Machine 或等价运行时事件模型需要能重建 `ack/progress/blocker/done`。
- Self-Improvement Loop 后续应读取 SOP / anti-pattern 产物，而不是只依赖统计信号。

## 风险与缓解（Risks & Mitigations）

- 风险：任务信封定义过重，重新演变成另一种 prompt 膨胀。
  - 缓解：规范强制最小字段集与最小上下文信封，不允许无边界扩张。

- 风险：过程可见要求导致用户侧状态噪音过多。
  - 缓解：只冻结有限状态 `ack/progress/blocker/done`，并要求状态变化才允许更新。

- 风险：认知分层与存储分层并存，增加实现复杂度。
  - 缓解：规范明确认知分层是语义视图，L0/L1/L2 仍作为底层兼容存储映射。

- 风险：程序性记忆沉淀不严，导致错误 SOP 固化。
  - 缓解：只有通过验收或高置信失败复盘的结果才允许升格为程序性记忆。

- 风险：约束不断增加而公理层长期不复审，最终让系统退化成“补丁集合”。
  - 缓解：把元公理（Meta-Axioms）、约束压力（Constraint Pressure）与公理修订候选（Axiom Revision Candidate）纳入可观测与验收范围。

## 可观测与验收（Metrics & Acceptance）

必须能够在一次执行记录中区分并审计：

- 原始输入与任务信封
- 结构化查询与最小上下文信封
- 用户可见交付状态的变化
- 当前读取了哪些记忆层
- 当前沉淀了哪类 SOP / anti-pattern
- 当前是否触发公理修订候选

建议验收指标：

- prompt/context 平均体积下降
- 无证据断言比例下降
- 重复失败路径重试率下降
- 复杂任务未发出进度状态的比例接近 0
- 上下文依赖输入被正确绑定为固定意图选项的比例持续上升

## 后续工作（Follow-ups）

- 在 `MVP_045_QUERY_GATED_RUNTIME` 中补充 `TaskEnvelopeV1`、交付状态与 retrieval-first 语义。
- 在 `MVP_046_AGENT_AXIOMS_CONTEXT_PLANES` 中补充最小上下文信封与过程可见约束。
- 在 `MVP_010_MEMORY` 中补充认知分层、巩固/遗忘/冲突/澄清规则。
- 在 `MVP_014_DIALOG_STATE_MACHINE` 中补充用户可见交付状态的可回放事件模型。
