# Axiom Kernel 设计文档（Axiom Kernel Design）

> 创建时间：2026-03-07  
> 定位：作为项目级设计合成文档，统一“公理内核（Axiom Kernel）”“任务系统（Task System）”“分层记忆（Layered Memory）”与“可审计闭环（Auditable Loop）”。

---

## 1. 北极星（North Star）

本项目的目标不是构建“更会聊天的 AI”，而是构建一个**可推导、可执行、可审计、可自演进的代理操作系统（Agent Operating System）**。

系统的第一性定义如下：

- **Agent 不是聊天机器人，而是任务系统（Task System）**
- 对话只是提交协议（Submitter Protocol），不是内部状态模型
- 交付结果（delivery）优先于生成话术（wording）
- 运行时必须以公理（axioms）与约束（constraints）推导行为，而不是依赖超长 prompt 维持人格与流程
- 内核运行时必须收敛为单一规范任务入口（Canonical Task Ingress）与单一执行主链

终极方向保持不变：

> build something people can create anything on

---

## 2. 设计转向（Design Shift）

### 2.1 从聊天历史驱动，转向任务信封驱动

用户输入（User Input）不是 Agent 直接消费的运行时对象。  
运行时必须先把原始输入编译为**任务信封（Task Envelope）**，再进入查询编译（Query Compile）与执行。

这意味着：

- 一句 “OK” 不应直接进入执行层
- 长对话不应靠“全历史塞模型”维持语义
- 当前轮只保留当前任务所需的最小上下文信封（Minimal Context Envelope）

### 2.2 从多入口错觉，转向单一运行时 + 适配器

系统可以有很多任务来源，但不应有多套核心运行时。

- CLI、HTTP、Scheduler、Polling、IM Channel 都只是提交适配器（Submitter Adapter）
- CLI stdout、Webhook、IM Reply、Artifact Store 都只是消费适配器（Consumer Adapter）
- 适配器负责接入、归一化、投递与消费，不负责重新定义执行语义
- 所有适配器都必须（MUST）把输入收敛到同一个规范任务入口（Canonical Task Ingress）
- 验收、记忆、状态机、证据、预算都必须（MUST）只在单一运行时主链上生效

### 2.3 从 Prompt 工程，转向 Query 工程

Prompt 在系统内部不应被视为长篇说明书，而应被收敛为**结构化查询（Structured Query）**：

- 目标是什么
- 交付物是什么
- 验收标准是什么
- 当前已知事实是什么
- 当前不确定项是什么
- 下一步最小动作是什么

Prompt 的职责是启发执行，不是承载全部状态。

### 2.4 从文本堆叠，转向状态机与证据引用

多轮任务必须由状态机（State Machine）与证据引用（Evidence Reference）维护，而不是依赖不断增长的会话 transcript。

长任务主链路必须是：

1. `Submitter Adapter`
2. `Triage`
3. `Task Envelope Compile`
4. `Context Retrieval`
5. `Query Compile`
6. `Run`
7. `Verify`
8. `Loop or Stop`
9. `Retrospective`
10. `Consumer Adapter`

---

## 3. 公理内核（Axiom Kernel）

### 3.1 稳定公理（Stable Axioms）

建议冻结以下最小公理集：

- **AX1 Fact First**：没有证据的内容不得表述为事实
- **AX2 Task Delivery First**：优先完成任务与交付，而不是延展对话
- **AX3 Minimum Effective Action**：在满足目标前提下选择最少动作
- **AX4 Explicit Uncertainty**：未知必须显式标注
- **AX5 Hypothesis Loop**：未知通过“假设 -> 验证 -> 修正”处理
- **AX6 Accountable Output**：结论必须可追溯到证据或推理声明
- **AX7 Visible Execution**：复杂任务必须对用户暴露可理解的进度状态
- **AX8 Solution Query Before Plan**：面对具体问题时，必须先形成一次“怎么解决”的结构化思路，再展开计划与步骤

### 3.2 动态约束（Dynamic Constraints）

现实约束（Reality Constraints）负责描述会变化的边界，例如：

- 预算（Budget）
- 权限（Permission）
- 网络与外发（Network/Egress）
- 工作区边界（Workspace Boundary）
- 人审门禁（Human Approval）
- 渠道时延与回复要求（Channel SLA）

系统行为必须由：

`Axioms + Constraints + Evidence + Budget`

共同推导，而不是由某个“万能技能”隐式决定。

### 3.3 公理修订（Axiom Revision）

公理默认稳定，但不是永恒静态。  
当约束压力（constraint pressure）与失败模式（failure patterns）累计到阈值时，系统应生成**公理修订候选（Axiom Revision Candidate）**，而不是继续在实现层堆补丁。

### 3.4 元公理（Meta-Axioms）

除最基本的推导框架外，系统不得（MUST NOT）假设任何工作性规则永久不变。建议冻结以下元公理：

- **MAX1 Everything Is Revisable**：公理比约束更稳定，但不是永恒静态。
- **MAX2 Constraint Pressure Precedes Axiom Revision**：公理修订必须由约束压力与失败模式累计触发，而不是由临时偏好直接触发。
- **MAX3 Preserve Coherence During Revision**：公理修订必须可审计、可回放、可比较，禁止运行时无治理漂移。

### 3.5 约束压力模型（Constraint Pressure Model）

系统应该（SHOULD）至少跟踪以下压力信号：

- `count`：当前活跃现实约束数量
- `failure_pressure`：近期失败路径数量与重复频率
- `conflict`：约束之间、约束与现有公理之间的冲突度
- `cost`：为维持现有公理而新增的 prompt 复杂度、补丁复杂度与流程弯折度

当上述压力超过阈值时，运行时应该（SHOULD）生成 `Axiom Revision Candidate`，其中至少包含：

- 当前活跃公理集合
- 当前活跃约束集合
- 压力指标摘要
- 触发原因（reason codes）
- 建议动作（review / revise / defer）

---

## 4. 最小运行时对象（Minimal Runtime Objects）

### 4.1 任务信封（Task Envelope）

任务信封是 Agent 接收的最小执行对象，而不是原始用户文本。至少应包含：

- `objective`：目标
- `deliverable`：预期交付物
- `acceptance_criteria`：验收标准
- `known_facts`：已验证事实
- `ambiguities`：仍未消除的歧义
- `open_blockers`：阻断项
- `progress_policy`：对用户可见的进度策略

### 4.2 最小上下文信封（Minimal Context Envelope）

模型输入应尽量收敛为六段式：

1. `GOAL`
2. `DELIVERABLE`
3. `CONSTRAINTS`
4. `FACTS`
5. `HYPOTHESES`
6. `NEXT`

原则：

- 不在主 prompt 中展开大段 JSON schema
- 不注入无关旧对话
- 不把角色话术与执行约束混写
- 不把整段历史 transcript 当作执行上下文胶水

### 4.3 解决方案查询（Solution Query）

在计划（Plan）之前，运行时应先产出一个**解决方案查询（Solution Query）**，用于回答：

- 当前输入是否是新任务，还是对既有合同的继续/追问
- 当前问题是否应优先绑定既有 `pending_contract`
- 当前应优先走本地技能（local skill）还是 LLM 内部自查（llm self-check）
- 在没有关键证据时是否必须直接阻塞，而不是继续推测

设计原则：

- 解决方案查询必须优先读取 `L0 Snapshot` 与继续合同，而不是只看当前一句文本
- 面对具体问题时，应优先本地技能（local skill）；只有当本地路径不足时，才进入一次性 LLM 自查
- 计划必须从 `Solution Query` 派生，不得绕过它直接从原始输入拼步骤

### 4.4 规范任务入口（Canonical Task Ingress）

运行时内部只应存在一个规范任务入口（Canonical Task Ingress），用于接收：

- `Raw Input -> Task Envelope`
- `Task Envelope -> Structured Query`
- `Structured Query -> Run/Verify/Retrospective`

其含义是：

- 运行时只有一个
- 核心状态机只有一套
- 核心验收逻辑只有一套
- 外部来源越多，越应该加强 adapter，而不是复制 runtime

### 4.5 分层记忆（Layered Memory）

记忆必须分层，并支持巩固（Consolidation）、遗忘（Forgetting）、冲突并存（Conflict Coexistence）与澄清（Clarification）。

这里必须区分：

- **元信息（Meta Context）**：身份、公理、约束、操作符目录种子；不是记忆
- **L0 快照（L0 Snapshot）**：当前任务/会话的事件归约快照
- **L1 索引（L1 Index）**：用于检索的标签、目录、项目手册与导航层
- **L2 检索结果包（L2 Retrieved Evidence Pack）**：本轮真正进入推理的结果集合

在认知语义上：

- **工作记忆（Working Memory）** 主要映射到 `L0`
- **情景记忆（Situational Memory）** 主要映射到 `L1`
- **语义记忆（Semantic Memory）** 与 **程序性记忆（Procedural Memory）** 主要在 `L2` 中以被选中结果体现

运行时优先做好检索（retrieval）与裁剪（selection），再考虑复杂写入流水线。

在个人助理（Personal Assistant）场景，执行上下文应进一步收敛为胶囊装配（Capsule Assembly）：

- **全局胶囊（Global Capsule）**：长期身份、稳定偏好、长期 SOP
- **项目胶囊（Project Capsule）**：单项目目标、事实、阻塞、近期证据
- **回合态胶囊（Ephemeral Turn State）**：本轮输入、当前 blocker、当前 delivery state

执行 prompt 不应直接消费原始聊天记录，而应消费胶囊化摘要与证据引用。

同时，动作模型应收敛为：

- **操作符（Operator）**：最小可执行动作单元
- **技能（Skill）**：`composite operator + SOP`
- **策略处置（Policy Disposition）**：`allow | ask | deny`

能力标签（Capability Tag）只作为动作标签、路由标签与约束匹配输入，不应直接承担执行裁决。

### 4.6 任务需求推导（Task Requirement Derivation）

运行时不应先问“像不像复杂任务”，而应先问：

- 是否必须先观察工作区（workspace observation）
- 是否必须先获得外部证据（external evidence）
- 是否必须多步执行（multi-step）
- 在没有证据时是否禁止推测性交付（forbid speculation without evidence）

复杂度门、执行计划、验收与阻塞策略都应由这层推导驱动，而不是由表层关键词直接驱动。

### 4.7 交付状态（Delivery Lifecycle）

复杂任务必须向用户暴露有限状态，而不是静默执行：

- `ack`
- `progress`
- `blocker`
- `done`

这里强调的是**状态可见**，不是实时输出所有内部细节。

---

## 5. 执行闭环（Execution Loop）

系统应围绕“验收驱动执行（Acceptance-Driven Execution）”构建，而不是围绕“生成一段回答”构建。

### 5.1 基本循环

每轮执行：

1. 建立候选假设（最多 3 个）
2. 选择最小有效动作
3. 获取证据
4. 更新假设
5. 对照验收标准检查
6. 通过则交付；不通过则继续；预算耗尽则终止并解释

### 5.2 验收优先

执行闭环必须具备：

- 明确验收标准
- 明确失败原因
- 明确停止条件
- 明确自纠错入口

没有验收标准的任务，不应直接进入复杂执行。

### 5.3 失败沉淀

每次执行结束都应沉淀最小学习结果：

- 成功 -> 程序性记忆中的 SOP
- 失败 -> anti-pattern / filter / blocker pattern

目标不是“永不失败”，而是“同样的失败不重复烧算力”。

---

## 6. 与现有架构的映射（Mapping to Current Repo）

本仓库已经具备若干基础构件，可以直接承接这条路线：

- `MVP_045_QUERY_GATED_RUNTIME`
  - 负责顶层状态机与 Query Compile
- `MVP_046_AGENT_AXIOMS_CONTEXT_PLANES`
  - 负责公理、约束、上下文平面与假设闭环
- `MVP_010_MEMORY`
  - 负责分层记忆、检索与治理
- `MVP_014_DIALOG_STATE_MACHINE`
  - 负责长任务状态重建
- `MVP_018_SELF_IMPROVEMENT_LOOP`
  - 负责复盘后的受治理自演进

因此当前优化重点不是“重起炉灶”，而是补齐以下缺口：

1. 把“任务系统优先”从理念写进规范
2. 把“用户输入 != Agent 接收对象”写成明确接口
3. 把“单一 runtime + submitter/consumer adapter”写成明确边界
4. 把“过程可见”从 UI 偏好升级为运行时契约
5. 把“失败沉淀”从建议升级为强制复盘输出
6. 把记忆从 `L0/L1/L2` 存储分层升级为“认知语义 + 存储映射”双视图

---

## 7. 迁移策略（Migration Strategy）

### Phase A：定义收敛

- 冻结任务系统导向的 ADR
- 在 Query-Gated Runtime 中引入 `TaskEnvelope`
- 在 Agent Axioms 规范中补齐 `ack/progress/blocker/done`

### Phase B：检索优先

- 让 Query Compile 默认走 retrieval-first
- 严禁未检索先写记忆的常态化路径
- 将失败与成功模式回流到程序性记忆

### Phase C：闭环收敛

- 强制每轮执行绑定 acceptance
- 验收失败进入 repair / escalate / stop
- 对高频约束冲突生成 axiom revision candidate

---

## 8. 设计结论（Conclusion）

这次优化的核心不是替换一个 prompt，也不是再堆一个 skill，而是把系统重心明确迁移到：

- **任务（Task）**
- **查询（Query）**
- **证据（Evidence）**
- **验收（Acceptance）**
- **记忆（Memory）**
- **复盘（Retrospective）**

换句话说：

> AgentOS Next 的内核，不应是“一个会聊天的大脑”，而应是“一个以公理和约束驱动、以任务和交付为中心的操作系统”。
