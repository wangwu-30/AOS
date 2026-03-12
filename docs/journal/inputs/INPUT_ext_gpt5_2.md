id: `20260214-ext_gpt5_2-002`
author: `ext_gpt5_2`
topic: `Round 2 交叉评审：协议准入（Admission MUST）与语义收敛（PackageRunner vs Executor API）`
position:
- 对 `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md` 的最强点（Strongest Point）：明确指出“语义漂移（semantic drift）”与“流程绕过（process bypass）”是 MVP 进入规模化协作/扩展后的两类高概率真实故障源，并提出用“限界实验（Bounded Spike）+证据（Evidence）+决策门（Decision Gate）”处理分歧，路径稳健。
- 对 `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md` 的关键风险（Key Risk）：若把“协议合规”做成 admission MUST 时校验边界拿捏不当（例如强制所有历史输入都满足最新字段集、或强制 round 状态机语义级一致），会造成误报与维护负担，反向激励团队绕过流程；因此 MUST 的落地应从“最小可验证集合（minimal verifiable set）”开始，并为扩展校验预设 kill criteria。
- 冲突 1（协议自动化准入是否升为 admission MUST）：建议升为 MUST，但仅限“最小门禁”范围（协议文件存在、线程成套文件存在、至少一个 INPUT 满足 Message Contract 与 confidence 值域、thread 元字段可解析）；更强约束（如要求所有 inputs 都合规、或强制 Round 2/3/4 全部完成）应先做 bounded spike 再决定。
- 冲突 2（PackageRunner 与 Executor API 语义收敛路径）：建议继续“映射层先行（mapping-first）”，并增加一个“被主流程产物消费（used-as-spec）”的落点，避免映射层长期无人使用导致再次漂移；优先落点建议是 `mvp rc-pack` 产出 `execute_result.json`（ExecuteResult 形状）作为审计材料，而不是立刻重构 PackageRunner 主路径。
evidence:
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`: Message Contract、Rounds、Decision Gate、Bounded Spike 的规范来源。
- `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md`: 本轮交叉评审对象（Round 2）。
- `tests/test_admission_expert_collab_protocol.py`: 协作协议最小合规门禁的实现候选（用于冲突 1 的 bounded spike）。
- `src/agentos_next/runtime/package_runner.py`: 当前执行主路径，已稳定产出 evidence/trace（语义收敛必须避免破坏它）。
- `src/agentos_next/kernel/executor.py`: `ExecuteRequest/ExecuteResult` 的目标语义接口（语义收敛的北极星）。
- `src/agentos_next/runtime/execute_mapping.py`: Spike-B 映射层（PackageRunResult -> ExecuteResult）的实现证据（用于冲突 2 的 bounded spike）。
- `tests/test_spike_executor_mapping.py`: Spike-B 映射层测试证据（accepted/rejected/HITL error_code 保留）。
- 命令结果（可复核）：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前应为全绿；在当前工作区最近一次结果为 25/25）。
tradeoffs:
- 协议 admission MUST（最小门禁）：
  - 收益：把流程从“文档存在”升级为“不可绕过的阻断门（block release）”，与 fail-closed 一致。
  - 成本/风险：门禁范围若过大将导致误报、维护成本上升、甚至诱发绕过行为；必须分层推进。
- 语义收敛 mapping-first：
  - 收益：不动主路径，回归风险最低；可以用证据逐步收敛。
  - 成本/风险：若映射层长期不被消费，仍会漂移成“摆设”；需要一个落点把它变成默认审计材料或执行入口的一部分。
open_questions:
- 冲突 1：协议 admission MUST 的“最小门禁集合”是否需要包含“Round 2 至少一份交叉评审 input”的强制要求？还是先保持文档 SHOULD、测试不强制？
- 冲突 2：`execute_mapping` 的落点（landing point）优先选 `rc-pack` 审计产物（execute_result.json），还是优先实现 `LocalExecutor.execute` 内部调用 PackageRunner？两者的决策门阈值分别是什么？
proposal:
- 冲突 1 的 bounded spike + kill criteria：
  - Spike-A1：将“协议自动化准入”提升为 admission MUST，但仅实现最小门禁测试（类似 `tests/test_admission_expert_collab_protocol.py` 的范围），并在 2-3 次真实协作迭代中观察误报率与维护成本。
  - Kill criteria：若出现以下任一情况则回退为 SHOULD（或缩小门禁范围）并记录为 `blocked_by_missing_evidence`：
    - 连续两次发布候选（RC）因非本质问题（文案/格式/历史文件）被阻断；
    - 为修复误报引入的协议/测试修改频率超过每周 1 次且无新增安全/审计收益；
    - 团队出现绕过输入文件/绕过线程文件的行为（流程逆反信号）。
- 冲突 2 的 bounded spike + kill criteria：
  - Spike-B1：保持 `execute_mapping` 不改主路径，同时在 `mvp rc-pack` 增加产物 `execute_result.json`（ExecuteResult 形状），并为该产物新增测试；以此证明映射层被消费（used-as-spec），形成审计闭环。
  - Kill criteria：若出现以下任一情况则停止推进收敛（保持仅 mapping 层 + 测试）并记录为 `needs_decision`：
    - 任何 `tests/test_mvp_*.py` 行为回归或 CLI 稳定 JSON 输出发生破坏；
    - `execute_result.json` 的 schema 需要频繁变更（>2 次/周）才能对齐现有 PackageRunner 事实，说明抽象层级不合适；
    - 为生成 execute_result 需要侵入 PackageRunner/Trace/Evidence 的核心落盘语义（破坏可回放与审计稳定性）。
acceptance:
- 对冲突 1（协议 admission MUST）：
  - 在 admission tests 子集中存在且通过协议门禁测试（最小集合），并能在缺字段/缺文件时明确失败（错误信息包含 `E_PROTOCOL_SCHEMA_INVALID` 语义）。
  - `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md` 中对应 Decision 状态可从 `pending_bounded_spike` 推进到 `accepted`，且引用测试路径作为证据。
- 对冲突 2（语义收敛路径）：
  - `execute_mapping` 映射层测试持续通过，并且新增的 bounded spike（如 rc-pack 的 execute_result 产物）有对应测试锁定输出结构。
  - 不改变 `src/agentos_next/runtime/package_runner.py` 的执行主路径语义与现有 CLI 输出字段；`PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`

---

id: `20260220-ext_gpt5_2-011`
author: `ext_gpt5_2`
topic: `SM2（Scheduler × Dialog State Machine）联动：policy_context 扩展 + DIALOG_EVENT 追加写入`
position:
- 我支持将 Scheduler 的触发来源（trigger）与 dialog 链接（dialog link）都保持在 `policy_context`（前向兼容，forward-compatible），不升格为 ExecuteRequest 顶层字段；除非出现 OS 级“计费拦截/全局配额治理（Kernel-Level Governance & Quota Enforcement）”硬需求。
- 我建议联动的最小可验证闭环是：Scheduler fire 时写入 dialog 的 `DIALOG_EVENT`（TURN_STARTED/TURN_FINISHED），并通过 `evidence_refs` 引用 scheduler fire evidence，以满足 rehydration 的缺证据阻断（missing evidence -> BLOCKED）语义。
evidence:
- `docs/journal/2026-02-20-expert-collab-thread-011.md`：thread_id=`20260220-SM2-SCHED-DIALOG-011`
- `docs/specs/MVP_015_SCHEDULER_DIALOG_LINK.md`：SM2 规范
- `src/agentos_next/apps/scheduler_tick.py`：在 dialog_trace_id 存在时写入 `DIALOG_EVENT`
- `src/agentos_next/kernel/dialog_state_machine.py`：`rehydrate_dialog_state`（missing evidence fail-closed）
- `tests/test_spike_sm2_scheduler_dialog_link.py`：联动与重建的验收测试
tradeoffs:
- 走 `policy_context`（推荐）：
  - 收益：不破坏 ExecuteRequest 顶层稳定性；Remote API 继续 schema-first；未知键透传自然支持。
  - 成本/风险：治理平面（Kernel/Gateway）若要做不解析 policy blob 的统一配额拦截，需要后续 bounded spike 评估是否升格顶层字段。
- 升格顶层字段（不在本 spike）：
  - 收益：OS 级治理更直接。
  - 成本/风险：破坏面大；需要版本化与兼容策略；与当前已达标基线冲突。
open_questions:
- []
proposal:
- 以 scheduler_tick 作为联动落点，最小新增：
  - `policy_context["dialog_trace_id"]` 作为 link key
  - `policy_context["trigger"]` 作为声明
  - 向 `data/traces/<dialog_trace_id>.jsonl` 追加 `DIALOG_EVENT` + evidence_refs
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_sm2_scheduler_dialog_link.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

---

id: `20260220-ext_gpt5_2-012`
author: `ext_gpt5_2`
topic: `FU2：assistant loop × scheduler follow-up（从 plan-only 到可调度执行）`
position:
- 我主张 FU2 必须保持“显式用户意图（explicit user intent）”：只在用户明确提供 `--followup-at` 时创建后台任务，默认不产生副作用（no side effects by default）。
- 我主张 FU2 的任务创建必须走 `Orchestrator.execute(builtin://scheduler.at)`，并使用稳定 `idempotency_key` 去重（dedup），避免重复创建带来不可控副作用。
- 我主张 `replay_mode=true` 必须 skip 调度创建（不写任务文件），但落 policy evidence note 以便审计。
evidence:
- `docs/journal/2026-02-20-expert-collab-thread-012.md`：thread_id=`20260220-FU2-FOLLOWUP-SCHED-012`
- `docs/specs/MVP_016_FOLLOWUP_SCHEDULING.md`：FU2 规范
- `src/agentos_next/apps/assistant_loop.py`：在 `ok=true` 且 `replay_mode=false` 时，通过 Orchestrator 调用 `builtin://scheduler.at` 创建任务
- `src/agentos_next/cli.py`：`mvp assistant-loop` / `mvp assistant-loop-stdio` 新增 `--followup-at`
- `tests/test_spike_fu2_followup_scheduling.py`：覆盖调度创建 + scheduler-tick 触发 + replay-mode skip
- 命令结果（可复核）：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
tradeoffs:
- 直接写 scheduler 文件（不推荐）：
  - 收益：实现更短。
  - 成本/风险：绕开 Orchestrator idempotency_store，重复执行时更容易产生重复任务与副作用。
- 走 Orchestrator 执行 builtin（推荐）：
  - 收益：复用幂等与错误码稳定性；证据链更完整。
  - 成本/风险：需要在 assistant loop 内新增一次 builtin 调用；但回归面可控。
open_questions:
- []
proposal:
- FU2 在 MVP 阶段仅支持 `scheduler.at`（一次性 follow-up）；cron follow-up 作为后续扩展。
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_fu2_followup_scheduling.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

---

id: `20260220-ext_gpt5_2-013`
author: `ext_gpt5_2`
topic: `REG2：Registry 版本/依赖（versioning & dependencies）最小落地：registryq:// + deterministic resolve`
position:
- 我支持在 REG1 的 `registry://<registry_id>` 之上新增“查询式 skill_ref（query ref）” `registryq://<name>@<constraint>`，以避免破坏现有执行语义（execution semantics）。
- 我建议 constraint MVP 子集只做 `*`（最高版本）与精确版本 `1.2.3`，并采用严格 semver 三段整数排序，减少歧义与回归面。
- 我建议依赖（deps）先作为 registry index 元数据（local-only），并通过 `registry-resolve --with-deps` 输出 deterministic 依赖图；缺包/歧义/循环必须 fail-closed。
evidence:
- `docs/journal/2026-02-20-expert-collab-thread-013.md`：thread_id=`20260220-REG2-VDEPS-013`
- `docs/specs/MVP_017_REGISTRY_VERSION_DEPS.md`：REG2 规范
- `src/agentos_next/kernel/skill_registry.py`：实现 `registryq://` 解析、semver、deps 解析（fail-closed）
- `src/agentos_next/cli.py`：新增 `mvp registry-resolve`，扩展 `mvp registry-add --deps-json`
- `tests/test_spike_reg2_registry_version_deps.py`：锁定最高版本解析与 deps graph 解析
tradeoffs:
- 使用新 scheme `registryq://`（推荐）：
  - 收益：不破坏 `registry://` 的执行语义；LocalExecutor 不需要做 query 解析；更利于回放与仲裁。
  - 成本/风险：生态需要学习两种 ref；但分层清晰（query vs execution）。
- 复用 `registry://` 承载 query（不推荐）：
  - 收益：表面上少一个 scheme。
  - 成本/风险：与 REG1 的“内容寻址 id”冲突，容易导致隐式降级或不一致解析。
open_questions:
- []
proposal:
- 后续扩展（不在 REG2）：
  - constraint 语法（^/~、范围、预发布）与冲突报告（conflict report evidence）
  - 依赖下载/安装（仍应保持 local-first + signed）
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_reg2_registry_version_deps.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

---

id: `20260219-ext_gpt5_2-008`
author: `ext_gpt5_2`
topic: `Spike-SCHED1 / MVP-012：Scheduler P0 原语（Scheduler Primitives）实现口径与验收`
position:
- 我支持将调度器（Scheduler）定义为“触发层（trigger layer）”而不是“执行层（execution layer）”：Scheduler 只决定何时触发，执行仍严格复用 `Orchestrator.execute(ExecuteRequest)`，从而继承 fail-closed、deadline、idempotency 与 evidence/trace 的已锁定语义。
- 我建议在不引入常驻 daemon 的前提下，为 SCHED1 增加一个显式 tick/runner（显式驱动），作为 MVP 验收与回归的确定性入口：无 runner 就无法对“未来触发”做可重复验收。
- 我建议将 `builtin://scheduler.at` 与 `builtin://scheduler.cron` 作为特权技能（privileged skills）落地，输入包含 `run_at/cron` + `execute_request_draft`；任务落盘在 `data/scheduler/tasks/`，触发记录写入 Evidence/Trace。
- 我建议治理（governance）做成“不可扩权覆盖（non-escalatable override）”：
  - 创建任务时剥离危险 policy keys（replay/remote_calls_armed/allow_network_egress/approved_by_human），触发时强制使用当前 OS/runner 的 policy_context 锁定值；
  - `workspace_id` 与 `deadline_ms` 由 scheduler 强制绑定/校验，避免跨 workspace 注入或无限 deadline。
evidence:
- `docs/specs/MVP_012_SCHEDULER.md`：SCHED1 数据模型、cron 子集、特权技能 I/O 与 Acceptance 已定义。
- `src/agentos_next/kernel/orchestrator.py`：`deadline_ms<=0` 的 hard precheck + idempotency_store 缓存语义（scheduler 触发必须复用）。
- `src/agentos_next/runtime/local_executor.py`：builtin 特权技能执行路径已存在（memory），可按同模式扩展 scheduler。
- `docs/specs/LLM_PROVIDER.md` + `tests/test_replay_mode_blocks_remote_backend.py`：replay-mode 远程禁用与双闸门（double-gating）已被回归锁定，scheduler 不能引入绕过点。
tradeoffs:
- 显式 runner/tick（推荐）：
  - 收益：验收与回归可 deterministically 重放；不依赖后台服务，降低 MVP 复杂度。
  - 成本/风险：需要新增 CLI 子命令或库 API；未来若要常驻 daemon 需再引入守护进程语义（可作为后续 spike）。
- 直接做常驻 daemon：
  - 收益：看起来更“产品化”。
  - 成本/风险：引入进程管理、并发抢占、跨平台差异，容易破坏当前稳定基线与可回放验收。
open_questions:
- []
proposal:
- 先实现：
  - `builtin://scheduler.at`、`builtin://scheduler.cron`（仅落盘任务定义）
  - `mvp scheduler-tick --now <UTC ISO>`（或等价库函数）触发 due tasks 并调用 `Orchestrator.execute`
- 单测锁定：
  - at：未来时间不触发，到期触发一次，重复 tick 不重复执行
  - cron：最小子集下 next_run_at 计算与触发行为
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 新增测试覆盖：
  - 任务可持久化（重建 orchestrator 后仍能 tick 触发）
  - evidence/trace 可追溯（至少 evidence_refs 非空，且 trace file 存在）
confidence: `medium`

---

id: `20260219-ext_gpt5_2-009`
author: `ext_gpt5_2`
topic: `Spike-REG1 / MVP-013：Skill Registry（技能注册表）与 registry:// 内容寻址 skill_ref`
position:
- 我支持将 `registry://<registry_id>` 作为 `ExecuteRequest.skill_ref` 的“引用形态（ref form）”，用于消除路径依赖并增强回放与仲裁能力；但 MVP 阶段必须保持 local-only，不引入网络下载。
- 我建议 registry_id 的唯一口径绑定 ASVP `manifest.json` 的 canonical bytes（canonical JSON, UTF-8, sort_keys, no whitespace），避免“签名口径”和“registry 口径”分叉。
- 我建议 LocalExecutor 在构造 `PackageRunRequest.skill_dir` 前解析 `registry://...`，并在解析失败时 fail-closed（不回退为 path），且仍执行 ASVP verify。
- 我建议提供一个显式注册动作（registry-add），将 `registry_id -> skill_dir` 落盘在 `data/registry/index.json`，并写 evidence（routing/snapshot）作为“为什么这个 ref 指向这个路径”的可回放证据。
evidence:
- `docs/specs/MVP_013_REGISTRY.md`：registry_id/索引落盘/执行语义/验收口径已定义。
- `src/agentos_next/protocol/asvp/manifest.py`：`Manifest.canonical_bytes()` 提供 canonical bytes 的代码级口径。
- `src/agentos_next/protocol/asvp/verify.py`：ASVP verify 入口，registry 解析后仍必须走此路径。
- `src/agentos_next/runtime/local_executor.py`：当前将 `skill_ref` 直接当 Path 使用；需要在此处新增 registry 解析层，避免破坏 PackageRunner/SkillPackageLoader。
tradeoffs:
- LocalExecutor 解析（推荐）：
  - 收益：对执行链路改动最小；不需要改 loader；易于回归锁定。
  - 成本/风险：需要维护 index 文件一致性；并需在缺映射时返回稳定错误码（建议复用现有）。
- 在 loader 内解析：
  - 收益：更“单点”。
  - 成本/风险：更容易影响 ASVP verify 与 package loader 的稳定性，回归面更大。
open_questions:
- []
proposal:
- 实现 `FileSkillRegistry`（`data/registry/index.json`）：
  - `register(skill_dir)->registry_id`、`resolve(registry_id)->skill_dir`
- 增加 CLI：
  - `mvp registry-add --skill-dir <path> [--data-dir data]`（写入 index + 写 evidence）
- 增加执行解析：
  - `mvp exec --skill-ref registry://...` 在本地可执行，且与 path 语义等效
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 新增测试覆盖：
  - registry_id 可复现（同 manifest 得到同 registry_id）
  - registry:// 与 path 执行 status/error_code 等效
  - verify_asvp 打开时仍能验签通过（使用 `examples/keys`）
confidence: `medium`

---

id: `20260219-ext_gpt5_2-010`
author: `ext_gpt5_2`
topic: `P1 多轮对话状态机（Multi-turn Dialog State Machine, SM1）落地方案（event-first + rehydration）`
position:
- 我支持以 `trace_id` 作为 dialog_id（对话/会话 id），并通过新增 `TraceEvent.event_type=DIALOG_EVENT` 的方式，把“对话生命周期（dialog lifecycle）”作为一等事件（first-class event）落盘；这是对现有 Evidence/Trace 底座的最小增量。
- 我主张状态机实现必须满足两个可验证目标：
  - 只读重建（rehydration）：从 `data/traces/<trace_id>.jsonl` 确定性重建当前状态（不依赖 wall-clock）。
  - 缺证据阻断（missing evidence -> BLOCKED）：当 TURN_FINISHED 引用的关键 evidence 缺失时，重建必须 fail-closed 进入 `BLOCKED`，并给出原因（reason）。
- 我建议把状态集合收敛为 `OPEN|RUNNING|BLOCKED|IDLE|CLOSED|FAILED`（与 thread-010 synthesis 一致），并将 TURN 粒度事件最小化为 4 个：`DIALOG_OPENED|USER_MESSAGE_RECEIVED|TURN_STARTED|TURN_FINISHED`。
evidence:
- `docs/journal/2026-02-19-expert-collab-thread-010.md`：thread_id=`20260219-P1-DIALOG-SM-010` 的范围/约束/验收口径已落盘。
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`：本轮新增 SM1 规范（state/event/rehydration/acceptance）。
- `src/agentos_next/kernel/types.py`：新增 `TraceEventType` 值 `DIALOG_EVENT`（向前兼容的新增枚举）。
- `src/agentos_next/cli.py`：在 `mvp assistant-loop-stdio` 中追加 dialog 事件写入（不改变既有 stdout JSON 字段集合）。
- `src/agentos_next/kernel/dialog_state_machine.py`：提供 `rehydrate_dialog_state(...)`（只读重建 + missing evidence fail-closed）。
- `tests/test_spike_p1_dialog_state_machine_replay.py`：覆盖 deterministic rehydration 与 missing evidence -> BLOCKED。
- 命令结果（可复核）：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
tradeoffs:
- 事件写入 trace（推荐）：
  - 收益：复用现有持久化；可回放；不引入新顶层 schema；对 CLI 契约无破坏。
  - 成本/风险：需要在多轮入口（stdio/channel）显式写事件，否则状态机无法覆盖所有入口（可逐步扩展）。
- 引入独立 session store（不推荐在 P1）：
  - 收益：读取快。
  - 成本/风险：新增持久化契约与迁移；更容易与 trace/evidence “真相源”分叉。
open_questions:
- []
proposal:
- 以 `assistant-loop-stdio` 作为 P1 首个覆盖入口，先把 event-first + rehydration 验证闭环打通；后续再扩展到 `channel-stdio` 与 scheduler/其他交互通道。
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_p1_dialog_state_machine_replay.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `high`

---

id: `20260219-ext_gpt5_2-013`
author: `ext_gpt5_2`
topic: `OPENCLAW-ASSISTANT-003：Skill 包形态/Manifest 最小集 + L0/L1/L2 记忆映射与 Remote API 扩展建议`
position:
- 关于 Skill 包形态与 Manifest：
  - 我建议继续坚持 ASVP（manifest+签名+防注入）为默认分发边界；manifest 本身保持最小字段集，不把“发现/索引元数据”塞进 manifest 顶层，而是作为普通内容文件（例如 `package_meta.json`）纳入 manifest.files，从而继承签名语义并允许元数据迭代。
  - v1 的可组合性（composability）与可发现性（discoverability）优先依赖 `contract.skill` 与 SC1 minimal `compiled/intent_snapshot.json`，而不是扩展 manifest 结构。
- 关于 OpenViking L0/L1/L2 分层记忆：
  - 建议将 L2_long 映射为 Artifact（commit 后不可静默篡改），L1_short 映射为 evidence + draft artifact（可 TTL），L0_session 映射为 trace + session snapshot refs。
  - “检索轨迹可视化”优先用现有 TraceEvent + evidence_refs 表达（而不是引入新专用日志体系）。
- 关于 Remote API 视角的“memory_context”提案：
  - 我不建议在 MVP 阶段为 `ExecuteRequest` 增加顶层 `memory_context` 字段（会扩大 kernel API 兼容面与测试面）。
  - 建议采用 bounded spike：将 `memory_context` 作为 `policy_context["memory_context"]`（扩展点）或作为 skill 输入（input schema）的一部分；其中 L0 仅允许内联摘要（small inline），L1/L2 必须用 ref/查询参数表达，避免把敏感原文塞进请求体。
evidence:
- `docs/specs/SKILL_PACKAGE_ASVP.md`: manifest 最小字段集与防注入语义（建议不扩张 manifest 顶层）。
- `src/agentos_next/compiler/skillc.py` + `tests/test_skillc_build_compiled_outputs.py`: SC1 compiled 三件套（minimal schema）已落地并回归锁定。
- `src/agentos_next/creator/skill_creator.py` + `tests/test_spike_cr1_creator_plan.py`: 发现/组合路径只依赖 compiled minimal，不依赖 manifest 扩展字段。
- `src/agentos_next/kernel/evidence_store.py`: FileEvidenceStore + `commit_artifact`（L2_long 的可审计落点）。
- `src/agentos_next/kernel/trace_logger.py` + `docs/specs/EVIDENCE_TRACE.md`: trace/evidence 作为检索轨迹与回放基础。
- `docs/specs/REMOTE_SANDBOX_API.md`: `policy_context` 被定义为 extension point（适合承载 memory_context 而不改顶层字段）。
tradeoffs:
- 在 ExecuteRequest 顶层新增 memory_context：
  - 收益：远端沙箱显式拿到分层上下文，语义直观。
  - 成本/风险：kernel API 变更面大；需要同步 CLI/Executor/Remote API/测试；容易触发兼容与回归风险。
- 以 policy_context 或 input schema 承载 memory_context（建议）：
  - 收益：不破坏既有顶层字段；前向扩展（forward compatible）；可按风险逐步收紧（L0 inline、L1/L2 refs）。
  - 成本/风险：语义上需要约定“policy_context 里哪些键属于上下文注入”，并明确脱敏与大小限制。
open_questions:
- memory_context 的最小 schema（v1）是否要单独写 spec（推荐），以及是否需要 `schema_version` 与大小上限（max bytes）？
- L2_long 的“查询参数”形态：用 tag/time-range/semantic-query 还是直接用 artifact_id 列表（更 deterministic）？
proposal:
- Manifest/Package：
  - 继续保留 ASVP manifest 最小字段集不变；如需 discovery 元数据，新增 `package_meta.json`（可选）并纳入 manifest.files。
- Memory：
  - 定义一个 `memory_context` v1 结构（schema_version + l0_inline + l1_refs + l2_query）并先作为 `policy_context["memory_context"]` 透传给 Remote API（bounded spike），本地执行可忽略。
- Bounded Spike + kill criteria：
  - Spike-MEMCTX1：在 `docs/specs/REMOTE_SANDBOX_API.md` 增补 `policy_context.memory_context`（optional）示例与约束；新增/扩展测试确保未知 keys 透传仍通过（不改 kernel ExecuteRequest）。
  - Kill criteria：若必须修改 `ExecuteRequest` 顶层字段或破坏既有 CLI/evidence/trace 契约才能表达 memory_context，则停止该 spike，退回“仅用 refs + skills 层输入表达”。
acceptance:
- 文档与测试均可验收：
  - `policy_context` 继续作为 extension point（未知键透传测试仍 PASS）。
  - 不修改 `docs/specs/SKILL_PACKAGE_ASVP.md` 的 MUST 字段集；新增元数据只以内容文件方式加入。
  - 全量回归保持全绿：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。
confidence: `medium`

---

id: `20260219-ext_gpt5_2-014`
author: `ext_gpt5_2`
topic: `MVP-010 Memory：Spike-MEMCTX1 接受（policy_context.memory_context）+ MEMCTX2 升级硬需求`
position:
- 我接受 Spike-MEMCTX1：优先将 `memory_context` 作为 `policy_context["memory_context"]` 的扩展点进行透传（forward-compatible），在不扩张 Kernel `ExecuteRequest` 顶层字段的前提下，让 Remote Sandbox 能按需加载上下文。
- 我同意并记录 Spike-MEMCTX2 的“单一硬需求（one hard requirement）”作为升级触发条件：若内核（Kernel）或 API 网关（Gateway）需要在不解析任意 policy blob 的情况下，对 memory_context 的大小/深度/计费权重执行 OS 级一致治理与配额拦截（quota enforcement），则必须将其升格为 `ExecuteRequest` 顶层字段，并通过版本化与回归测试保证兼容。
evidence:
- `docs/specs/REMOTE_SANDBOX_API.md`: `policy_context` 是 extension point，且已补充 `memory_context` 示例与“未来可升格为顶层字段”的注记（Spike-MEMCTX1/MEMCTX2 边界）。
- `tests/test_remote_executor_cr1_payload.py`: 已新增用例锁定 `policy_context["memory_context"]` 的透传（Spike-MEMCTX1 passthrough）。
- `docs/specs/EXECUTOR_API.md`: `ExecuteRequest` 顶层字段属于长期兼容契约，提升为顶层必须版本化与回归。
tradeoffs:
- 先走 policy_context（MEMCTX1）：
  - 收益：最小回归面；保持 45/45 稳定性；前向扩展自然。
  - 成本/风险：Kernel 级治理若要做“字段级配额拦截”会受限（由 MEMCTX2 硬需求覆盖）。
- 直接升格顶层字段（MEMCTX2）：
  - 收益：治理/配额/计费更易一致执行（OS 级一等公民）。
  - 成本/风险：兼容面扩大；需要同步 CLI/Executor/Remote API/测试；必须严格版本化与 admission 回归。
open_questions: []
proposal:
- 立即推进 MEMCTX1（policy_context passthrough + schema/size 约束写入 MVP-010 spec）。
- 仅在触发硬需求时，才进入 MEMCTX2 设计与版本化裁决（bounded spike + kill criteria + admission 回归）。
acceptance:
- MEMCTX1：
  - `policy_context["memory_context"]` 在 Remote payload 构造中可透传，且未知 keys 仍前向兼容（tests PASS）。
  - 全量回归保持全绿：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。
- MEMCTX2（若触发）：
  - 必须伴随版本化策略与 admission 回归测试；不得破坏既有 CLI/evidence/trace 契约。
confidence: `high`

---

id: `20260217-ext_gpt5_2-012`
author: `ext_gpt5_2`
topic: `Spike-SC1：compiled/ 目录最终 schema 示例（最小/完整各 1 份）`
position:
- 目标：为 Spike-CR1（Creator discovery+compose）提供可直接引用的 Spike-SC1 `compiled/` 产物 schema 示例，分为“最小（minimal）”与“完整（full）”两套；最小集必须与当前 `skillc build` 的实际产物一致，完整集仅作为后续扩展的可选字段参考（optional fields），不得成为 MVP 硬依赖。
- 定义说明：
  - 编译产物（Compiled Artifacts）当前定位为“审计材料（audit-only）”，运行时主路径暂不消费，以避免破坏 `mvp run-package` 输出契约与 evidence/trace schema。
  - 关键术语：意图快照（Intent Snapshot）、提示包（Prompt Bundle）、执行中间表示（Execution IR）。
- 最小示例（Minimal, `schema_version=1.0.0`）：
  - `compiled/intent_snapshot.json`
```json
{
  "schema_version": "1.0.0",
  "name": "personal_assistant_brief",
  "version": "0.1.0",
  "description": "Generate a concise personal-assistant style response with optional checklist.",
  "intent": "Generate a concise personal-assistant style response with optional checklist.",
  "success_criteria": {
    "constraints": {
      "max_reply_words": 120,
      "no_markdown_links": true
    }
  },
  "constraints": {
    "max_output_tokens": 256,
    "model_id": "local_mock",
    "temperature": 0.2
  },
  "contract_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```
  - `compiled/prompt_bundle.json`
```json
{
  "schema_version": "1.0.0",
  "prompt_kind": "llm_json_contract_v1",
  "static_parts": {
    "header": [
      "You are executing a skill contract. Follow the contract logic strictly.",
      "Skill: personal_assistant_brief v0.1.0",
      "Description: Generate a concise personal-assistant style response with optional checklist.",
      "Logic:"
    ],
    "logic": "Given a user request, produce a brief, helpful reply and an optional checklist. Do not invent facts; state assumptions explicitly when needed."
  },
  "notes": "Dynamic Input/Output schema are injected by runtime; this bundle is audit-only in v1."
}
```
  - `compiled/execution_ir.json`
```json
{
  "schema_version": "1.0.0",
  "executor_kind": "local_llm_json",
  "streaming_capable": false,
  "required_capabilities": [],
  "policy_hints": {}
}
```
- 完整示例（Full, `schema_version=1.0.0`，新增字段均为 optional）：
  - `compiled/intent_snapshot.json`（full）
```json
{
  "schema_version": "1.0.0",
  "name": "personal_assistant_brief",
  "version": "0.1.0",
  "description": "Generate a concise personal-assistant style response with optional checklist.",
  "intent": "Help the user generate a concise assistant reply; optionally produce a checklist.",
  "success_criteria": {
    "constraints": {
      "max_reply_words": 120,
      "no_markdown_links": true
    },
    "acceptance_tests": [
      {
        "name": "basic",
        "input": { "request": "Draft a short email asking to reschedule a meeting." },
        "expect": { "reply_contains": ["reschedule"] }
      }
    ]
  },
  "constraints": {
    "risk_level": "low",
    "execution_targets": ["auto"],
    "network_egress": { "default": "deny", "allow": [] },
    "requires_secrets": false,
    "data_requirements": { "pii": "avoid", "retention": "none" },
    "execution_profile": { "max_output_tokens": 256, "temperature": 0.2, "model_id": "local_mock" }
  },
  "contract_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "derived_from": {
    "contract_path": "contract.skill",
    "artifacts_dir": "artifacts/"
  },
  "i_o": {
    "inputs_schema_ref": "artifacts/inputs_schema.json",
    "outputs_schema_ref": "artifacts/outputs_schema.json"
  }
}
```
  - `compiled/prompt_bundle.json`（full）
```json
{
  "schema_version": "1.0.0",
  "prompt_kind": "llm_json_contract_v1",
  "static_parts": {
    "header": [
      "You are executing a skill contract. Follow the contract logic strictly.",
      "Skill: personal_assistant_brief v0.1.0",
      "Description: Generate a concise personal-assistant style response with optional checklist.",
      "Logic:"
    ],
    "logic": "Given a user request, produce a brief, helpful reply and an optional checklist. Do not invent facts; state assumptions explicitly when needed.",
    "footer": [
      "Return ONLY a JSON object that validates against the Output JSON Schema."
    ]
  },
  "dynamic_injection_contract": {
    "inject_input_json": true,
    "inject_output_json_schema": true,
    "input_json_format": "canonical_json(sort_keys=true, ensure_ascii=true)",
    "output_schema_format": "canonical_json(sort_keys=true, ensure_ascii=true)"
  },
  "schema_hashes": {
    "inputs_schema_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "outputs_schema_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "redaction": {
    "store_prompt_fulltext": false,
    "store_prompt_digest_sha256": true
  },
  "notes": "Audit/replay material. Runtime may choose to use contract.logic directly in v1."
}
```
  - `compiled/execution_ir.json`（full）
```json
{
  "schema_version": "1.0.0",
  "executor_kind": "local_llm_json",
  "streaming_capable": false,
  "required_capabilities": [
    "structured_output(json_schema)"
  ],
  "policy_hints": {
    "preferred_target": "local",
    "risk_level": "low",
    "remote_calls_expected": false
  },
  "plan": {
    "steps": [
      {
        "kind": "llm_complete_json",
        "prompt_bundle_ref": "compiled/prompt_bundle.json",
        "outputs_schema_ref": "artifacts/outputs_schema.json"
      }
    ],
    "on_error": [
      { "when": "E_HITL_REQUIRED", "action": "reject" },
      { "when": "E_TIMEOUT", "action": "timeout" }
    ]
  }
}
```
evidence:
- `src/agentos_next/compiler/skillc.py`: Spike-SC1 实现处，实际落盘生成 `compiled/intent_snapshot.json`、`compiled/prompt_bundle.json`、`compiled/execution_ir.json`（minimal 集对应实现字段集合）。
- `tests/test_skillc_build_compiled_outputs.py`: Spike-SC1 的回归测试，锁定 compiled 产物存在且包含 `schema_version=1.0.0`。
- `examples/skills/personal_assistant_brief/contract.skill`: 示例数据来源（acceptance_rules、execution_profile、logic 等）。
tradeoffs:
- 最小集（minimal）：
  - 收益：字段少、稳定、易于作为 CR1 依赖；避免 schema 频繁变更。
  - 成本/风险：表达力有限，不能直接覆盖 streaming/canvas/tooling 等复杂能力。
- 完整集（full, optional）：
  - 收益：为后续扩展预留空间（hash、dynamic injection contract、plan steps、redaction hints）。
  - 成本/风险：若把 optional 误当 MUST，会抬高 CR1/OC1 依赖成本并增加演进摩擦。
open_questions: []
proposal:
- CR1（Creator）阶段只依赖 minimal 集中的 `schema_version/name/version/constraints/success_criteria/executor_kind` 等字段；其余字段一律视为 optional。
- 如需消费 `compiled/*` 驱动运行时（例如由 IR 直接执行），必须先走 bounded spike，并遵守“不破坏 `mvp run-package` 输出契约与 evidence/trace schema”的硬回退阈值。
acceptance:
- gpt5.3 可据此直接写出 CR1 的实现清单与验收用例，并以 minimal schema 为 hard contract：
  - `skillc build` 输出目录包含 `compiled/` 三文件，且每个文件是 JSON object 且 `schema_version=1.0.0`（参见 `tests/test_skillc_build_compiled_outputs.py`）。
  - 全量回归仍通过：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。
confidence: `high`

---

id: `20260216-ext_gpt5_2-011`
author: `ext_gpt5_2`
topic: `Claude Code 是不是已经是 AgentOS？（产品 Shell vs 平台 Infra 的判定口径）`
position:
- 我同意“Claude Code = 产品（product/shell），AgentOS = 平台/基础设施（platform/infra）”这一口径。Claude Code 覆盖的是用户可感知的交互入口与工具生态；AgentOS 关注的是跨产品复用的信任/治理/审计/分发/兼容契约。
- 仅按表面映射（`claude` 命令=入口、Tools=Skills、MCP=发现）是不够的。是否构成 AgentOS 的关键不在“功能像不像”，而在是否满足 OS 级不变量（invariants）：
  - Invariant-1：统一执行语义（Unified Execution Semantics）必须收敛到 `ExecuteRequest/ExecuteResult`，具备幂等（idempotency）、超时（timeout/deadline）、trace correlation。
  - Invariant-2：默认拒绝（fail-closed）与策略执行点（PEP）必须在执行入口强制，尤其是远程调用/网络出站/secret 接触面。
  - Invariant-3：Evidence/Trace 一等公民（first-class），落盘 schema 稳定、可回放（replayable）、可脱敏（redaction）。
  - Invariant-4：可验证分发单位（verifiable distribution unit）：技能/扩展必须有可签名、可防注入、可版本化的边界（ASVP + admission）。
- Tools ≈ Skills 的正确对齐方式：Tool 更像“可调用原语（callable primitive）”，Skill 更像“带合同与治理边界的可分发单元（contracted + governed + distributable unit）”。MCP Servers 更像“连接/发现机制（connector/discovery mechanism）”，并不天然提供信任与治理边界。
- 因此：Claude Code 可以被视为一个“AgentOS 上层产品”的近似形态，但不等于 AgentOS 本身；AgentOS 的目标是让任何人都能构建 Claude Code 级产品，并共享同一套可信执行与审计分发底座。
evidence:
- `docs/specs/EXECUTOR_API.md`: 定义统一执行语义（ExecuteRequest/ExecuteResult、idempotency、timeout、trace correlation）。
- `src/agentos_next/kernel/orchestrator.py`: Orchestrator 作为执行路由入口（local/remote/auto）与 deadline/idempotency 语义载体。
- `docs/specs/SANDBOXING.md`: fail-closed、egress 默认禁止与沙箱隔离基线。
- `tests/test_mvp_run_package_codex_gating.py`: fail-closed + double gating 的回归证据（未显式双闸门不得远程）。
- `docs/specs/EVIDENCE_TRACE.md` + `docs/specs/ADMISSION_TESTS.md`: evidence/trace 落盘与准入门禁的自动化约束。
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 技能包签名/防注入（可验证分发边界）。
- `docs/specs/RELEASE_CRITERIA.md` + `src/agentos_next/release/pack.py`: release-pack/rc-pack 作为“可复核证据包”机制，支撑 replay 与审计。
tradeoffs:
- 把 Claude Code 当作“AgentOS 已经存在”的结论：
  - 收益：叙事简单，容易让人理解“已经有形态”。
  - 成本/风险：容易忽略 OS 级不变量（治理/审计/分发/兼容）与平台边界，最终把核心护城河做成产品私有实现。
- 坚持“Claude Code=产品，AgentOS=平台”（建议）：
  - 收益：把竞争面从“做一个更像 Claude Code 的 app”转为“做可复用的可信执行与分发底座”，利于生态扩张。
  - 成本/风险：短期产品感知弱，需要用可验证 spikes 证明“平台能支撑产品上限”。
open_questions: []
proposal:
- 用 3 个 bounded spikes 把“AgentOS 能支撑 Claude Code 类产品”从概念变成证据（本地优先、fail-closed 不降级）：
  - Spike-CC1（Tool -> Skill 语义桥）：定义最小 tool-adapter 使工具调用落到 `ExecuteRequest/ExecuteResult` 并产出 evidence/trace（先本地）。
  - Spike-CC2（MCP -> Skill Index 适配）：把“发现”做成只读索引接口（可查询 skills 的 intent/constraints/acceptance 摘要），不等同于信任；信任由 ASVP/admission 提供。
  - Spike-CC3（分发闭环）：以 ASVP 包形式安装/验证/执行/回放一个第三方 skill，证明“平台价值”独立于任何 UI shell。
- Kill criteria（单一硬阈值）：若任何 spike 需要降低 fail-closed/double gating、或需要破坏 `mvp run-package` 输出契约/evidence-trace schema 才能打通，则停止并回退到“机制补齐”而非在产品层硬接。
acceptance:
- 文档落盘后保持工程回归：`PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- 若执行 Spike-CC1~CC3：提供可复现命令与 trace_id，证明 “请求 -> 执行（Orchestrator/Executor）-> evidence/trace -> replay” 闭环成立，且默认不触发远程调用（fail-closed 保持）。
confidence: `high`

---

id: `20260215-ext_gpt5_2-008`
author: `ext_gpt5_2`
topic: `Skill 的本质：从 I/O 合同到“意图合同”（Intent Contract）`
position:
- 我同意 Claude 的“Skill = 意图的封装（Skill = encapsulated intent）”方向，但需要把“意图（intent）”工程化为“可验证的意图合同（verifiable intent contract）”，否则会退化为不可测的营销文案。
- “旧思路 Input/Output”不是要被抛弃，而是要降格为“可验证性载体（verifiability carrier）”：意图必须通过 `inputs_schema/outputs_schema + acceptance_rules + evidence/trace` 被检验（checkable），否则平台无法对齐执行、也无法审计/回放。
- Skill 的长期定义建议为（中文为主、关键术语附英文对照）：
  - Skill = `Intent（意图声明） + Success Criteria（成功判据） + Constraints（约束/政策边界） + Interface（输入/输出接口） + Observability（可观测要求）` 的组合合同（contract）。
  - Execution Plan/Strategy（执行方式/策略）由平台（Orchestrator/Executor）决定，但 Skill 必须声明其“所需能力（required capabilities）”与“禁止事项（non-negotiables）”，以便 fail-closed、沙箱与路由能落地。
- 对“只说做什么，不说怎么做”的补充：可以不说“怎么做（how）”，但必须说“怎么算做成（what counts as done）”。否则平台无法进行一致的验收（acceptance）与回归测试（regression）。
- 形态不限定（tool/agent/service）是对的，但“治理边界（governance boundary）”必须限定：Skill 包（skill package）作为可签名的分发单位（ASVP）需要稳定边界；Agent loop/交互 UI 作为平台能力更合理（避免每个 Skill 自带输入循环导致协议碎片化）。
evidence:
- `docs/specs/SKILL_CONTRACT.md`: 已定义 Skill Contract 为“可验证执行合同（verifiable execution contract）”，并用于路由与治理；这为“意图合同”提供现成落点（把 intent/success criteria 纳入合同语义，而不是另起炉灶）。
- `src/agentos_next/skills/llm_execution.py`: 当前执行路径依赖 `contract.logic + schema` 构造确定性 prompt，并对输入/输出做 schema 验证；说明 I/O 与逻辑文本已承担“可验证意图”的雏形。
- `src/agentos_next/skills/package_loader.py`: loader 强制 artifacts 与 contract schema 一致（TOCTOU 防漂移），支持“意图声明一旦签名就不可被偷换”的语义基础。
- `docs/specs/SKILL_PACKAGE_ASVP.md`: ASVP 将包边界固定为可验证目录（manifest 覆盖全部文件、防注入），使“意图封装”可以被签名与审计。
- `docs/specs/EXECUTOR_API.md`: `ExecuteRequest/ExecuteResult` + idempotency/timeout/trace correlation，将“意图的执行”转为可复核的结果语义（status/error_code/evidence_refs）。
tradeoffs:
- 纯“意图文本”定义 Skill：
  - 收益：表达自然、对用户友好、形态开放。
  - 成本/风险：不可验证、不可回归；容易在多执行器/多模型下语义漂移（semantic drift）。
- “意图合同（intent contract）+ I/O/验收”定义 Skill（建议）：
  - 收益：既保留意图抽象，又保留可验证性；更适配 ASVP 签名、evidence/trace 审计、Executor 统一语义。
  - 成本/风险：合同字段会更“产品化”（更像规范而非随手 prompt）；需要更清晰的默认值与兼容策略。
- 把执行方式完全交给平台：
  - 收益：平台可统一 input loop、streaming、重试、回压（backpressure）、超时等通用能力。
  - 成本/风险：Skill 必须更清楚声明 required capabilities/constraints，否则平台无法安全选择执行策略（尤其 remote/tool egress）。
open_questions:
- v1 是否需要在 `contract.skill` 中显式加入 `intent`/`success_criteria` 字段，还是先用 `description + acceptance_rules` 组合表达（兼容成本更低）？
- “成功判据”如何在不同形态下统一：仅针对结构化输出（JSON）还是允许多模态/流式（streaming）输出的分段验收？
proposal:
- 文档层（优先，低风险）：在 `docs/specs/SKILL_CONTRACT.md` 增补“Skill = 意图合同”的正式定义，并明确：
  - intent/success criteria 与 I/O/acceptance_rules 的关系（意图必须可验证）。
  - 平台职责：input loop/streaming/重试由 Orchestrator/Executor 提供；Skill 通过 execution_profile/required_capabilities 声明需求与边界。
- Bounded Spike（避免直接改合同解析造成回归）：
  - Spike-INT1：不改现有解析器，先约定 `acceptance_rules` 的最小结构模板（例如必须包含 `success_conditions` 列表），并在 `skillc build` 输出 `acceptance_rules.json` 的同时生成 `compiled/intent_snapshot.json`（从 `name/description/logic` + acceptance_rules 派生，作为审计材料）。
  - Kill criteria：若需要修改现有 `mvp run-skill/run-package` 输出契约或 `SkillPackageLoader` 的强制加载逻辑才能落地，则停止该 spike，改为仅更新 spec（不引入新产物）。
acceptance:
- accepted 的可验证标准（文档+工程）：
  - 文档：`docs/specs/SKILL_CONTRACT.md` 中出现“意图合同（Intent Contract）”定义段落，并明确“必须可验证（verifiable）”与平台/Skill 职责切分。
  - 工程回归：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿（确保任何术语升级不会诱发实现回归）。
  - 若执行 Spike-INT1：新增 1 个单测验证 `skillc build` 产出 `compiled/intent_snapshot.json`（仅新增文件，不影响旧运行路径），且 ASVP/loader 对旧 skill 包行为不变。
confidence: `medium`

---

id: `20260216-ext_gpt5_2-010`
author: `ext_gpt5_2`
topic: `Skill 自动发现/组合：作为 Skill-Creator Skill 实现 vs 平台内置`
position:
- 我同意将“Skill 自动发现/组合（auto discovery/composition）”实现为 `Skill-Creator`（一个特殊 Skill），而不是平台内置功能；平台只提供机制（mechanism），Creator 提供策略（policy/UX），类似 GitHub Actions（workflow vs action）。
- 但必须明确边界：Creator 不是越权的“内置功能替身”。平台必须内置最小机制，否则 Creator 会被迫绕过治理（fail-closed）或破坏审计链（audit chain）。
- MVP 推荐信任模型：`first-party 特权 Skill（privileged skill）`。Creator 可以访问只读索引 API（read-only skill index），但任何“发布/分发（publish/distribution）”必须走用户签名（ASVP）+ 准入测试（admission tests）；Creator 不应持有签名私钥。
- Creator 的输出应是“可复核的组合计划（composition plan）”：以 `ExecuteRequest/ExecuteResult` 语义为北极星（north star），产出可执行 steps + rationale，并落盘 evidence/trace，支持 replay。
evidence:
- `docs/specs/EXECUTOR_API.md`: 统一执行语义（ExecuteRequest/ExecuteResult、idempotency、timeout、trace correlation），Creator 的 plan 必须以此为执行落点。
- `src/agentos_next/kernel/orchestrator.py`: Orchestrator 是执行路由入口（local/remote/auto）与幂等/deadline 预检，Creator 不能绕过它。
- `src/agentos_next/runtime/local_executor.py`: 现有本地执行路径通过 PackageRunner 并映射为 ExecuteResult（统一语义出口）。
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 分发单位的签名/防注入边界（Creator 生成的可分发包必须可签名可验证）。
- `docs/specs/ADMISSION_TESTS.md`: 准入测试是阻断门（block release），发布不可绕过。
- `docs/specs/SANDBOXING.md`: 默认拒绝（fail-closed）与沙箱/egress 基线，Creator 不能以“组合”为理由放松。
- `docs/specs/EVIDENCE_TRACE.md`: 组合依据、选择理由、执行步骤必须可落盘可回放（audit/replay）。
- `tests/test_mvp_run_package_codex_gating.py`: fail-closed + double gating 的回归证据（Creator 不得绕开）。
- `src/agentos_next/release/pack.py`: rc-pack/release-pack 的证据包机制（Creator 的结果应可被证据包捕获与复核）。
tradeoffs:
- 作为 Skill（推荐）：
  - 收益：内核最小化（minimal kernel），策略可插拔（pluggable），第三方可竞争更好的 Creator，实现迭代快。
  - 成本/风险：平台必须补齐“只读索引 + plan 表达 + 审计落盘 + 发布门禁”，否则会出现“隐式内置”与越权。
- 平台内置：
  - 收益：更容易控一致性与安全边界，短期产品闭环快。
  - 成本/风险：内核膨胀、回归成本高、生态难分叉创新。
open_questions: []
proposal:
- 平台机制（MVP）：
  - 提供 `Skill Index`（只读检索接口）：返回 skills 的 intent/inputs/outputs/constraints/risk_level/acceptance 的摘要（脱敏）。
  - 提供 `Composition Plan` 结构：steps 对齐 ExecuteRequest-like 语义 + rationale（原因码/证据引用）。
  - 提供 `Publish Flow`：草稿 -> 用户签名（ASVP）-> admission tests -> 可分发。
- Creator（first-party privileged skill）：
  - 输入：用户目标 + 约束（离线/不出网/隐私等级）
  - 输出：plan + rationale +（可选）draft_skill（仅草稿，不自动签名发布）
- Bounded Spike（验证不越权）：
  - Spike-CR1：实现一个 demo Creator，只在本地固定 skill 集合上做 discovery+composition，输出 plan 并执行；全程走 Orchestrator/LocalExecutor，落盘 trace/evidence。
  - Kill criteria：若为跑通闭环必须绕过 fail-closed/double gating、或必须让 Creator 写入“已签名包/持有私钥/绕过 admission”，则判定失败，回退为平台内置机制补齐。
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿（不破坏既有门禁与契约）。
- Spike-CR1 若落地：提供可复现命令（CLI）证明：
  - Creator 输出的 plan 可被执行（Orchestrator -> LocalExecutor），并在 `data/traces/<trace_id>.jsonl` 中可复核选择与执行过程（含 rationale 的 evidence refs）。
  - 组合执行不触发远程调用（fail-closed 保持）；未显式双闸门不得出网。
confidence: `high`

---

id: `20260215-ext_gpt5_2-009`
author: `ext_gpt5_2`
topic: `对标 OpenCLAW：验证 AgentOS 上限的“能力拆分”与 Bounded Spikes`
position:
- 我同意 Host 的结论“架构上可行，但生态和配套技能需要时间建设”，但我建议把对标拆成两层：Kernel 上限（kernel ceiling）与 Product 上限（product ceiling）。
- Kernel 上限（AgentOS-next 当前更接近这一层）：重点不是“能接多少渠道/多少技能”，而是“是否能用可验证的统一语义把渠道/技能/执行串起来”，并保持 fail-closed、证据链（evidence chain）与兼容契约（compatibility contract）不被破坏。
- 对标表中的几个映射需要校正：
  - `Gateway（WebSocket 控制平面）` 不是 `Orchestrator 路由` 的同义词；Orchestrator 是执行路由（execution routing），Gateway 是交互/连接控制平面（interaction/control plane），应是并列层：Gateway 产出 `ExecuteRequest`，Orchestrator/Executor 消费它并产出 `ExecuteResult`。
  - `多通道（WhatsApp/Telegram/Discord/iMessage）` 更像“系统级 Interaction Adapters（交互适配器）”，可以实现为特权 Skill（privileged skills）或平台内置组件；关键是将它们统一到同一事件/trace 语义，而不是把渠道逻辑塞进业务 Skill。
  - `Live Canvas` 不是“UI Skill”就能解决的问题：需要一个稳定的“可视化工作区 artifact schema（canvas artifact schema）”与事件流（event stream）；UI 只是其中一个消费端。
- 基于现有 AgentOS-next 的不变量（invariants），更合理的上限验证路径是：先做“一个渠道 + 一个 gateway + 一个可安装 skill + 可回放 evidence/trace + fail-closed”，再扩展到多渠道/语音/画布/registry，而不是反过来。
evidence:
- `src/agentos_next/kernel/orchestrator.py`: Orchestrator 负责 preferred_target 路由（local/remote/auto），并实现 deadline precheck 与幂等缓存（idempotency）主语义入口。
- `src/agentos_next/runtime/local_executor.py`: LocalExecutor 通过 `PackageRunner` 执行 skill_dir，并把结果映射为 `ExecuteResult`（统一语义出口）。
- `src/agentos_next/runtime/remote_executor.py`: RemoteExecutor 目前为占位 stub（`E_REMOTE_NOT_IMPLEMENTED`），说明“云端运行”尚未实现，但路由架构已具备。
- `docs/specs/EXECUTOR_API.md`: 定义 `ExecuteRequest/ExecuteResult`、幂等/超时/trace correlation（可以作为 Gateway 与多通道的统一北极星语义）。
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 定义可签名/可防注入的 skill package 边界（5700+ skills 的前提不是数量，而是可验证分发边界）。
- `docs/specs/SANDBOXING.md` + `tests/test_mvp_run_package_codex_gating.py`: 默认拒绝（fail-closed）与 double gating 的可回归证据（多通道/语音接入后更需要这条底线）。
- `src/agentos_next/release/pack.py` + `tests/test_mvp_rc_pack.py`: rc-pack 能把 trace/evidence 与协作引用打包（验证“可回放”的产品形态基础）。
tradeoffs:
- 把 OpenCLAW 的产品特性“内建进 kernel”：
  - 收益：短期 demo 更像“完整产品”。
  - 成本/风险：破坏内核最小性（minimal kernel），导致契约不稳定、测试成本上升、生态扩展困难。
- 把 OpenCLAW 的产品特性“技能化/适配器化（skill/adaptor-ize）”：
  - 收益：保持 kernel 语义稳定，渠道/语音/UI 都可以作为可替换模块演进；更接近“OS 提供基础设施”而不是“一个超级 app”。
  - 成本/风险：初期需要定义 1-2 个关键稳定协议（event schema / canvas artifact schema），否则模块化会碎片化。
- “Skills 5700+”的真实挑战：
  - 收益：生态护城河。
  - 成本/风险：不是编译器/运行时本身，而是 registry、版本兼容、审核与安全治理（governance）体系；如果签名/沙箱/策略不牢，规模越大风险越大。
open_questions:
- Gateway 的最小形态（MVP gateway）是否只需本地 websocket（loopback）即可，还是必须包含认证/多租户/断线重连等？
- “交互适配器”在权限模型上是 first-party 特权模块还是第三方可发布 skill？若后者，ASVP/沙箱/egress 必须更强。
- Canvas 的最小“artifact schema”应如何与 `ExecuteResult.artifact_refs` 对齐（不破坏既有输出契约）？
proposal:
- 建议用 4 个 Bounded Spikes 把“OpenCLAW 上限可达”从观点变成可验证证据（先小后大）：
  - Spike-OC1（Interaction, 1 channel）：实现一个“渠道适配器”原型（例如本地 stdin/stdout chat 交互或 webhook mock），把消息事件转换为 `ExecuteRequest`，并把 `ExecuteResult` 转回渠道响应（先不做流式）。
    - Kill criteria：若需要修改 `mvp run-package` 标准输出字段集合或 evidence/trace schema 的 breaking change 才能打通，则停止，改为在 rc-pack 内附带额外审计文件（non-breaking）。
  - Spike-OC2（Gateway, control plane）：实现最小本地 Gateway（WebSocket 控制平面）作为独立进程，提供 `POST/WS message` -> `ExecuteRequest` 路由；所有执行仍通过 Orchestrator/LocalExecutor，且必须落盘 trace/evidence。
    - Kill criteria：若 Gateway 需要绕过 fail-closed/double gating 才能跑通 demo，则视为失败（必须回退并补齐闸门接口）。
  - Spike-OC3（Registry, distribution）：实现最小 Skill Registry（本地索引即可）：以 ASVP `manifest.json` 的哈希作为内容寻址 ref（content-addressed ref），支持 “resolve ref -> local path”，不引入网络。
    - Kill criteria：若无法做到 deterministic ref（同包同 ref）或无法保持 loader/验签兼容，则停止，先只把 ref 写入 rc-pack 作为审计材料。
  - Spike-OC4（Canvas, artifacts not UI）：定义最小 canvas artifact（例如 `canvas.json`）schema，并让一个 demo skill 产出该 artifact，通过 `ExecuteResult.artifact_refs` 暴露；UI 仅作为后续消费端，不进入 spike 目标。
    - Kill criteria：若必须修改既有 `ExecuteResult` 必填字段或 evidence/trace schema 才能表达 artifacts，则停止，改用 “artifact_refs 指向额外文件” 的方式实现向前兼容。
acceptance:
- accepted（本轮对标分析可进入决策/排期）的可验证标准：
  - 文档：本输入块给出“kernel ceiling vs product ceiling”的拆分与 4 个 spikes（每个含 kill criteria）。
  - 工程回归：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿（保证对标讨论不引入破坏性变更）。
  - 若执行 Spike-OC1/OC2：新增至少 1 条自动化测试或可复现命令脚本，证明 “消息 -> ExecuteRequest -> ExecuteResult -> 渠道响应” 闭环，并在 `data/trace/*.jsonl` 中可见对应 trace_id（不要求 UI/语音）。
confidence: `medium`

---

id: `20260214-ext_gpt5_2-003`
author: `ext_gpt5_2`
topic: `Round 3 收敛裁决：协议 admission MUST 与语义收敛落点二选一`
position:
- 冲突 1（协议 admission MUST）最终结论：选择 B（暂不把“Round 2 至少 1 份交叉评审 input”纳入 MUST，仅保持 SHOULD）。原因：在当前 MVP 阶段，把 Round 2 交叉评审提升为 MUST 的边际安全收益有限，但误报/维护成本与“流程逆反”（绕过文件协作）的风险更高；更合理的 fail-closed 门禁是保持“协议合规最小集合”为 MUST（现已由 `tests/test_admission_expert_collab_protocol.py` 落地），并在未来基于真实协作数据再升级 Round 2 约束。
- 冲突 1 评分矩阵（Security 35 / Verifiability 30 / Cost 20 / Speed 15）：
  - 安全与治理（Security/Governance）：`31/35`
  - 可验证性（Verifiability）：`27/30`
  - 实施成本（Implementation Cost）：`18/20`
  - 交付速度（Delivery Speed）：`14/15`
  - 总分：`90/100`（通过 Decision Gate：总分 >= 80 且 Security >= 30）
- 冲突 2（语义收敛落点）最终结论：选择 A（先落 `mvp rc-pack` 的 `execute_result.json`）。原因：`rc-pack` 本身是审计/复核入口，引入 `ExecuteResult` 形状的产物可将映射层变成“被消费的规范（used-as-spec）”，同时不触碰 `src/agentos_next/runtime/package_runner.py` 的主路径语义，回归风险最小；相比之下先做 `LocalExecutor.execute -> PackageRunner` 适配会引入 async/接口稳定性等更大变动面。
- 冲突 2 评分矩阵（Security 35 / Verifiability 30 / Cost 20 / Speed 15）：
  - 安全与治理（Security/Governance）：`33/35`
  - 可验证性（Verifiability）：`29/30`
  - 实施成本（Implementation Cost）：`16/20`
  - 交付速度（Delivery Speed）：`14/15`
  - 总分：`92/100`（通过 Decision Gate：总分 >= 80 且 Security >= 30）
- 冲突 2 单一硬回退阈值（one hard rollback trigger）：若为生成 `execute_result.json` 必须修改 `src/agentos_next/runtime/package_runner.py` 的输出语义或 evidence/trace 落盘结构（schema_version/breaking change），则立即回退该落点（保持仅 `execute_mapping.py` + 测试，不进入 `rc-pack` 默认产物），并将该议题状态改回 `needs_decision`。
evidence:
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`: Decision Gate 权重与阈值（总分 >=80 且 Security>=30）的规范来源。
- `tests/test_admission_expert_collab_protocol.py`: 当前已落地的“最小协议门禁 MUST”，为冲突 1 的 B 方案提供安全底座。
- `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md`: 冲突项与风险陈述来源（process bypass / semantic drift）。
- `src/agentos_next/runtime/execute_mapping.py`: Spike-B 已完成的映射层证据（PackageRunResult -> ExecuteResult）。
- `tests/test_spike_executor_mapping.py`: Spike-B 映射层测试证据（accepted/rejected 与 error_code 保留）。
- `src/agentos_next/release/pack.py`: 当前 `mvp rc-pack` 是审计产物入口，适合作为 ExecuteResult 落点载体。
- `tests/test_mvp_rc_pack.py`: `rc-pack` 产物与 `collab_refs` 的可复核性测试证据。
tradeoffs:
- 冲突 1 选择 B（Round 2 保持 SHOULD）：
  - 收益：降低误报与维护成本，减少绕过协作协议的逆反激励，同时保留后续基于数据升级为 MUST 的空间。
  - 成本/风险：Round 2 的约束不再是自动化硬门禁，可能出现“弱交叉评审”情况；需用线程状态机与人工裁决补位。
- 冲突 2 选择 A（rc-pack 落 execute_result.json）：
  - 收益：把语义映射变成默认审计材料，提升可验证性与长期一致性，同时最小化对主执行路径的侵入。
  - 成本/风险：新增产物与 schema 需要维护；若设计不当可能推动对主路径的侵入（由硬回退阈值控制）。
open_questions: []
proposal:
- 冲突 1（协议 admission MUST）执行项：
  - 维持 Round 2 交叉评审为 SHOULD，不纳入 admission MUST；在 `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md` 中将该裁决写入对应 Decision（并记录评分矩阵与通过门槛）。
  - 在后续 2 个 RC 周期内收集“误报/维护成本/流程逆反”信号；若出现明显 process bypass，再重新触发 bounded spike。
- 冲突 2（语义收敛落点）执行项：
  - 在 `mvp rc-pack` 增加 `execute_result.json` 产物（ExecuteResult 形状），并新增测试锁定字段结构；遵守硬回退阈值（不触碰主路径语义/落盘结构）。
acceptance:
- 冲突 1 accepted 条件：
  - `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md` 明确记录选择 B 与评分矩阵分数，且标注为 `accepted`。
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` 通过，且 admission tests 不强制要求 Round 2 input 存在。
- 冲突 1 needs_decision 条件：
  - 若在后续 2 个 RC 周期内出现“无 Round 2 交叉评审 + 导致关键决策失误/不可复核”的事件记录，则将该项回退为 `needs_decision` 并启动新的 bounded spike。
- 冲突 2 accepted 条件：
  - `mvp rc-pack` 产出 `execute_result.json`，并有对应测试用例锁定其结构；全量 `unittest` 全绿。
  - 未触发硬回退阈值（无需修改 `src/agentos_next/runtime/package_runner.py` 的输出语义或 evidence/trace 落盘结构）。
- 冲突 2 needs_decision 条件：
  - 一旦触发硬回退阈值，立即停止将 execute_result 作为 rc-pack 默认产物，并将该项状态改回 `needs_decision`（保留映射层与测试）。
confidence: `high`

---

id: `20260214-ext_gpt5_2-004`
author: `ext_gpt5_2`
topic: `Architecture Alignment：语义北极星/过渡架构/不可破坏约束（Non-Negotiables）`
position:
- 议题 1（语义北极星）：同意以 `Executor API（ExecuteRequest/ExecuteResult）` 作为长期唯一语义源（single long-term semantic source）。`PackageRunner` 可作为实现细节或过渡层存在，但其对外稳定语义应逐步向 `ExecuteResult` 收敛（通过映射层与执行器封装，而非立即重构主路径）。
- 议题 2（过渡架构）：同意 `LocalExecutor.execute -> PackageRunner` 是当前最小风险落点（minimal-risk landing point）。理由：保持 `PackageRunner` 当前稳定执行/落盘闭环不变，同时在 `Executor` 层提供统一语义入口；与当前 Spike-B 的映射层（`execute_mapping.py`）天然兼容。
- 议题 3（不可破坏约束）：完全同意必须保持：
  - `mvp run-package` CLI JSON 字段稳定性（stable JSON contract）
  - `evidence/trace` 落盘 schema 稳定性（schema_version 语义清晰，禁止隐式 breaking change）
  - fail-closed（默认拒绝）与 admission 门禁不降级（remote double-gating、ASVP、协议准入测试等）
- 我同意的架构不变量（Invariants, 3-5 条）：
  - Invariant-1：所有远程调用（Remote Call）默认禁止（fail-closed），必须双闸门（double gating）显式开启，且 replay-mode 下无条件禁止远程。
  - Invariant-2：`mvp run-package` 的标准输出 JSON 字段为兼容契约，任何变更必须显式版本化并有回归测试（admission/regression）。
  - Invariant-3：evidence/trace 落盘的 schema_version 必须可追踪且结构稳定；新增字段可向前兼容，但不得破坏既有读取与准入测试。
  - Invariant-4：技能包执行在可验证模式下必须执行 ASVP 校验；验证失败必须拒绝执行（fail-closed）。
  - Invariant-5：协作协议（Expert Collaboration Protocol）合规必须能被自动化门禁验证，避免流程层绕过（process bypass）。
- 我不同意的点（最多 3 条）+ bounded spike + kill criteria：
  - Disagree-1：不同意“立即把 PackageRunner 主路径重构为完全走 Executor 接口”（refactor-first）。应先 executor wrapper + mapping-first，再决定是否重构。
    - Bounded Spike：实现 `LocalExecutor`（实现 `Executor.execute`）内部调用 `PackageRunner`，仅用于新入口（例如 `mvp exec` 或库API），并保持现有 CLI 不变；用测试证明不破坏回归。
    - Kill criteria：若任何 `tests/test_mvp_*.py` 行为回归或 evidence/trace 落盘结构需要 breaking change 才能打通，则停止推进 refactor-first，回退为 mapping-only。
  - Disagree-2：不同意把“Round 2 至少 1 份交叉评审 input”立刻提升为 admission MUST（过强门禁会诱发绕过）。
    - Bounded Spike：在 2-3 个协作线程/RC 周期中先作为 SHOULD 观察数据（缺失率/误报/绕过信号），再决定是否升级为 MUST。
    - Kill criteria：若升级前缺失 Round 2 就已造成不可复核的关键决策错误事件，则提前升级为 MUST；若升级后出现高误报与维护负担，则回退为 SHOULD。
  - Disagree-3：不同意让 `ExecuteResult` 的引入改变现有 `run-package` 的输出形状（即便语义更“统一”）。
    - Bounded Spike：在 `rc-pack` 中增加 `execute_result.json`（ExecuteResult 形状）作为审计材料，先证明“used-as-spec”；不触碰现有 CLI 输出。
    - Kill criteria：若为生成 `execute_result.json` 必须修改 `src/agentos_next/runtime/package_runner.py` 的输出语义或 evidence/trace schema，则立即回退，不进入默认产物。
- 最终 stance：`accept with conditions`（接受当前路径，但必须坚持不变量与先 spike 后裁决的节奏）。
evidence:
- `src/agentos_next/kernel/executor.py`: `ExecuteRequest/ExecuteResult` 定义（语义北极星）。
- `src/agentos_next/runtime/package_runner.py`: 当前稳定执行主路径（不可破坏约束的核心载体）。
- `src/agentos_next/runtime/execute_mapping.py`: Spike-B 映射层（mapping-first 证据）。
- `tests/test_spike_executor_mapping.py`: 映射层回归测试证据（accepted/rejected/error_code 保留）。
- `docs/specs/RELEASE_CRITERIA.md`: 不可破坏约束与发布门槛（Release Criteria）。
- `docs/specs/ADMISSION_TESTS.md`: admission tests 定义与执行方式（阻断门）。
- `tests/test_admission_expert_collab_protocol.py`: 协作协议自动化门禁（Invariant-5）证据。
- `src/agentos_next/llm/backend.py` + `tests/test_mvp_run_package_codex_gating.py`: fail-closed + double gating 回归证据。
- 命令结果（可复核）：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（应全绿）。
tradeoffs:
- 以 Executor API 为唯一长期语义源：
  - 收益：降低长期分叉与语义漂移风险，统一治理/审计边界。
  - 成本/风险：短期可能增加封装与映射层维护；若操之过急会引入回归。
- 过渡采用 LocalExecutor -> PackageRunner：
  - 收益：最小侵入、可验证、可渐进收敛。
  - 成本/风险：需要保持映射/封装与主路径同步演进，必须用测试锁定。
open_questions: []
proposal:
- 在不改变现有 CLI 的前提下，新增一个库层 `LocalExecutor`（或新增 CLI 子命令）作为统一语义入口，内部调用 `PackageRunner` 并返回 `ExecuteResult`。
- 对外保持 `mvp run-package` 输出稳定；对内逐步以 `ExecuteResult` 作为审计/治理的统一语义（优先在 `rc-pack` 或 executor wrapper 消费映射层）。
- 所有强约束升级（尤其是协作流程门禁）必须先 bounded spike，明确 kill criteria 后再进入裁决。
acceptance:
- Accepted（本次对齐通过）判定：
  - 现有回归与准入测试全绿：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。
  - 不变量被持续满足：远程调用 fail-closed（含 double gating/replay-mode）、ASVP、协议准入门禁、run-package JSON 契约与 evidence/trace schema 稳定。
- Needs_decision（需要再裁决）判定：
  - 若出现“为统一语义必须破坏 run-package JSON 或 evidence/trace schema”的方案，则必须退回 bounded spike 并在 DECISIONS 中记录为 `needs_decision`（不允许直接合并为 accepted）。
confidence: `high`

---

id: `20260214-ext_gpt5_2-005`
author: `ext_gpt5_2`
topic: `Architecture Alignment Final：过渡主路径二选一与并行补充策略（唯一口径）`
position:
- 过渡架构主路径选择：A（先落 `rc-pack execute_result.json` 作为主路径）。理由：这是“审计链（audit chain）与语义统一（ExecuteResult 形状）”的最低风险落点，可将映射层变成默认审计材料（used-as-spec），同时不触碰 `PackageRunner` 的执行主路径与 `mvp run-package` 的输出契约。
- 另一个方案是否并行保留：yes（B 作为并行补充保留，但不作为主路径推进）。具体：保持 `LocalExecutor.execute -> PackageRunner` 作为后续可选的 bounded spike 方向，待 `execute_result.json` 落地稳定后再评估是否推进为新的执行入口。
- 单一硬回退阈值（one hard rollback trigger）：若为实现/生成 `rc-pack` 的 `execute_result.json` 必须修改 `src/agentos_next/runtime/package_runner.py` 的对外行为（包括 `mvp run-package` CLI JSON 字段或 evidence/trace 落盘 schema 的 breaking change），则立即回退该主路径选择（停止 `execute_result.json` 作为默认产物，退回 mapping-only + tests，并将议题标记回 `needs_decision`）。
- 最终 stance：`accept with conditions`（接受当前路径，但必须满足不可破坏约束与硬回退阈值）。
evidence:
- `src/agentos_next/release/pack.py`: `mvp rc-pack` 是当前 RC evidence pack 入口（审计载体）。
- `src/agentos_next/runtime/execute_mapping.py`: `PackageRunResult -> ExecuteResult` 映射层（可用于生成 execute_result.json 的语义基础）。
- `tests/test_spike_executor_mapping.py`: 映射层回归证据（accepted/rejected/error_code 保留）。
- `src/agentos_next/runtime/package_runner.py`: 当前稳定执行主路径（硬回退阈值保护对象）。
- `tests/test_mvp_rc_pack.py`: RC pack 产物结构与 `collab_refs` 可复核性测试证据（可扩展覆盖 execute_result.json）。
- `docs/specs/RELEASE_CRITERIA.md`: 非协商约束（non-negotiables）与发布门槛来源。
tradeoffs:
- 选择 A 作为主路径：
  - 收益：最小侵入、可验证、能把 ExecuteResult 形状变成默认审计材料，降低语义漂移风险。
  - 成本/风险：新增产物与 schema 维护；若实现不当会诱发对主路径/落盘结构的侵入（由硬回退阈值控制）。
- 保留 B 作为并行补充：
  - 收益：为未来统一执行入口预留路径，不阻塞当前最小风险推进。
  - 成本/风险：若并行推进过快会扩大变更面；因此明确为 bounded spike，非主路径。
open_questions: []
proposal:
- 在 `mvp rc-pack` 中增加 `execute_result.json`（ExecuteResult 形状）并新增测试锁定其结构；保持 `mvp run-package` 输出与 evidence/trace schema 不变。
- 将 `LocalExecutor.execute -> PackageRunner` 标注为并行补充路线，仅在 A 稳定后以 bounded spike 形式推进。
acceptance:
- `mvp rc-pack` 产出 `execute_result.json`，并在 `tests/test_mvp_rc_pack.py`（或新增测试）中验证其字段结构满足 `ExecuteResult`（status/target/timing/error_code/evidence_refs/artifact_refs）。
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- 未触发硬回退阈值：不需要修改 `mvp run-package` CLI JSON 字段或 evidence/trace 落盘 schema 的 breaking change。
confidence: `high`

---

id: `20260215-ext_gpt5_2-006`
author: `ext_gpt5_2`
topic: `编译后的 Skill 分发形态（Compiled Skill Package v1）`
position:
- 我同意“OS 分发的应该是编译后的 Skill（Compiled Skill）”，但需要把“编译”定义为：可验证（verifiable）、可审计（auditable）、可回放（replayable）的分发包，而不是“必须是某种字节码/机器码”。
- 我同意 Host 的“工程代码 + prompt”直觉，但建议把边界收敛为：`Runtime Adapter（运行时适配层）+ Prompt Assets（提示资产）+ Contract Snapshot（合同快照）+ Execution IR（执行中间表示）`。其中“输入循环（input loop）/流式输出（streaming output）”优先由平台（Orchestrator/Executor）提供通用能力，Skill 只声明能力与协议，避免每个 Skill 复制一套 loop 语义导致协议分裂。
- v1 形态建议优先选择“声明式 IR（declarative IR）”而非“可执行代码（executable code）”作为第三方 Skill 的长期默认；可执行代码可作为 first-party/trusted 例外（或未来以 WASM/WASI 受限执行），否则难以形成稳定的跨执行器语义与签名边界。
- 包结构上建议继续以 ASVP（签名清单 + 防注入）为信任外壳：编译后的 Skill 仍是一个目录（directory package），传输层可再压成 tar/zip，但验签语义以目录展开后的 `manifest.json/signature.sig` 为准。
evidence:
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 技能包必须是目录，manifest 列举所有内容文件哈希，且必须防注入（这直接约束“分发形态”的信任外壳）。
- `src/agentos_next/compiler/skillc.py`: 当前 `skillc build` 仅生成 schema/profile/rules 四件套，没有 prompt bundle 或 execution IR。
- `src/agentos_next/skills/package_loader.py`: loader 会要求存在 compiled artifacts（`artifacts/` 或 `dist/<name>/`），且对 artifacts 与 contract schema 做一致性校验（TOCTOU 防漂移）。
- `src/agentos_next/skills/llm_execution.py`: 当前 prompt 由 `contract.logic + schema` 拼装（可见 prompt 资产尚未成为独立、可签名的 bundle）。
- `docs/specs/SANDBOXING.md`: 本地/云端沙箱约束与 egress 默认禁止，意味着“分发的工程代码”必须有明确沙箱/能力边界才能进入默认生态。
tradeoffs:
- 把“工程代码 + prompt”原样分发：
  - 收益：快速做 demo、工程体验直观。
  - 成本/风险：签名边界不清（哪些代码参与信任？）、跨执行器语义不可控、供应链与沙箱隔离成本陡增。
- 分发“声明式 IR + prompt bundle”（建议作为第三方默认）：
  - 收益：更容易稳定签名/回放/审计；Executor/Orchestrator 可统一实现 input loop 与 streaming 协议；更易做 policy gating。
  - 成本/风险：需要定义 IR 的最小完备字段与兼容策略；短期编译器与验证器工作量增加。
- 第三方可执行代码（WASM/WASI 或其他）：
  - 收益：表达力强、能做复杂逻辑。
  - 成本/风险：沙箱与资源治理复杂；跨平台与调试成本高；若过早引入会拖慢 MVP。
open_questions:
- v1 的 Execution IR（execution_ir.json）最小字段集如何定？（建议从“能力声明 + 入口/输出协议 + 工具调用计划骨架”开始，避免过早把完整 agent loop 固化进 IR）
- Prompt Assets（prompt bundle）与 Contract Snapshot 的关系：是把 `contract.logic` 迁出成文件并在 contract 中仅留引用，还是先“双写”（contract 保持现状，bundle 做审计材料）？
proposal:
- 采用“Compiled Skill Package v1（目录）”建议结构（在现有 ASVP 包上增量扩展，保持向后兼容）：
  - 必须（MUST）：`manifest.json`、`signature.sig`、`contract.skill`、`artifacts/inputs_schema.json`、`artifacts/outputs_schema.json`、`artifacts/acceptance_rules.json`、`artifacts/execution_profile.json`
  - 可选（SHOULD, v1 增量）：`compiled/execution_ir.json`、`compiled/prompt_bundle.json`、`compiled/runtime_adapter.json`
  - 约束：任何新增文件都进入 ASVP manifest；runner 暂不依赖 compiled 目录即可执行（先把 compiled 作为审计/回放材料）。
- Bounded Spike（建议 2 个，先证链路，不拍脑袋改主路径）：
  - Spike-SC1：扩展 `skillc build` 生成 `compiled/execution_ir.json` 与 `compiled/prompt_bundle.json`（最小字段集），并新增单测验证产物存在且 JSON 结构合法；运行时先不消费。
  - Spike-SC2：在 `execute_skill_via_llm` 增加“若存在 prompt_bundle 则可选读取”但默认仍用 `contract.logic`（双写过渡）；新增回归测试确保旧包行为不变。
- Kill criteria：
  - 若引入 compiled 目录导致现有 `examples/skills/*` 的 ASVP 验签失败或 `SkillPackageLoader` 变得不向后兼容，则回退为“仅生成不强依赖的审计材料”，并把消费逻辑延期到下一轮。
acceptance:
- 可判定 accepted 的验收标准（命令级）：
  - `skillc build examples/skills/personal_assistant_brief/contract.skill --out /tmp/skillc_dist` 后，`/tmp/skillc_dist/<skill_name>/compiled/execution_ir.json` 与 `.../compiled/prompt_bundle.json` 存在且为 JSON object。
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿，并新增至少 1 个测试覆盖 compiled 产物生成与（可选）读取的向后兼容。
  - `mvp run-skill` 与 `mvp run-package` 对旧 skill 包输出不变（兼容契约不破坏）。
confidence: `medium`

---

id: `20260215-ext_gpt5_2-007`
author: `ext_gpt5_2`
topic: `AgentOS 要解决什么问题（从“没有 AgentOS 会怎样”到可验证口径）`
position:
- 我同意 ext_claude 的核心框架：AgentOS 的本质不是“另一个 LLM 框架（LLM framework）”，而是“让用户更容易且更安全地使用 Agent”的基础设施（infrastructure）。
- 我建议把“没有 AgentOS 会怎样”的表述收敛为一个可验证的问题陈述（problem statement）：
  - 在 Agent 时代，用户的核心成本不再是“能不能跑起来”，而是“能不能信、能不能控、能不能复核、能不能规模化复用”。
  - 没有 OS 级基础设施时，信任（trust）、协作（collaboration）、分发/市场（distribution/market）会碎片化为每个应用/每个 Agent 的私有实现，导致不可审计与不可迁移（non-portable, non-auditable）。
- 对 ext_claude 的三栏表，我给出可实现的工程化定义：
  - 信任基础设施（Trust Infrastructure）= 可验证身份/完整性（identity/integrity）+ 执行证据（evidence/trace）+ 策略执行点（PEP）+ 默认拒绝（fail-closed）。
  - 协作基础设施（Collaboration Infrastructure）= 以文件/证据为中心的异步协作协议与决策门（protocol + decision gate），保证讨论/决策可复核、可回放、可进入准入测试。
  - 市场基础设施（Market/Distribution Infrastructure）= 可签名、可版本化、可回放的 Skill 分发包 + 可引用的 skill_ref（内容寻址或 registry ref）+ 最小安装/更新语义（不必先等“应用商店”形态）。
- 边界澄清：AgentOS 的“OS 类比”更像“软件分发 + 权限/沙箱 + 审计 + 兼容契约”的组合，而不是 UI shell 或模型推理框架；其北极星是“用户可验证的行为与结果（verifiable actions/results）”，而非“开发者更快写 prompt”。
evidence:
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 已定义技能包签名/验证与防注入（信任外壳的工程化定义）。
- `docs/specs/SANDBOXING.md`: 已定义本地/云端沙箱默认规则与 egress 默认禁止（fail-closed 的约束来源）。
- `docs/specs/EXECUTOR_API.md`: 定义 `ExecuteRequest/ExecuteResult`、幂等/超时/trace correlation（“可控+可复核”的统一语义载体）。
- `docs/specs/ADMISSION_TESTS.md` + `docs/specs/RELEASE_CRITERIA.md`: 把“不可破坏约束”与准入测试（admission）制度化，避免碎片化实现。
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md` + `tests/test_admission_expert_collab_protocol.py`: 协作协议被自动化门禁验证（协作基础设施的可执行性证据）。
- `tests/test_mvp_run_package_codex_gating.py`: 远程调用 fail-closed + double gating 的回归证据（信任基础设施的具体行为）。
- `src/agentos_next/release/pack.py` + `tests/test_mvp_rc_pack.py`: RC evidence pack 附带协作引用与 trace/evidence（“可复核”的落盘载体）。
- 命令结果（可复核）：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前全绿，证明以上契约与门禁在工程上已被锁定）。
tradeoffs:
- 把 AgentOS 做成“开发框架/SDK”优先：
  - 收益：更快吸引开发者，短期功能更花哨。
  - 成本/风险：用户侧信任/审计/治理缺位，最终仍回到碎片化与不可迁移，无法形成 OS 级地位。
- 把 AgentOS 做成“用户可验证基础设施”优先（建议）：
  - 收益：能构建跨 Agent 的可复核信任边界，形成分发与生态的长期护城河。
  - 成本/风险：短期 UX/产品层面看起来“没那么炫”；需要持续坚持兼容契约与门禁（工程纪律）。
- 市场基础设施的节奏：
  - 过早做“商店形态”会分散注意力；但完全不定义 skill_ref/安装更新语义，会使“市场”停留在口号。
open_questions:
- “市场基础设施”的最小闭环到底到哪一层：只做到签名包+skill_ref（内容寻址）即可，还是必须立刻实现 registry/索引/更新协议？
- 协作基础设施是否要扩展到“Agent-to-Agent 协作协议”（不仅是专家文档协作），以及它与 evidence/trace 的绑定方式。
proposal:
- 将 AgentOS 的问题陈述写入（或补充到）顶层愿景文档：用“三大基础设施 + 可验证口径”描述，而不是“框架/产品功能清单”。
- Bounded Spike（用于把“市场基础设施”从口号拉到工程事实）：
  - Spike-MKT1：定义并实现最小 `skill_ref` 内容寻址（content-addressed ref），例如基于 `manifest.json` 的 sha256，贯穿 `ExecuteRequest.skill_ref`（仅 local path -> content ref 映射，不引入网络）。
  - Kill criteria：若无法在不破坏 `mvp run-package` 输出契约与 evidence/trace schema 的前提下引入 `skill_ref` 形式化（例如需要 breaking change），则停止该 spike，退回仅在 rc-pack 附带 ref 作为审计材料。
acceptance:
- accepted（本议题对齐通过）的可验证标准：
  - 文档层：在本输入块中形成一致口径（“信任/协作/市场”分别给出工程化定义），并能被 evidence 引用到现有 spec/测试。
  - 工程层（现状已满足）：`PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿，且包含 fail-closed gating、协作协议准入门禁、rc-pack 产物结构回归。
  - Spike-MKT1 若执行：新增测试证明 `skill_ref` 内容寻址可复现（同一 skill 包得到同一 ref），且不改变 `mvp run-package` 标准输出 JSON 字段集合。
confidence: `high`
