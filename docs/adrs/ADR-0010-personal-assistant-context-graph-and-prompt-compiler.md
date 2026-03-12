# ADR-0010 个人助理标签化上下文图与提示词编译器（Tagged Context Graph / Prompt Compiler）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-08
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`

## 背景（Context）

个人助理（Personal Assistant）不是单一“项目开发 agent”。同一运行时需要覆盖闲聊、意图澄清、项目任务、会议安排、外网检索、记忆检索与 follow-up 等多 domain。原有实现已具备 Query-Gated Runtime、Context Plane、Execution Prefix / Communication Prefix 与 AgentProfile/SoulProfile 基础，但仍存在三类设计压力：

- 上下文仍偏向“上下文平面 + 前缀字符串”的工程表达，不足以表达跨 domain、父子任务与依赖共享。
- SoulProfile 主要承载沟通身份与风格，尚未把 `GlobalSoul / RoleAxioms / StylePack / DoctrinePack` 明确分层。
- runtime 仍保留旧 `execution_prefix / communication_prefix / prompt_envelope` 兼容工件，但这些结构不适合继续充当 canonical prompt 载体。

## 决策（Decision）

采用以下 canonical 设计：

1. 上下文与 prompt 严格分层。
   - `ContextPlanePackV1` 继续作为低层稳定输入。
   - 在 Query Compile 内新增 `ContextGraphV1` 作为 domain-agnostic 运行时事实图。
   - 再从 ContextGraphV1 为五类 Prompt Profile 投影 `TaskContextViewsV1`。

2. Soul 继续存在，但拆成分层运行时语义。
   - `SoulProfileV2` 引入 `GlobalSoul / RoleAxioms / StylePack / DoctrinePack`。
   - legacy `SoulProfileV1` 在加载时自动归一化，不要求一次性迁移所有文件。

3. 引入 `PromptCompilationV1`。
   - Query Compile 统一编译 `intent_router / planner / executor / verifier_replanner / communicator` 五类 Prompt Profile。
   - `PromptCompilationV1` 成为 canonical 唯一提示词输入来源。
   - `execution_prefix`、`communication_prefix`、`prompt_envelope` 仅保留为历史兼容工件，不再决定 runtime 行为。

4. 个人助理运行时默认采用“最小充分上下文 + 受约束 prompt rewrite slot”。
   - `global_soul`、`role_axioms`、安全边界、工具约束、输出 schema、`send_message` policy 为 immutable sections。
   - 仅允许在 `retrieval_query / task_framing / hypothesis_condensation / communication_brief` 上做局部改写；失败回退确定性编译。

5. 用户可见最终交付收敛到显式消息发送任务（Send Message Task）。
   - 所有用户可见自然语言必须（MUST）由 `communicator` 产出。
   - 最终交付必须（MUST）通过 `builtin://channel.send_message` 完成。
   - 验收阶段若发现有用户可见输出却没有经过 `communicator -> send_message`，必须（MUST）失败。

6. Canonical `assistant_loop` 可以（MAY）执行受限动作批次（Action Batch）。
   - action 仅允许（MUST）执行 `builtin://` operator，避免重新引入“自由技能递归展开”。
   - action 可以（MAY）携带 `task_id|action_id` 与 `depends_on`。
   - 当 action block 执行了非交付类 action 且尚未完成最终交付时，runtime 进入 `verifier_replanner` 与 `communicator` 主链，以保证最终交付基于最新证据。

7. Canonical `assistant_loop` 在非简单模式下收敛到显式角色主链。
   - 至少（MUST）执行 `executor -> verifier_replanner -> communicator` 三段。
   - `executor` 负责产出动作批次，`verifier_replanner` 负责判定是否需要修订，`communicator` 负责最终用户可见表达。

## 备选方案（Alternatives）

### 方案 A：继续以 Context Plane + 两段前缀为主

- 优点：实现最简单，迁移成本最低。
- 缺点：难以表达多 domain 上下文缩放、角色差异、父子任务依赖与 prompt 分层。

### 方案 B：直接把整图或整段结构化 JSON 喂给模型

- 优点：理论表达力更强。
- 缺点：上下文膨胀快，前缀稳定性差，KV cache 利用率低，且当前代码基线并未准备好完整结构化模型输入。

### 方案 C：完全采用 prompt-of-prompt

- 优点：对 prompt 自适应能力最强。
- 缺点：行为漂移大、可审计性差、失败归因困难，不适合作为 canonical runtime。

## 取舍（Tradeoffs）

- 选择 `ContextGraph + TaskContextView + PromptCompilation` 会增加运行时对象和 schema 数量，但换来跨 domain 可扩展性与更清晰的角色边界。
- 选择“确定性骨架 + 局部可改写 slots”意味着首版不是最自由的 prompt 生成，但可以更稳定地审计和回放。
- 保留旧 `execution_prefix/communication_prefix` 作为历史工件有助于阅读旧证据，但不再允许它们决定新 runtime 的语义。

## 后果（Consequences）

- Query Compile 产物将变大，但信息分层更清晰，可显式观测当前 domain、当前 Prompt Profile、当前 StylePack/DoctrinePack。
- Soul 配置文件可以渐进迁移；旧配置无需立即重写。
- assistant loop 以 canonical 方式向 skill policy 透传 `context_graph / task_context_views / prompt_profiles / prompt_compilation`。
- Consumer Adapter 需要同步切到显式消息交付结果，不能再从 `reply_text` 或裸 `reply` 推正式交付。

## 风险与缓解（Risks & Mitigations）

- 风险：Query 对象过大，影响预算与调试效率。
  - 缓解：保持 ContextGraphV1 为最小充分节点集；`context_pack.evidence` 仍受 `5..10` 边界治理。

- 风险：RoleAxioms 与 AgentProfile.execution_axioms/communication_axioms 语义重叠。
  - 缓解：AgentProfile 仍是 runtime policy 主源；Soul 的 RoleAxioms 只做 prompt 角色覆盖。

- 风险：局部 rewrite slot 未来若接 LLM，会引入额外漂移。
  - 缓解：冻结 immutable sections，并要求 rewrite 失败自动回退确定性编译。

## 可观测与验收（Metrics & Acceptance）

- Query Compile 结果必须包含：
  - `context_graph`
  - `task_context_views`
  - `prompt_profiles`
  - `active_style_pack`
  - `active_doctrine_pack`
- Prompt 编译必须能区分 `communicator` 与 `executor` 的 RoleAxioms。
- assistant loop 生成的 routing/plan evidence 必须能观察到 Prompt Profile、StylePack、DoctrinePack 的选择结果。
- 相关单测必须覆盖：
  - legacy SoulProfile 归一化
  - 五类 Prompt Profile 生成
  - workspace analysis 等高约束任务命中 `scientific_hypothesis_mode`

## 后续工作（Follow-ups）

- 为局部 rewrite slot 增加可选小模型编译路径与显式 fallback trace。
- 把 `ContextGraph` 与 task dependency graph 做更强关联，以支持后续真正的 event-driven DAG 执行。
