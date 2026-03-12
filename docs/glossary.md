# 术语表（Glossary）

规则：中文为主，关键术语首次出现必须写作 `中文（English Term）`。

## 核心概念

- 查询内核（Query Kernel）：把模型视为查询引擎、把 agent 视为约束与编排层的运行时核心口径。
- 有效运行时能力（Effective Runtime Capabilities）：由 runtime 根据公理、约束、环境与策略一次性编译出的能力真相对象。
- 浏览器运行时（Browser Runtime）：内核内部用于网页搜索与浏览的确定性浏览器后端。
- 搜索提供方链（Search Provider Chain）：`web.search` 在 runtime 内部按固定顺序尝试的搜索 provider 列表与降级链。
- DuckDuckGo HTTP 搜索（DuckDuckGo HTTP Search）：通过 DuckDuckGo 的 HTML / Lite HTTP 入口提取候选结果的无状态搜索 provider 家族。
- 浏览器辅助搜索（Browser-Assisted Search）：只作为 `web.search` 内部兜底实现存在的受限浏览器搜索步骤，不属于 public primitive。
- 严格健康门（Strict Health Gate）：只有在 provider 主动探测返回至少一个可用结果后，相关能力才允许进入 `EffectiveRuntimeCapabilitiesV1` 的默认能力门。
- 外部证据策略（External Evidence Policy）：控制普通外部信息查询可使用多少轮 `web.search + web.browse` 的预算对象。
- 有界外部证据编排（Bounded External Evidence Orchestration）：普通外部信息查询在单一 runtime 内按预算多轮组合 `web.search` 与 `web.browse` 的系统编排机制。
- 候选/来源耗尽（Candidate/Source Exhaustion）：已取得搜索候选，但在有界 search/browse 预算内仍未形成可接受外部证据的稳定失败情形。
- 显式调研（Explicit Research）：只有在用户明确要求深入调研、调研报告、多来源对比、带引用结论等场景下才允许启用的调研路径。
- 调研报告（Research Report）：`builtin://research.run` 成功时必须产出的 Markdown 报告，至少包含目标、来源摘录或等价证据摘要与引用列表。
- 动作图（Action Graph）：历史 planner 计划形态；自 2026-03-12 起不再是顶层 canonical 计划形态。
- 动作结果引用（Action Result Reference）：以 `{"$from_action":"...","path":[...]}` 形式声明的上游动作结果读取方式。
- 动作批次（Action Batch）：模型在单次推理输出中声明的一组受限 runtime actions，只允许使用 `action_id / operator_ref / arguments / depends_on`。
- 运行时图会话（Runtime Graph Session）：封装 `runtime_graph_v1` durable 写路径的 canonical facade，内部组合推理调度器会话与工作者任务调度器会话。
- 推理调度器（Reasoning Scheduler）：串行调度 `intent_router / planner / verifier_replanner / communicator` 并维护 leader 侧 durable 状态机的组件。
- 工作者任务调度器（Worker Task Scheduler）：负责 `worker_task` 的 durable admission、状态迁移、恢复与结果记录的组件。
- 工作者任务（Worker Task）：由 leader 批准并写入 `runtime_graph_v1` 的单个 durable worker execution unit。
- 工作者任务图（WorkerTaskGraphV1）：planner 或 verifier_replanner 产出的顶层 canonical worker task 计划形态。
- 工作者 ReAct 运行时（Worker ReAct Runtime）：在单个 `worker_task` 内执行 `reason -> select tools -> parallel execute -> observe` 子循环的 worker-local 运行时。
- 提交（Submission）：同一轮 controller 准入后生成的一组 task 执行单元，使用 `submission_id` 作为稳定分组键。
- 执行通道（Execution Lane）：在 admission-time 绑定的任务级执行档位，决定 reasoning profile、model pool、tool parallelism 与 verification mode。
- 停止策略（Stop Policy）：控制 deadline、token budget、无进展窗口与重复动作上限的结构化停止合同。
- 任务修订（Task Amendment）：用户针对 active submission 的纠正或补充输入，应用层识别、内核负责 supersede 与 stale rejection。
- 代次守卫（Generation Guard）：在 reason、tool dispatch 与 result 回灌前检查 generation 是否仍为当前有效代次的保护机制。
- 副作用边界（Side-Effect Boundary）：task 首次 dispatch 非只读操作后的边界；越界后不得静默 supersede。
- 本地未签名技能（Local Unsigned Skill）：位于独立本地层、跳过 ASVP 验签、但仍受 contract/schema/policy/admission 约束的技能包。
- 技能指纹（Skill Fingerprint）：基于技能目录内容计算出的稳定哈希，用于 remember-by-fingerprint 审批。
- MCP 适配器（MCP Adapter）：把 MCP provider 映射到统一 operator ABI、同时隐藏 transport/session 细节的兼容层。
- 兼容技能适配器（Agent Skills Adapter）：把外部 Agent Skills 映射到运行时 operator ABI 的兼容层，不改变 Kernel primitive。
- 工具执行线程池（Tool Executor Pool）：仅在单个 worker 内并行执行工具调用的本地线程池，不承担 durable 恢复语义。
- 渠道（Channel）：外部交互渠道，如 CLI、Webhook、Telegram；不等于交付物本体。
- 消费适配器（Consumer Adapter）：把 canonical runtime 结果投影到外部渠道的适配层。
- 提交适配器（Submitter Adapter）：把外部输入归一化后送入规范任务入口的适配层。
- 规范任务入口（Canonical Task Ingress）：运行时内部唯一允许进入编译、执行与交付主链的入口。
- 查询门控运行时（Query-Gated Runtime）：将 Query Compile、Assistant Loop、Verify 与 Consumer Adapter 串成的唯一 runtime 主链。
- 运行时图（Runtime Graph）：统一描述消息、任务、上下文快照、结果胶囊与 leader 决策关系的逻辑图视图。
- 运行时图耐久调度器（Runtime Graph Durable Scheduler）：把 `RuntimeGraph` 的 root bootstrap、状态迁移、plan revision 推进与 action task 落盘收敛成单一 durable 写边界的调度组件。
- 任务简报（Task Brief）：由 query compile 产出的最小执行合同，聚焦背景、目标、验收标准、约束与引用，而不是预先展开细计划。
- 任务包（Task Bundle）：给单个 worker task 的结构化执行包，至少包含 objective、completion contract ref、task execution policy、context refs 与 file refs。
- 文件引用（File Reference）：以 `workspace_path|evidence_ref|artifact_ref` 表达的只读文件/证据引用对象。
- 任务执行策略（Task Execution Policy）：按 task 定义的 timeout、retry、deadline fallback 与副作用重试边界。
- 领导者（Leader）：拥有 intent 绑定、首层拆分、replan、父任务验收、communicator 与 HITL 升级权的运行时角色。
- 工作者（Worker）：只执行单个 task、提交结果或 split/context/replan 请求、但不得直接改父上下文或直接对用户输出的临时子 agent。
- 拆分申请（Split Request）：由 worker 提交、但必须经过 leader 判断后才能真正生成子任务的结构化请求。
- 上下文上升（Context Escalation）：当 task bundle 不足时，运行时沿祖先上下文链补充只读 context refs 的过程。
- 人工介入保持态（Hold for HITL）：预算耗尽或越界时保留当前 trace、计划与部分结果并等待人工介入的中间状态。
- Playwright 浏览器运行时（Playwright Browser Runtime）：以 Playwright 作为 canonical web backend 的浏览器执行实现。
- 交付合同（Delivery Contract）：规定完成条件、验证规则与交付边界的结构化对象。
- 长轮询（Long Polling）：通过 `getUpdates` 等机制持续拉取外部事件的入站模式。
- 发布门（Release Gate）：决定是否允许表述“统一 runtime 验证通过”的阻断门。
- 运行时策略包（Runtime Policy Bundle）：按工作区装配的用户偏好、执行模式、主动性与数据敏感度默认策略集合。
- 用户偏好画像（User Preference Profile）：描述沟通风格、响应语言、活跃时段、偏好主题与风险偏好的结构化对象。
- 执行模式策略（Execution Mode Policy）：把“省钱优先 / 平衡 / 高质量 / 闲聊优先”等用户模式映射为 runtime 路由偏好的策略对象。
- 数据敏感度策略（Data Sensitivity Policy）：定义 L0/L1/L2 数据默认级别、存储行为与外发确认约束的策略对象。
- 主动策略（Proactivity Policy）：定义静默时段、推送频率与触发边界的策略对象；本阶段只作为声明性约束进入 runtime。
- MiniMax 提供方（MiniMax Provider）：通过 MiniMax OpenAI-Compatible Chat Completions 接口接入的远程模型提供方。
- 研究教义（Research Doctrine）：在单一 canonical runtime 内组织 `search -> browse -> compare -> cite` 的插件化方法论包，而不是第二套 runtime。
- 研究证据包（Research Evidence Pack）：由 research doctrine 从搜索、浏览与比较轨迹中整理出的结构化证据对象，用于 verifier 与 communicator 消费。
- 自对抗模式（Self-Adversarial Mode）：在复杂、高风险或高歧义任务中启用的 `hypothesis -> challenge -> revision` 内部教义包。
- 观察学习候选（Observation Learning Candidate）：从成功/失败/research 轨迹提炼出的 SOP、anti-pattern 或 strategy 候选；首版只允许人工晋升。
- 连续性记忆（Continuity Memory）：围绕 `(workspace_id, conversation_id)` 维护的当前会话状态头与事件日志，属于记忆系统 V2 的 `L0`。
- 记忆记录 V2（Memory Record V2）：记忆系统 V2 中唯一允许持久化的结构化记忆记录，包含 `kind / summary / payload / memory_key / scope / source` 等字段。
- 记忆上下文 V2（Memory Context V2）：通过 `policy_context["memory_context"]` 注入执行面的唯一记忆上下文结构，字段固定为 `l0_continuity / l1_query / l2_hits / conflicts / retrieval_ref`。
- 迁移兼容桥（Migration Compatibility Bridge）：在 canonical public contract 已升级后，运行时为旧输入、旧索引或旧测试提供的受限归一化层；所有对外可观察结果仍以新 contract 为准。

## 历史术语

- 动作图（Action Graph）：旧的顶层 canonical 计划形态；自 2026-03-12 起仅保留历史读取语义，已退出新写路径。
- 轻量记忆注入兜底（Inline Memory Fallback）：历史实现中的临时注入分支；已退出记忆系统 V2。
- Browser Use Bridge（Browser Use Bridge）：历史桥接方案；已退出 canonical runtime surface。
- Telegram 原语（Telegram Primitive）：`builtin://telegram.*` 一类历史模型侧原语；已退出 canonical runtime surface。
