# MVP_045_QUERY_GATED_RUNTIME

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_045
- 相关规范（Related Specs）：
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_044_PA_POLLING_MODE.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_051_RUNTIME_POLICY_BUNDLE.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`
  - `docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md`

## 目的（Purpose）

定义查询门控运行时（Query-Gated Runtime）的唯一主链，并把能力解析、Prompt 编译、工作者任务图（Worker Task Graph）执行与消息交付收敛到单一 canonical 语义。

## 2026-03-12 规范覆盖（Normative Override）

本节自 2026-03-12 起覆盖本文件中所有将 `ActionGraph`、顶层 `executor batch` 或顶层 `action task` 视为 canonical 运行时面的描述。

### Canonical 主链（MUST）

查询门控运行时（Query-Gated Runtime）必须（MUST）遵循：

`Submitter Adapter -> Canonical Task Ingress -> Query Compile -> Reasoning Scheduler -> Worker Task Scheduler -> Verify -> Communicator -> Consumer Adapter`

其中：

- 推理调度器（Reasoning Scheduler）必须（MUST）串行负责 `intent_router / planner / verifier_replanner / communicator`。
- 工作者任务调度器（Worker Task Scheduler）必须（MUST）负责 durable `worker_task` 的 admission、状态迁移与恢复。
- 工作者 ReAct 运行时（Worker ReAct Runtime）必须（MUST）只作为单个 `worker_task` 内部的 worker-local 子循环存在。

### WorkerTaskGraphV1（MUST）

planner 与 verifier/replanner 的 canonical 输出必须（MUST）为 `WorkerTaskGraphV1`，并且只能（MUST）在 `worker_tasks` 字段中表达顶层可执行单元。

`WorkerTaskGraphV1` 的最小字段必须（MUST）包含：

- `worker_task_id`
- `objective`
- `depends_on`
- `allowed_operator_refs`
- `scope_summary`
- `completion_contract_ref`
- `tool_budget`
- `time_budget_ms`

`tool_budget` 的默认值必须（MUST）为：

- `max_calls = 4`
- `max_parallel_calls = 1`
- `retry_read_only_tools = false`

### 顶层输出约束（MUST）

- `planner` 与 `verifier_replanner` 必须（MUST）只输出 `worker_tasks`；不得（MUST NOT）输出顶层 `actions`。
- `executor` 仅可（MUST）在 worker-local 语义中输出工具动作 `actions`。
- `executor` 若输出 `worker_tasks`，运行时必须（MUST）以 `E_WORKER_SPLIT_REQUIRES_LEADER` 拒绝。
- `communicator` 仍然必须（MUST）是唯一允许输出 `builtin://channel.send_message` 的 phase。

### 工具执行与 durable 语义（MUST）

- 顶层 durable 单位必须（MUST）是 `root task + worker_task`，而不是 `root task + action task`。
- 工具调用不得（MUST NOT）成为顶层 durable task；工具调用必须（MUST）作为 worker 内部事件记录到同一张 `RuntimeGraph` 的 evidence 与 `result_capsules`。
- 工具执行线程池（Tool Executor Pool）只允许（MUST）在单个 worker 内并行；默认 `max_parallel_workers = 1`。
- 只读工具可以（MAY）按 `retry_read_only_tools` 有界重试；有副作用工具默认不得（MUST NOT）自动重放。

### 边界条件（MUST）

- 本规范不再提供 `ActionGraphV1` 作为 canonical 顶层计划形态。
- runtime 不得（MUST NOT）再使用顶层 browse bridge 或顶层工具批执行作为 planner/verifier 的主语义。
- 若 worker 预算耗尽，必须（MUST）回到 leader，并以 `E_HITL_REQUIRED` 进入 `hold`。

### 兼容策略（MUST）

- `ActionGraphV1` 与顶层 `action task` 仅保留历史读取含义；新执行路径不得（MUST NOT）继续新写。
- 本次变更不提供向旧 `ActionGraphV1` 的回写兼容层。

### 错误码（MUST）

- `E_WORKER_TASK_GRAPH_INVALID`
- `E_WORKER_SPLIT_REQUIRES_LEADER`
- `E_HITL_REQUIRED`
- `E_TASK_DEPENDENCY_UNRESOLVED`
- `E_TASK_DEPENDENCY_CYCLE`

### 测试与验收（MUST）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_executes_emitted_actions_then_aggregate_reasoning -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`

## 主链（Canonical Flow）

运行时必须（MUST）遵循：

`Submitter Adapter -> Canonical Task Ingress -> Query Compile -> Assistant Loop -> Verify -> Consumer Adapter`

高层不得（MUST NOT）在主链外复制一套能力判断、消息投递或动作解释语义。

## EffectiveRuntimeCapabilitiesV1（MUST）

- `EffectiveRuntimeCapabilitiesV1` 必须（MUST）在入口阶段一次性生成。
- Prompt、planner、executor、verifier、consumer 必须（MUST）只读该对象。
- 运行时不得（MUST NOT）再使用 `capability_runtime_hints`、provider 自探测或 polling 自建 tuple/dict 作为并行真相源。

默认值（MUST）：
- `requested_capabilities = []`
- `effective_capabilities = []`
- `disabled_capabilities = []`

错误码（MUST）：
- `E_CAPABILITY_SCHEMA_INVALID`
- `E_CAPABILITY_DENY`

## Prompt Surface（MUST）

- `communicator` phase 的 Granted Operators 必须（MUST）只暴露 `builtin://channel.send_message`。
- 模型侧不得（MUST NOT）看到：
  - `builtin://telegram.send_message`
  - `builtin://telegram.send_document`
  - `builtin://browseruse.search`
  - `playwright_search`
  - `provider=...`
  - `provider_variant=...`
- `web.search` 在 prompt 中的 canonical 形态必须（MUST）为：
  - `builtin://web.search(query, limit?)`
- 当 `research_required=true` 且 `research_run` 已进入 `effective_capabilities` 时，worker phase 的 prompt-visible canonical 形态必须（MUST）为：
  - `builtin://research.run(objective, depth?, report_format?, min_sources?)`
- 当 `research_required=false` 时，prompt 不得（MUST NOT）暴露 `builtin://research.run`。

## Runtime Policy Projection（MUST）

- Query Compile 可以（MAY）读取 Runtime Policy Bundle，但不得（MUST NOT）因此新增并行 runtime 入口。
- `communication_style`、`response_language` 与 `execution_mode` 必须（MUST）只作为 canonical query/context/model routing 的输入投影，而不是新的执行主链。
- 主动策略（Proactivity Policy）与数据敏感度策略（Data Sensitivity Policy）在阈值治理冻结前，不得（MUST NOT）直接触发强主动外发或绕过既有审批/能力门。
- Runtime Policy Bundle 不得（MUST NOT）承载 research/adversarial 算法；研究教义（Research Doctrine）与自对抗模式（Self-Adversarial Mode）必须（MUST）留在 doctrine/axiom 侧。

## 外部证据策略投影（External Evidence Policy Projection）（MUST）

- Query Compile 对普通外部信息查询必须（MUST）生成外部证据策略（External Evidence Policy）对象 `task_requirements.external_evidence_policy_v1`。
- `external_evidence_policy_v1` 的最小字段必须（MUST）包含：
  - `search_rounds_max`
  - `browse_candidates_per_search_max`
  - `total_browse_steps_max`
- 默认值必须（MUST）为：
  - `search_rounds_max = 2`
  - `browse_candidates_per_search_max = 3`
  - `total_browse_steps_max = 4`
- Query Compile 必须（MUST）先读取 `RuntimePolicyBundleV1.external_evidence_policy` 作为默认值，再允许单次请求覆盖；单次覆盖必须（MUST）优先于 bundle 默认值。
- Runtime Policy Bundle 只可以（MAY）提供普通外部证据预算默认值；不得（MUST NOT）借此把普通查询升级为 `research_required=true`。

## Task Brief / Task Bundle（MUST）

- Query Compile 必须（MUST）优先产出任务简报（Task Brief），即最小执行合同，而不是预先展开细计划。
- `query_gated_query_v1` 必须（MUST）显式包含：
  - `task_bundle`
  - `task_execution_policy`
  - `file_refs`
- `task_bundle` 至少必须（MUST）包含：
  - `objective`
  - `completion_contract_ref`
  - `task_execution_policy`
  - `context_snapshot_ref`
  - `file_refs`
  - `read_only_ancestor_context_refs`
  - `allowed_capabilities`
  - `workspace_root`
  - `task_mode`
  - `worker_task_admission_mode`
  - `scope_guard`
- `worker_task_admission_mode` 默认必须（MUST）为 `leader_gate`。
- worker 不得（MUST NOT）直接新增子任务；若需要继续拆分，只能（MUST）提交 `split_request`，并等待 leader 判断和落图。
- planner 必须（MUST）只负责首层工作包（work packet）拆分；后续拆分若发生，必须（MUST）由 leader 决定。

## ActionGraphV1（MUST）

最小字段：
- `action_id`
- `operator_ref`
- `arguments`
- `depends_on`

规则（MUST）：
- `depends_on` 只能（MUST）引用精确 `action_id`。
- 上游结果引用只能（MUST）使用结构化 `{"$from_action": "...", "path": [...]}`。
- 运行时不得（MUST NOT）再解析：
  - `a1/a2/...`
  - `${...}`
  - `{{...}}`
  - `skill_ref/input`
  - `dependsOn`
  - `task_id|id` 作为 action 标识

错误码（MUST）：
- `E_TASK_DEPENDENCY_UNRESOLVED`
- `E_TASK_DEPENDENCY_CYCLE`
- `E_TASK_ARGUMENT_REFERENCE_INVALID`
- `E_ACTION_OPERATOR_UNSUPPORTED`

## Delivery（MUST）

- 渠道（Channel）只表达消息交互，不表达交付物本体。
- 用户可见自然语言必须（MUST）由 `communicator` 产出，并通过 `builtin://channel.send_message` 交付。
- 模型不得（MUST NOT）直接选择 Telegram primitive 或其他渠道细节。
- Consumer Adapter 必须（MUST）负责把 `builtin://channel.send_message` 投影到真实渠道。
- 当运行时已验证失败原因时，必须（MUST）先生成 `user_facing_failure_summary_v1` 或等价结构化失败摘要，再由 `communicator` 进行对外表达。
- `communicator` 可以（MAY）重写语气、顺序与句法，但不得（MUST NOT）超出 `user_facing_failure_summary_v1.allowed_user_visible_facts` 自行发明新的根因标签、provider 诊断或修复建议。
- 若 `user_facing_failure_summary_v1.disallowed_inferences` 存在，`communicator` 必须（MUST）遵守；原始 observation capsule 不得（MUST NOT）推翻该摘要边界。
- `user_facing_failure_summary_v1` 至少必须（MUST）覆盖 `builtin://web.search`、`builtin://web.browse`、`builtin://shell.exec`、`builtin://memory.search` 的稳定失败分类；失败摘要不得（MUST NOT）直接暴露未裁决的原始异常文本作为用户根因。
- 当 `builtin://web.search` 的内部 provider 链包含 Browser-Assisted Search 时，prompt、communicator 与用户可见文案不得（MUST NOT）把 `playwright_search`、DuckDuckGo HTTP 变体名或其他内部 provider 标识暴露成 public operator surface。

## Leader / Worker 边界（MUST）

- `intent_router`、`planner`、`verifier_replanner`、`communicator` 必须（MUST）视为 leader phase。
- `executor` 与所有 builtin/tool action 必须（MUST）视为 worker execution seam。
- 运行时必须（MUST）把 `runtime_role=leader|worker` 投影到 step policy 与 trace evidence。
- worker 可以（MAY）提交：
  - `task_result_capsule`
  - `context_escalation_request`
  - `split_request`
  - `replan_signal`
- worker 不得（MUST NOT）：
  - 直接完成父任务
  - 直接改变验收标准
  - 直接发起 plan revision
  - 直接对用户输出最终消息

## Timeout / Retry / Budget Hold（MUST）

- `deadline_ms` 必须（MUST）保留为兼容字段，但其主语义应（SHOULD）降级为 root request 总体上限与默认种子。
- 每个 task 必须（MUST）拥有 `task_execution_policy_v1`。
- LLM 调用与工具调用都必须（MUST）有 timeout。
- 自动重试必须（MUST）是有界的；非幂等或已产生副作用的 action 默认不得（MUST NOT）自动重试。
- 当 tool budget、step budget、deadline、token budget 或 no-progress 条件命中时，运行时不得（MUST NOT）直接终止为用户失败消息；必须（MUST）进入 `hold`，并以 pause-class 错误码等待恢复或人工介入（HITL）。
- 当 `planner = "llm"` 且 `planner_backend` 指向需要网络的 provider 时，运行时必须（MUST）在进入 planner phase 前完成双闸门预检；若 `remote_calls_armed=false` 或 `allow_network_egress=false`，必须（MUST）以稳定错误码 fail-closed，并且 `steps` 必须（MUST）为空。
- `verify_assistant_execution` 必须（MUST）把预算耗尽映射为：
  - `delivery_state = hold`
  - `hitl_required = true`
  - `primary_failure_code = E_HITL_REQUIRED`
- 若 worker phase 直接产出 planner 未批准的新 action，运行时必须（MUST）拒绝该 batch，并返回 `E_WORKER_SPLIT_REQUIRES_LEADER` 或等价稳定语义。

## Web Runtime（MUST）

- `builtin://web.search` 必须（MUST）保持单一 public 搜索原语；模型面不得（MUST NOT）看到内部 provider 选择或浏览器兜底步骤。
- `builtin://web.search` 的 runtime 内部 provider chain 必须（MUST）为 `Brave -> DuckDuckGo HTTP Search -> Browser-Assisted Search`。
- Browser-Assisted Search 只能（MUST）作为 runtime 内部实现细节存在；不得（MUST NOT）成为 public primitive 或 prompt-visible operator。
- `web.search` 必须（MUST）经过严格健康门（Strict Health Gate）后才能进入 `EffectiveRuntimeCapabilitiesV1`。
- `builtin://web.browse` 必须（MUST）由 Playwright 执行。
- 显式调研（Explicit Research）只能（MUST）通过 `builtin://research.run` 暴露给模型；普通外部查询不得（MUST NOT）因为 search/browse 失败而自动升级为调研工具调用。

## 有界外部证据编排（Bounded External Evidence Orchestration）（MUST）

- 当 `requires_external_evidence=true` 且 `research_required=false` 时，运行时必须（MUST）在单一 canonical runtime 内执行普通外部证据路径，而不是显式调研路径。
- 普通外部证据路径必须（MUST）允许 verifier / replanner / runtime browse bridge 在 `external_evidence_policy_v1` 预算内多轮组合 `builtin://web.search` 与 `builtin://web.browse`。
- 自动 browse bridge 必须（MUST）按候选 URL 列表依次尝试 browse，并在第一个成功且形成可接受证据的页面处停止；不得（MUST NOT）只消费单一首结果。
- 候选 URL 去重必须（MUST）基于规范化后的 URL 字符串。
- 同一候选 URL 在单个 task 内不得（MUST NOT）被 bridge 重复 browse。
- 普通外部证据预算耗尽但仍未取得可接受来源时，运行时必须（MUST）将其归类为候选/来源耗尽（Candidate/Source Exhaustion），而不是 `web.search` runtime 不可用。
- 普通外部证据预算耗尽属于已验证 blocker；除非全局 task/step/replan 预算同时耗尽，否则不得（MUST NOT）强制映射为 `hold/E_HITL_REQUIRED`。

## 失败摘要分层（MUST）

- `user_facing_failure_summary_v1` 对外部证据相关失败必须（MUST）至少区分三类稳定语义：
  - search runtime unavailable
  - ordinary external evidence candidate/source exhausted
  - explicit research blocked or incomplete
- 当普通外部证据预算耗尽时，失败摘要必须（MUST）落到：
  - `reason_class = external_evidence_candidate_exhausted`
  - `template_key = blocker.external_evidence_candidate_exhausted`
- 当显式 `builtin://research.run` 未能形成足够来源时，失败摘要必须（MUST）落到显式 research incomplete 语义；不得（MUST NOT）回写为普通 search runtime repair 建议。
- communicator 不得（MUST NOT）把“候选页不可读/预算耗尽”表述成“需要修复 web.search runtime”。

## Doctrine Selection（MUST）

- Query Compile 产物必须（MUST）显式包含：
  - `research_required`
  - `research_depth`
  - `selected_doctrine_pack`
  - `evidence_expectation`
  - `citation_required`
- `research_required=true` 只能（MUST）来自用户对深入调研、调研报告、多来源对比、带引用结论或等价结构化 research 请求的明确意图；不得（MUST NOT）因为普通 `search + browse` 预算耗尽而自动升级。
- `selected_doctrine_pack` 只能（MUST）表示单 runtime 内部的教义包选择；不得（MUST NOT）表示并行 runtime 选择。
- `selected_doctrine_pack` 不得（MUST NOT）单独授权 `builtin://research.run`；显式 research operator 只能（MUST）由 `research_required=true` 与 `research_run` capability 共同决定。
- `browser_research_mode` 与 `self_adversarial_mode` 必须（MUST）作为 doctrine packs 挂在 `SoulProfileV2` / prompt compilation 上，而不是新的 planner/executor/verifier 栈。

## 边界条件（Boundary Conditions）

- 当 `communicator` 未产出最终消息时，运行时必须（MUST）返回稳定错误而不是静默成功。
- 当外部证据动作失败时，后续 phase 必须（MUST）看到结构化失败事实，而不是丢失结果。
- 当外部证据动作失败且运行时已知更底层 detail 时，对用户可见层必须（MUST）优先使用验证后的失败摘要；不得（MUST NOT）直接把原始异常文本当作最终根因描述。
- 当预算耗尽进入 `hold` 时，运行时必须（MUST）保留 trace、evidence、部分结果与计划摘要；不得（MUST NOT）在 hold 前静默丢弃上下文。
- 当 planner 远程预检失败时，运行时必须（MUST）保留 query、error evidence 与最终快照，但不得（MUST NOT）伪造 planner step、executor step 或非空 `steps`。
- 当 `web_browse` 已授予时，运行时必须（MUST）同时授予 `web_search`。
- 当 `web.search` 由于严格健康门裁剪时，prompt、planner 与 service capability summary 必须（MUST）反映“search unavailable under current runtime gates”，不得（MUST NOT）继续宣称 search 可用。
- 当普通外部证据路径已找到搜索候选但 browse 预算耗尽时，运行时不得（MUST NOT）自动调用 `builtin://research.run`。
- Active service / CLI / webhook / polling 路径不得（MUST NOT）再导入或依赖 `EV1Runtime` 作为现役执行入口；若保留 `ev1`，只能（MUST）作为兼容别名或 legacy 隔离产物。

## 兼容策略（Compatibility）

- `final_output` 可以（MAY）继续保留字段名，但其 canonical 语义必须（MUST）是最终一次被接受的 `builtin://channel.send_message` 结果。
- `capability_runtime_hints`、BrowserUse、Telegram model primitives、ActionGraph alias/template 不再属于 canonical runtime。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. 单一 `EffectiveRuntimeCapabilitiesV1` 贯穿 prompt、planner、executor、consumer。
2. `communicator` 只暴露 `builtin://channel.send_message`。
3. ActionGraph 严格使用 `action_id + depends_on + $from_action`。
4. `a1`/模板字符串必须被拒绝。
5. polling 启动时必须使用同一 capability snapshot。
6. Runtime Policy Bundle 若存在，只能影响 canonical query 投影，不得创建第二套路由语义。
7. 普通外部信息查询必须在默认预算内允许多次 `web.search + web.browse`，且不得自动调用 `builtin://research.run`。
8. 普通外部证据在首个候选失败、后续候选成功时，运行时必须继续尝试后续候选并成功形成证据。
9. 普通外部证据预算耗尽时，失败摘要必须映射到 `external_evidence_candidate_exhausted`，而不是 search runtime repair。
10. `research_required=true` 的任务必须在 verifier/communicator 阶段可见研究证据包（Research Evidence Pack）或等价结构化研究事实。
11. `task_bundle/task_execution_policy/file_refs` 必须在 compiled query 中可见，并可投影到 step policy。
12. 只有全局 task/step/replan 预算耗尽时才进入 `hold/HITL_REQUIRED`；普通外部证据候选耗尽不得被错误映射为 `research_required=true`。
13. 当 `planner="llm"` 且 planner backend 需要网络时，双闸门拒绝必须（MUST）在 planner phase 之前发生，且返回结果中的 `steps` 必须为空。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_spike_al2_planner_gating -v`
