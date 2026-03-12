# ADR-0020：控制器执行通道路由与本地未签名技能分层

- 状态（Status）：Accepted
- 日期（Date）：2026-03-13
- 相关规范（Related Specs）：
  - `docs/specs/MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT.md`
  - `docs/specs/MVP_056_LOCAL_UNSIGNED_SKILL_AND_COMPAT.md`
  - `docs/specs/SKILL_CREATOR.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`

## 背景（Context）

现有实现已经具备 `KernelTaskService`、`task_execution_graph_v1` 与 `WorkerReActRuntime` 的基础能力，但 controller 仍保留明显的 phase-loop / batch-loop 痕迹：

- lane 路由分散在 phase override 与 prompt policy 中，缺少稳定的任务级 `Execution Lane`
- 默认执行仍受固定 `replan_budget / loops_max` 影响，而不是 token/time/progress 驱动
- `HITL_REQUIRED` 被混杂在失败分支中，暂停与失败语义不清
- 本地 unsigned skill 与正式 hub skill 没有清晰分层，`verify_asvp=false` 的本地执行会误伤普通本地 skill
- 用户紧接着补充纠正时，缺少稳定的 `submission / generation / supersede / stale rejection` 语义

这些问题会直接削弱系统的连续执行、任务修订与审计一致性。

## 决策（Decision）

采纳以下不可逆决策：

1. Kernel 作为唯一执行底座，冻结为五个 primitive：
   - `Task Service`
   - `Task Execution Graph`
   - `Skill Execute API`
   - `Worker ReAct Runtime`
   - `Policy / Evidence / Replay`
2. Controller 只路由任务级执行通道（Execution Lane），不得逐步接管 worker 的 tool-by-tool 执行。
3. 默认执行模式改为 token/time/progress 驱动的持续执行；固定 batch / replan 次数退出不再是 canonical 行为。
4. `hold` 与 `HITL_REQUIRED` 正式定义为可恢复暂停态，而不是失败态。
5. 本地未签名技能（Local Unsigned Skill）与正式技能中心（Skill Hub）分层：
   - hub 只容纳 `registry:// + ASVP` 的标准 skill
   - local unsigned skill 只存在于本地层，并按 fingerprint 审批
6. 任务修订（Task Amendment）采用 `submission_id + generation + supersede + stale result rejection` 的组合语义。

## 备选方案（Alternatives）

### 方案 A：保留 controller 的 batch/replan loop 作为默认执行模型

未采纳。原因：

- 与“持续执行直到完成”的目标冲突
- 容易把复杂任务截断在固定批次边界
- lane insufficiency 与 no-progress 无法区分为“应升档”还是“应暂停”

### 方案 B：让 worker 自行升级模型与 lane

未采纳。原因：

- 破坏任务级审计与 admission-time policy
- 无法稳定复盘 controller 的路由证据
- 不利于多 provider / 多模型池的一致治理

### 方案 C：把 local unsigned skill 直接并入正式 hub

未采纳。原因：

- 会稀释 ASVP、发布治理与 registry canonical 语义
- 用户本地试验技能与可发布技能的信任等级不同
- remember-by-fingerprint 的人类批准无法替代签名发布

## 取舍（Tradeoffs）

收益：

- controller 与 worker 边界更清晰，任务级路由与 worker 内执行各归其位
- lane、submission、generation、hold、supersede 全部进入 evidence/trace，可审计性更强
- 本地 unsigned skill 不再污染正式 hub，治理边界更清晰

代价：

- `assistant_loop` 需要从 legacy batch logic 迁移到 controller-managed worker graph
- 需要维护更多 kernel-level 状态字段，如 `submission_id / generation / effect_class / side_effect_boundary_reached`
- 旧测试与旧文档中“replan budget exhaustion”一类语义必须同步迁移

## 后果（Consequences）

- `controller_routing_decision_v1` 成为 lane 路由的 canonical evidence
- `execution_lane_replan_v1` 成为 lane 升档的 canonical evidence
- `E_DEADLINE_EXCEEDED`、`E_TOKEN_BUDGET_EXHAUSTED`、`E_NO_PROGRESS` 默认进入 `hold`
- 本地 unsigned skill 的批准只适用于 local layer；普通本地 skill 不得被误判为 local unsigned
- `skill-creator` 的默认产物成为 `.agentos/local_skills/` 下的 local unsigned skill

## 风险与缓解（Risks & Mitigations）

- 风险：controller guard 误把无害路径判成 no-progress 或 hold。
  - 缓解：把 lane policy、controller execution mode 与 hold-class error code 全部写入 evidence；补 thread045 回归测试。
- 风险：本地 unsigned skill 的批准逻辑在多个模块重复实现，导致行为漂移。
  - 缓解：将 fingerprint 计算与 remembered approval 收敛到 kernel approval store。
- 风险：side-effect task 在 amendment 后被静默覆盖。
  - 缓解：引入 `effect_class + side_effect_boundary`，并要求越界后转 hold/blocker/HITL。

## 可观测与验收（Metrics & Acceptance）

必须可观测：

- controller 选择的 `execution_lane` 与 `execution_lane_policy`
- lane promotion evidence
- `submission_id` / `generation` / supersede event
- local unsigned skill 的 fingerprint 与 approval memory

验收命令：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_emits_query_gated_evidence_and_simple_plan -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web.TestThread047RuntimeCapabilitiesAndWeb.test_builtin_creator_write_local_skill_uses_local_unsigned_layer -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread055_kernel_execution_lane_and_local_skill -v`

## 后续工作（Follow-ups）

- 将 `skill-creator` 以 first-party `AgentOS Skill` 包形式暴露，而不只作为 builtin creator 能力存在
- 为 `Task Amendment` 增补专门的集成测试，覆盖 active submission 自动 supersede 与 stale result rejection
- 将 compat skill / MCP 的 effect declaration 与 policy gate 继续收紧到更细粒度的 operator contract

## 参考架构取舍（Adopt / Reject）

- 借鉴 `OpenHands` 的 typed runtime：采纳其“执行面强类型、事件可审计”的方向，但不照搬多层 agent/runtime 结构。
- 借鉴 `pi` 的 minimal loop：采纳“默认主链尽量短”的原则，但 reject 其把复杂任务也压成单薄 loop 的做法。
- 借鉴 `Goose` 的 MCP 接入：采纳 MCP 通过 adapter 接到统一 operator ABI 的思路，但 reject 暴露 MCP transport/session 给 worker 的做法。
