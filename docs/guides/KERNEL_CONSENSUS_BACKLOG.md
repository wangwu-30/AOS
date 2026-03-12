# 内核共识待办（Kernel Consensus Backlog）

- 日期（Date）：2026-03-08
- 状态（Status）：Active
- 目的（Purpose）：作为当前“已达成但尚未完全落地”的系统共识单一事实源（Single Source of Truth, SSOT）。

## 使用规则（Operating Rules）

- 本文档只记录已经达成共识、但尚未完全落地的事项。
- 每个条目必须包含：
  - `状态（Status）`
  - `优先级（Priority）`
  - `目标（Goal）`
  - `验收（Acceptance）`
- 条目一旦完成，必须从本文档移出，并同步到：
  - [项目状态汇报 2026-03-08](/Users/wangwu/codex/agentos-next/docs/guides/PROJECT_STATUS_REPORT_2026-03-08.md)
  - [变更记录](/Users/wangwu/codex/agentos-next/CHANGELOG.md)
- 后续新增共识时，必须先补到本文档，再进入实现。

## 状态定义（Status Legend）

- `todo`：已确认方向，尚未开始。
- `in_progress`：已开始实现或已立 contract，但未完成闭环。
- `blocked`：方向确认，但被上游依赖阻塞。

## P0 当前优先项（Current P0）

### 1. 双公理面正式拆分（Execution Axioms + Communication Axioms）

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 把当前单一 `AgentProfileV1.axioms[]` 正式拆成：
    - `ExecutionAxiomProfile`
    - `CommunicationAxiomProfile / SoulProfile`
  - 执行公理只进入 `query compile / solution query / planning / verify`
  - 沟通公理只进入 `intent understanding / user-facing rendering / channel reply`
- 验收（Acceptance）：
  - `AgentProfileV1` 或等价对象中存在双公理面字段
  - prompt 组装时不再用同一 `axioms[]` 同时支撑执行与沟通
  - Telegram/PA 路径可加载独立 `SoulProfile`

### 2. Soul/Identity Plane 落地

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 把参考 `SOUL.md` 吸收为正式 `SoulProfileV1`
  - 至少覆盖：
    - genuinely helpful
    - resourceful before asking
    - external actions ask-first
    - guest/boundary awareness
    - not the user’s voice
- 验收（Acceptance）：
  - `SoulProfileV1` 有 schema、默认值、加载路径
  - 沟通前缀（Communication Prefix）来自 `SoulProfileV1`，不再只是 `role_hint/style_constraints`

### 3. 模型契约收敛为 OperatorPlanV1

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 模型作为“CPU”，只输出：
    - `operator`
    - `arguments`
    - 可选 `stop/blocker/clarify`
  - 不再让 skill-specific `reply schema` 主导模型主输出
- 验收（Acceptance）：
  - 内核级 LLM contract 独立于 skill `outputs_schema`
  - `streaming / reply shaping / channel UX` 不再需要模型承担

### 4. 运行时快照层（Runtime Snapshot / L0 Snapshot）正式化

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 把当前会话状态升级为事件归约快照
  - 至少承载：
    - `pending_contract`
    - `expected_next_user_act`
    - `active_project_id`
    - `last_clarification_question`
    - `blocker`
    - `last_delivery_state`
- 验收（Acceptance）：
  - 存在正式 `RuntimeSnapshotV1` 或等价 schema
  - Query Compile 优先读取 `L0 Snapshot`，而不是优先看原始文本

### 5. Project Capsule / Active Project Resolver

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 在个人助理场景引入：
    - `Global Capsule`
    - `Project Capsule`
    - `Active Project Resolver`
  - 默认只装配一个主项目上下文
- 验收（Acceptance）：
  - `project_id` 命名空间进入记忆与 context assembly
  - 单轮执行默认只绑定一个主项目

## P1 次高优先项（Next P1）

### 6. Solution Query 升级为真正单次推理内核能力

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P1`
- 目标（Goal）：
  - 当前 `SolutionQueryV1` 已存在，但 `llm_self_check` 仍较轻
  - 需要让它变成稳定、单次、可审计的求解阶段
- 验收（Acceptance）：
  - `SolutionQueryV1` 有独立 evidence
  - 本地 skill 优先，LLM 自查只作为一次性 fallback

### 7. Theorem / SOP Store

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P1`
- 目标（Goal）：
  - 把“公理 + 约束 + 经验”推导出来的可复用思路沉淀成：
    - `Derived Theorem`
    - `SOP Rule`
  - `SolutionQuery` 只检索命中的 theorem/SOP，而不是每轮重推一切
- 验收（Acceptance）：
  - 存在 theorem/SOP schema、index 与 retrieval
  - `recent_success_patterns` 不再只是自由文本列表

### 8. Operator Search 渐进式披露

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P1`
- 目标（Goal）：
  - 增加 `operator.search`
  - 默认只给薄目录，需要时再检索具体 operator/skill 细节
- 验收（Acceptance）：
  - 运行时可通过 `operator.search` 获取操作符详情
  - 不再需要把完整能力目录默认塞进上下文

### 9. 真正多模型路由

- 状态（Status）：`todo`
- 优先级（Priority）：`P1`
- 目标（Goal）：
  - 让 `ModelRoutingPolicyV1` 从审计对象升级为真实 runtime 决策
  - 支持：
    - `weak_to_strong`
    - `planner_first`
    - 用户覆盖
- 验收（Acceptance）：
  - runtime 能按 `interaction_mode + complexity + user preference` 选择模型策略

## P2 收尾项（P2）

### 10. Channel/Transport 彻底外提

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P2`
- 目标（Goal）：
  - 让流式、reply shaping、Telegram UX 完全成为 consumer adapter 责任
  - 模型与执行内核不再感知 transport 细节
- 验收（Acceptance）：
  - prompt 中不再出现 transport-specific UX 技巧
  - streaming 完全由 runtime event + consumer adapter 驱动

## 当前剩余阻断（Remaining Blockers）

### 11. LLM 主契约仍受 Skill Output Schema 驱动

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 让内核 LLM 主契约收敛为稳定的 `OperatorPlanV1`
  - skill `outputs_schema` 只在局部执行期校验，不再定义内核主输出结构
- 验收（Acceptance）：
  - `llm_execution` 不再直接以 skill `outputs_schema` 作为运行时主 contract
  - assistant runtime 不再把 `reply` 作为硬编码成功条件

### 12. 旧执行入口仍保留 `skill_ref/input`

- 状态（Status）：`in_progress`
- 优先级（Priority）：`P0`
- 目标（Goal）：
  - 收掉 `channel_gateway / ui1 / legacy EV1` 等残余路径中的 `skill_ref/input`
  - 统一到 `operator_ref/arguments`
- 验收（Acceptance）：
  - active runtime surfaces 不再新写入 `skill_ref/input`
  - 调度、回放、入站网关都使用 canonical 执行字段

当前进展（Current Progress）：
- 已完成：`assistant_loop`、followup/scheduler 持久化、`channel_gateway`、`ui1`、remote payload、turn manifest。
- 剩余收尾：legacy EV1、registry/creator 历史命名、少量历史文档与测试样例。
