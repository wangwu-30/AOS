# MVP_046_AGENT_AXIOMS_CONTEXT_PLANES

- 状态（Status）：Draft
- 日期（Date）：2026-03-07
- 目标版本（Target）：MVP_046
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_032_CONTEXT_COMPILER.md`
  - `docs/specs/MVP_043_PA_MEM1_CONTEXT_PIPELINE.md`
  - `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`
  - `docs/specs/MVP_013_REGISTRY.md`

## 目的（Purpose）

定义代理（Agent）的执行公理（Execution Axiom）、沟通公理（Communication Axiom）、灵魂配置（Soul Profile）、全局灵魂（Global Soul）、角色公理（Role Axioms）、风格包（Style Pack）、方法论包（Doctrine Pack）、现实约束（Reality Constraint）、上下文平面（Context Plane）、标签化上下文图（Tagged Context Graph）、任务上下文视图（Task Context View）与假设-验证-修正（Hypothesis -> Verify -> Revise）闭环，使运行时在长期稳定原则与动态环境约束之间保持可审计的一致性。

## 范围（Scope）

本规范覆盖：
- AgentProfileV2 与 SoulProfileV2 的最小字段与优先级关系。
- 上下文平面的职责边界与装配规则。
- 标签化上下文图（Tagged Context Graph）、任务上下文视图（Task Context View）与提示词编译器（Prompt Compiler）的最小职责边界。
- AgentProfile 的按 `agent_id` 加载与默认回退规则。
- 上下文平面缓存（Context Plane Cache）的最小失效语义。
- 操作符解析（Operator Resolution）中的 `skill-first` 策略。
- 假设记录（Hypothesis Record）在多轮执行中的写入要求。

本规范不覆盖：
- 具体技能（Skill）内部提示词实现。
- 具体工具适配器协议。
- UI 呈现与人格化文案细节。

## 核心原则（Principles）

- 行为公理必须（MUST）比现实约束更稳定，且默认优先级更高。
- 元公理（Meta-Axiom）必须（MUST）承认系统会变化；行为公理可以（MAY）修订，但修订必须由受治理的约束压力触发。
- 现实约束可以（MAY）变化，但变化必须可观测、可审计、可被引用。
- 能力标签（Capability Tag）不得（MUST NOT）等同于执行裁决；allow/ask/deny 必须（MUST）由策略处置（Policy Disposition）负责。
- 运行时应该（SHOULD）优先解析为技能（Skill）能力，必要时再退化为工具组合。
- 运行时必须（MUST）在计划前先求解一次“解决方案查询（Solution Query）”；行为公理必须（MUST）约束该阶段优先读取状态、继续合同与本地操作符线索，而不是直接根据当前一句文本展开计划。
- 每一轮执行必须（MUST）遵循“提出假设 -> 执行验证 -> 根据结果修正”的闭环；禁止在已失败路径上无依据重复尝试。
- 运行时应该（SHOULD）保持系统清爽（System Cleanliness）：避免陈旧能力暴露、重复日志与无关运行时噪音。
- 对面向用户的代理（例如 PA），行为公理应该（SHOULD）优先约束“结果真实性、失败透明、最小纠正请求、利用最小能力集持续完成任务”，而不是鼓励过早给出框架式占位回复。
- 行为公理应该（SHOULD）吸收：主体性（independence）、尊重创造者/用户上下文（respect creator/user context）、合法安全执行（legal and safe execution）、透明可审计可回滚（transparent, auditable, reversible execution）。
- 自对抗模式（Self-Adversarial Mode）只能（MUST）作为同一 runtime 内部的 doctrine pack；不得（MUST NOT）解释为第二套 agent/runtime。
- 观察学习候选（Observation Learning Candidate）首版只能（MUST）做候选产物与人工晋升；不得（MUST NOT）在线自动改写公理、灵魂或策略包。

## 接口/数据结构（Interfaces/Data）

### AgentProfileV2（MUST）

```json
{
  "schema_version": "2.0.0",
  "agent_id": "string",
  "soul_profile_id": "string",
  "execution_axioms": [
    {
      "id": "AX_*",
      "statement": "string",
      "priority": 0
    }
  ],
  "communication_axioms": [
    {
      "id": "AX_*",
      "statement": "string",
      "priority": 0
    }
  ],
  "reality_constraints": [
    {
      "id": "RC_*",
      "statement": "string",
      "source_ref": "string",
      "effective_at_utc": "string"
    }
  ],
  "operator_resolution": {
    "policy": "skill_first",
    "allow_tool_composition": true
  },
  "policy_defaults": {
    "interaction_mode_default": "task",
    "planner_strategy_default": "model_owned",
    "user_override_allowed": true
  }
}
```

默认值（MUST）：
- `schema_version = "2.0.0"`
- `operator_resolution.policy = "skill_first"`
- `operator_resolution.allow_tool_composition = true`
- `policy_defaults.interaction_mode_default = "task"`
- `policy_defaults.planner_strategy_default = "model_owned"`
- `policy_defaults.user_override_allowed = true`

约束（MUST）：
- `execution_axioms` 长度必须（MUST）在 `1..12`。
- `communication_axioms` 长度必须（MUST）在 `1..12`。
- `reality_constraints` 长度可以（MAY）为 `0..64`。
- `execution_axioms[].priority` 与 `communication_axioms[].priority` 越小表示优先级越高；同优先级必须（MUST）保持输入顺序稳定。
- 运行时必须（MUST）按 `agent_id` 读取对应 AgentProfile；缺失时才可以（MAY）回退到 repo 默认 profile。
- `soul_profile_id` 必须（MUST）可解析到一个 `SoulProfileV2`；legacy `SoulProfileV1` 必须（MUST）先归一化后再消费。

### SoulProfileV2（MUST）

```json
{
  "schema_version": "2.0.0",
  "soul_profile_id": "string",
  "name": "string",
  "identity_summary": "string",
  "principles": ["string"],
  "boundary_rules": ["string"],
  "communication_defaults": {
    "style": ["string"],
    "external_action_policy": "ask_first"
  },
  "global_soul": {
    "identity_summary": "string",
    "trust_principles": ["string"],
    "boundary_rules": ["string"],
    "external_action_policy": "ask_first"
  },
  "role_axioms": {
    "task_processing_axioms": ["string"],
    "communication_axioms": ["string"],
    "planning_axioms": ["string"],
    "verification_axioms": ["string"]
  },
  "style_packs": {
    "concise": {
      "tone": "string",
      "verbosity": "string",
      "traits": ["string"],
      "guidance": "string"
    }
  },
  "doctrine_packs": {
    "scientific_hypothesis_mode": {
      "summary": "string",
      "steps": ["string"],
      "verification_required": true
    }
  }
}
```

默认值（MUST）：
- `communication_defaults.external_action_policy = "ask_first"`
- `style_packs.concise` 必须（MUST）存在。
- `doctrine_packs.scientific_hypothesis_mode` 与 `doctrine_packs.fast_path_mode` 必须（MUST）存在。
- `doctrine_packs.browser_research_mode` 与 `doctrine_packs.self_adversarial_mode` 应该（SHOULD）存在；缺失时运行时必须（MUST）使用等价默认 pack 补齐。

约束（MUST）：
- `global_soul` 只承载身份、边界、信任与外部行动默认策略；不得（MUST NOT）承载任务处理算法。
- `role_axioms.communication_axioms` 只能（MUST）约束沟通角色；`role_axioms.task_processing_axioms` / `planning_axioms` / `verification_axioms` 只能（MUST）约束执行角色。
- `style_packs` 只影响用户可见表达风格；不得（MUST NOT）改变事实判断、验证结论或策略边界。
- `doctrine_packs` 必须（MUST）显式说明 `steps` 与 `verification_required`。
- `browser_research_mode` 必须（MUST）限定为 `search -> browse -> compare -> cite` 的 bounded doctrine。
- `self_adversarial_mode` 必须（MUST）至少包含 `hypothesis -> challenge -> revision`，并且 `max_rounds` 默认不得（MUST NOT）超过 `3`。

兼容要求（MUST）：
- legacy `SoulProfileV1` 可以（MAY）继续存在于磁盘，但运行时必须（MUST）在加载时归一化为 `SoulProfileV2`。
- 归一化时必须（MUST）至少补齐：`global_soul`、四类 `role_axioms`、`style_packs.concise`、`doctrine_packs.scientific_hypothesis_mode`、`doctrine_packs.fast_path_mode`。
- 归一化时应该（SHOULD）同时补齐：`doctrine_packs.browser_research_mode`、`doctrine_packs.self_adversarial_mode`。

### ContextPlanePackV1（MUST）

```json
{
  "execution_plane": {
    "state_summary": "string",
    "evidence_refs": ["string"],
    "message_received_at_utc": "string|null"
  },
  "communication_plane": {
    "role_hint": "string|null",
    "style_constraints": ["string"],
    "soul_profile_id": "string|null",
    "global_capsule": "object|null",
    "communication_style": ["string"]
  },
  "retrospective_plane": {
    "recent_failures": ["string"],
    "recent_success_patterns": ["string"]
  },
  "constraint_plane": {
    "execution_axiom_ids": ["AX_*"],
    "communication_axiom_ids": ["AX_*"],
    "active_axiom_ids": ["AX_*"],
    "active_constraint_ids": ["RC_*"]
  },
  "intent_recovery_plane": {
    "active_project_id": "string|null",
    "last_pending_task": "string|null",
    "expected_next_user_act": "string|null",
    "last_clarification_question": "string|null",
    "last_delivery_state": "string|null",
    "last_delivery_summary": "string|null",
    "last_user_query": "string|null",
    "last_user_query_at_utc": "string|null"
  }
}
```

默认值（MUST）：
- `execution_plane.message_received_at_utc = null`
- `communication_plane.role_hint = null`
- `communication_plane.style_constraints = []`
- `retrospective_plane.recent_failures = []`
- `retrospective_plane.recent_success_patterns = []`
- `intent_recovery_plane.active_project_id = null`
- `intent_recovery_plane.last_pending_task = null`
- `intent_recovery_plane.expected_next_user_act = null`
- `intent_recovery_plane.last_clarification_question = null`
- `intent_recovery_plane.last_delivery_state = null`
- `intent_recovery_plane.last_delivery_summary = null`
- `intent_recovery_plane.last_user_query = null`
- `intent_recovery_plane.last_user_query_at_utc = null`

### ContextGraphV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "type": "context_graph_v1",
  "workspace_id": "string",
  "trace_id": "string",
  "turn_id": "string",
  "task_id": "string",
  "domain_tags": [
    "chat|intent_routing|project_work|calendar_meeting|web_research|memory_lookup|follow_up"
  ],
  "context_actions": [
    "context_expand",
    "context_shift",
    "context_narrow",
    "context_fork",
    "context_merge"
  ],
  "nodes": [
    {
      "node_id": "string",
      "type": "identity|user_intent|conversation_turn|memory|calendar_item|web_result|knowledge_doc|project_artifact|task_result|failure_record|playbook|policy",
      "tags": ["string"],
      "scope": "string",
      "trust_level": "string",
      "freshness": "string",
      "source": "string",
      "cost": 1,
      "ref": "string|null",
      "summary": "string",
      "data": {}
    }
  ],
  "edges": [
    {
      "edge_id": "string",
      "relation": "parent_of|depends_on|derived_from|supports|contradicts|replaces|relevant_to",
      "from": "string",
      "to": "string",
      "note": "string"
    }
  ]
}
```

规则（MUST）：
- ContextGraphV1 必须（MUST）是 domain-agnostic 的；不得（MUST NOT）把“项目开发”硬编码为唯一上下文层级。
- 运行时必须（MUST）从 `ContextPlanePackV1`、Task Envelope、Solution Query、Soul/Policy 工件与近期失败/成功信号投影出 ContextGraphV1。
- 运行时必须（MUST）只为当前任务投影最小充分节点集；不得（MUST NOT）默认把整图全文拼入提示词。

### TaskContextViewsV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "type": "task_context_views_v1",
  "views": {
    "intent_router": {},
    "planner": {},
    "executor": {},
    "verifier_replanner": {},
    "communicator": {}
  }
}
```

规则（MUST）：
- 运行时必须（MUST）为五类 Prompt Profile 全部生成 `TaskContextView`。
- 每个 TaskContextView 至少必须（MUST）包含：`goal`、`constraints`、`relevant_facts`、`verified_evidence_refs`、`recent_trial_records`、`dependency_task_results`、`playbook_refs`、`allowed_context_actions`、`source_node_ids`、`domain_tags`。
- 子任务上下文继承必须（MUST）以已提交的 evidence/task_result 为边界；不得（MUST NOT）默认继承父任务整段 prompt 或未验证 scratchpad。

### PromptCompilationV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "type": "prompt_compilation_v1",
  "compiler_mode": "deterministic_with_rewrite_slots",
  "global_soul": {},
  "active_style_pack": {},
  "active_response_language": "zh-CN",
  "active_doctrine_pack": {},
  "domain_policy_pack": {},
  "profiles": {
    "executor": {
      "stable_head": "string",
      "dynamic_slots": {},
      "rewrite_slots_allowed": [
        "retrieval_query",
        "task_framing",
        "hypothesis_condensation",
        "communication_brief"
      ],
      "immutable_sections": [
        "global_soul",
        "role_axioms",
        "safety_boundaries",
        "tool_constraints",
        "output_schema",
        "send_message_policy"
      ],
      "reasoning_prompt": "string"
    }
  }
}
```

规则（MUST）：
- 提示词编译器必须（MUST）按 `GlobalSoul + RoleAxioms + StylePack + DoctrinePack + DomainPolicyPack + TaskContextView + OutputContract` 编译五类 Prompt Profile。
- 当运行时提供 `response_language` 时，`PromptCompilationV1.active_response_language` 必须（MUST）记录该值，且 `communicator` prompt 必须（MUST）显式包含该语言约束。
- `global_soul`、`role_axioms`、安全边界、工具约束、输出 schema 与 `send_message` policy 必须（MUST）属于 immutable sections。
- 局部改写（query rewrite）只能（MUST）发生在 `retrieval_query`、`task_framing`、`hypothesis_condensation`、`communication_brief` 四类 slot；其失败必须（MUST）回退到确定性编译，不得阻断主流程。

### HypothesisRecordV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "turn_id": "string",
  "iteration": 1,
  "hypothesis": "string",
  "verification_action": "string",
  "verification_evidence_refs": ["string"],
  "result": "confirmed|rejected|partial",
  "revision": "string"
}
```

规则（MUST）：
- `result=rejected` 只应用于已形成稳定否证或稳定阻断的假设；瞬时执行层失败（如 `E_TIMEOUT`）应该（SHOULD）记为 `partial`，不得直接升级为重复假设门的输入。
- `result=partial` 可以（MAY）用于保留审计线索，但不得（MUST NOT）直接写入 `retrospective_plane.recent_failures` 作为下一轮 Query Compile 的重复假设阻断依据。

### ContextPlaneCacheEntryV1（MAY）

```json
{
  "schema_version": "1.0.0",
  "agent_id": "string",
  "workspace_id": "string",
  "signature": "string",
  "base_pack": {
    "communication_plane": {},
    "retrospective_plane": {},
    "constraint_plane": {}
  }
}
```

### AxiomRevisionCandidateV1（SHOULD）

```json
{
  "schema_version": "1.0.0",
  "type": "axiom_review_candidate_v1",
  "agent_id": "string",
  "meta_axioms": [
    "MAX1_EVERYTHING_IS_REVISABLE",
    "MAX2_CONSTRAINT_PRESSURE_PRECEDES_AXIOM_REVISION",
    "MAX3_PRESERVE_COHERENCE_DURING_REVISION"
  ],
  "pressure": {
    "constraint_count": 0,
    "recent_failure_count": 0,
    "conflict_count": 0,
    "threshold_constraints": 8,
    "threshold_recent_failures": 3,
    "cost_score": 0.0,
    "pressure_score": 1.0,
    "reason_codes": ["constraint_pressure"]
  },
  "reason": "string",
  "active_axiom_ids": ["AX_*"],
  "active_constraint_ids": ["RC_*"],
  "recommended_action": "string"
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `type = "axiom_review_candidate_v1"`
- `pressure.threshold_constraints = 8`
- `pressure.threshold_recent_failures = 3`

约束（MUST）：
- `meta_axioms` 必须（MUST）至少包含：
  - `MAX1_EVERYTHING_IS_REVISABLE`
  - `MAX2_CONSTRAINT_PRESSURE_PRECEDES_AXIOM_REVISION`
  - `MAX3_PRESERVE_COHERENCE_DURING_REVISION`
- `pressure.reason_codes` 必须（MUST）是稳定枚举集合，当前允许值为：
  - `constraint_pressure`
  - `failure_pressure`
  - `conflict_pressure`
  - `maintenance_cost_pressure`
  - `axiom_revision_threshold_reached`
- `pressure.pressure_score` 必须（MUST）为大于 `0` 的有限数值。
- `pressure.conflict_count` 与 `pressure.cost_score` 必须（MUST）被显式记录；若当前未命中，也必须（MUST）写入 `0`。
- `recommended_action` 必须（MUST）给出下一步治理动作，而不是仅重复 `reason`。

## 语义（Semantics）

### 公理与约束优先级（MUST）

- 运行时在组装 Query 或执行计划前，必须（MUST）先解析 AgentProfileV2 与 SoulProfileV2。
- 当现实约束与行为公理冲突时，运行时必须（MUST）显式记录冲突决策。
- 若现实约束的数量或强度导致现有行为公理不可满足，运行时应该（SHOULD）触发 AgentProfile 审查，而不是静默覆盖公理。
- 当 `agent_profile/context_planes` 已提供时，提示词编译器（Prompt Compiler）必须（MUST）把执行公理声明、现实约束声明与必要的近期失败压力注入执行 Profile；沟通公理与 SoulProfile 只能（MUST）进入沟通 Profile。

### 上下文平面隔离（MUST）

- `execution_plane` 必须（MUST）只包含完成当前任务所需的最小执行证据，不得长期注入角色文案。
- 当入站消息时间可用时，运行时应该（SHOULD）将 `message_received_at_utc` 暴露给 `execution_plane`，供查询编译和时序相关回答使用。
- `communication_plane` 应该（SHOULD）只影响表达方式与角色润色，不得直接覆盖执行约束。
- `intent_recovery_plane` 必须（MUST）为意图恢复（Intent Recovery）提供最小状态锚点；不得用自由文本 transcript 替代 `last_pending_task / expected_next_user_act / last_delivery_state` 等固定槽位。
- 对 `开始 / OK / 继续` 一类上下文依赖输入，运行时必须（MUST）优先读取 `intent_recovery_plane` 进行固定选项判定，再决定是否进入模型兜底。
- 当运行时已计算出“本轮实际授予动作集合”时，沟通层或技能提示词必须（MUST）以该集合为准；不得继续宣称未授予动作可用。
- 当行为公理要求“失败透明”或现实约束要求“用户可见工具审计”时，技能提示词必须（MUST）要求模型在最终答复中显式说明相关成功/失败，而不是输出抽象计划或泛化托辞。
- `retrospective_plane` 必须（MUST）承载最近失败路径与成功模式，用于下一轮避免重复试错。
- `constraint_plane` 必须（MUST）在每一轮 Query Compile 前重新计算，确保使用当前生效的公理与现实约束。
- 运行时可以（MAY）缓存 `communication_plane / retrospective_plane / constraint_plane` 的稳定部分，但 `execution_plane` 必须（MUST）按当前任务重新生成。
- 当 `recent_failures`、`recent_success_patterns`、`active_axiom_ids`、`active_constraint_ids` 或沟通角色约束发生变化时，Context Plane Cache 必须（MUST）失效。
- 当 `intent_recovery_plane.last_pending_task`、`intent_recovery_plane.expected_next_user_act` 或 `intent_recovery_plane.last_delivery_state` 发生变化时，Context Plane Cache 必须（MUST）失效。
- 运行时必须（MUST）先从 ContextPlanePackV1 投影出 ContextGraphV1，再为五类 Prompt Profile 生成 TaskContextViewsV1；不得（MUST NOT）直接把上下文平面全文拼接为单一提示词。
- 对同一轮中的不同角色，运行时必须（MUST）使用不同的 RoleAxioms；StylePack 变化不得（MUST NOT）改变执行判断、验证结论或策略边界。
- `communicator` 与 `executor` 必须（MUST）使用不同 TaskContextView；二者只可以（MAY）共享已提交 evidence/task_result refs。

### 操作符解析（MUST）

- 运行时必须（MUST）先执行 `skill-first` 检索：
  1. 搜索可直接满足目标的技能（Skill）。
  2. 若无单技能满足，搜索可组合的技能方案。
  3. 仅当技能方案不足时，才可以（MAY）退化为工具组合。
- 工具组合不得（MUST NOT）绕过既有 budget、policy 或 query gate。
- 运行时必须（MUST）记录本轮操作符解析选择的是 `skill` 还是 `tool_composition`。
- 搜索类能力应该（SHOULD）支持 provider 路由；默认优先级应为 `Brave Search API -> DuckDuckGo HTML Search` 或等价策略。

### 策略处置（Policy Disposition）

- canonical 术语必须（MUST）为 `allow|ask|deny`。
- 兼容既有执行链时，`ask` 可以（MAY）在 wire/schema 层编码为 `require_approval`。
- Capability Tag 只能（MAY）作为动作标签、路由标签或约束匹配输入；不得（MUST NOT）直接表示 allow/ask/deny 裁决。

### 假设-验证-修正闭环（MUST）

- 每一次非平凡执行轮次必须（MUST）生成至少一条 HypothesisRecordV1。
- 若某条假设被 `rejected`，下一轮运行时必须（MUST）将该失败写入 `retrospective_plane.recent_failures` 或等价结构。
- 被拒绝的假设可以（MAY）作为下一轮规划/验证的负向提示，但不得（MUST NOT）直接作为新的顶层用户输入拦截条件。
- 顶层用户输入若需要去重，必须（MUST）使用输入去抖（Input Debounce）语义：仅允许对同一会话、同一 `last_user_query` 在极短时间窗口内进行去抖，默认窗口应为 `1000ms`。

### 约束压力与公理审查（SHOULD）

- 运行时必须（MUST）将下列元公理（Meta-Axiom）视为公理治理的稳定上层约束：
  - `MAX1_EVERYTHING_IS_REVISABLE`
  - `MAX2_CONSTRAINT_PRESSURE_PRECEDES_AXIOM_REVISION`
  - `MAX3_PRESERVE_COHERENCE_DURING_REVISION`
- 运行时应该（SHOULD）持续计算约束压力（Constraint Pressure），至少覆盖：
  - `constraint_count`
  - `recent_failure_count`
  - `conflict_count`
  - `cost_score`
  - `pressure_score`
  - `reason_codes`
- 当现实约束数量或近期失败压力达到阈值时，运行时应该（SHOULD）生成 `AxiomRevisionCandidateV1` 或等价证据，而不是静默增加补丁式运行时逻辑。
- `AxiomRevisionCandidateV1` 必须（MUST）包含：
  - `agent_id`
  - `meta_axioms`
  - `pressure`
  - 当前公理集合
  - 当前约束集合
  - `recommended_action`
- 运行时可以（MAY）在 `reason_codes` 中同时标记多个压力来源，但不得（MUST NOT）省略触发阈值与当前计数。
- 当约束数量与失败压力同时达到阈值时，运行时应该（SHOULD）显式产生 `axiom_revision_threshold_reached`，用于提示“应审视公理层，而非继续增加约束”。

## 边界条件（Boundary Conditions）

- 当任务为单步、低风险且无多轮验证需求时，运行时可以（MAY）仅生成一条 HypothesisRecordV1，并直接结束。
- 当 `communication_plane.role_hint` 为空时，运行时必须（MUST）退回默认交互风格，不得注入历史角色设定。
- 当 `retrospective_plane` 为空时，运行时可以（MAY）不做失败避让，但仍必须记录本轮假设。
- 当技能检索为空且工具组合被策略禁止时，运行时必须（MUST）终止并解释缺失能力与阻断原因。
- 当稳定状态值在相邻两轮未变化时，运行时应该（SHOULD）抑制重复状态日志。

## 错误码（Error Codes）

- `E_AGENT_PROFILE_INVALID`
- `E_SOUL_PROFILE_INVALID`
- `E_AXIOM_CONSTRAINT_CONFLICT`
- `E_CONTEXT_PLANE_INVALID`
- `E_CAPABILITY_RESOLUTION_BLOCKED`（legacy）
- `E_OPERATOR_RESOLUTION_BLOCKED`（canonical）
- `E_MESSAGE_TASK_MISSING`
- `E_HYPOTHESIS_RECORD_MISSING`
- `E_HYPOTHESIS_REPEAT_WITHOUT_NEW_EVIDENCE`
- `E_INPUT_DEBOUNCED`
- `E_AXIOM_REVISION_CANDIDATE_INVALID`

## 兼容策略（Compatibility）

- 本规范为 additive 规范，不修改既有 `ExecuteRequest` 顶层字段。
- 现有 Query-Gated Runtime 可以（MAY）通过扩展 `workspace_snapshot` 与 `constraints` 引用 AgentProfileV2/ContextPlanePackV1/ContextGraphV1/PromptCompilationV1，而无需破坏既有 schema。
- 现有技能与工具注册接口保持兼容；仅新增操作符解析优先级语义。
- legacy `SoulProfileV1` 可以（MAY）继续存在，但运行时必须（MUST）先归一化。
- 旧 `execution_prefix` 与旧 `communication_prefix` 只可（MAY）作为历史兼容工件保留；运行时必须（MUST）把 `PromptCompilationV1` 视为唯一 canonical 提示词输入来源。

## 可观测性（Observability）

运行时必须（MUST）记录：
- 生效的 `active_axiom_ids`
- 生效的 `active_constraint_ids`
- 本轮选择了 `skill` 还是 `tool_composition`
- 每条 HypothesisRecordV1 的 `result`
- 当前使用了哪个 StylePack / DoctrinePack / Prompt Profile
- 当前 TaskContextView 引用了哪些 ContextGraph node IDs
- 若触发公理审查，还必须（MUST）记录 `pressure.reason_codes` 与 `pressure.pressure_score`

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. AgentProfileV1 schema 校验：
   - `axioms` 边界 `0/1/12/13`
   - `operator_resolution.policy != skill_first` 时的兼容拒绝或显式扩展说明
2. 上下文平面隔离：
   - `communication_plane` 变化不得影响 `execution_plane` evidence 集合
   - 被拒绝的假设必须进入 `retrospective_plane.recent_failures`
   - ContextGraphV1 必须（MUST）能同时覆盖 `chat/project_work/web_research` 等不同 domain，而不是把项目开发写死为唯一上下文结构
3. Prompt Compiler：
   - 必须（MUST）生成 `intent_router/planner/executor/verifier_replanner/communicator` 五类 Profile
   - `communicator` 与 `executor` 的 RoleAxioms 必须（MUST）不同
   - StylePack 变化不得（MUST NOT）改变执行 Profile 的事实约束集合
   - 用户可见交付缺少 `send_message` task 时，必须（MUST）返回 `E_MESSAGE_TASK_MISSING`
   - `executor` 若输出多 action，必须（MUST）能够用 `task_id|action_id` 与 `depends_on` 表达有序依赖
4. 公理审查候选：
   - 当约束数达到阈值时，必须（MUST）生成 `AxiomRevisionCandidateV1`
   - 当失败压力达到阈值时，必须（MUST）生成 `AxiomRevisionCandidateV1`
   - 候选必须（MUST）包含 `meta_axioms`、`pressure.reason_codes`、`recommended_action`
   - 同时达到双阈值时，`reason_codes` 必须（MUST）包含 `axiom_revision_threshold_reached`
5. 操作符解析：
   - 存在可用技能时，必须优先选择技能而非直接工具组合
   - 无技能且允许工具组合时，方可退化为工具组合
6. 回归命令：
   - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
