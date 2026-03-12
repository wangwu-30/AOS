# 项目状态汇报（Project Status Report）

- 日期（Date）：2026-03-08
- 范围（Scope）：Assistant Runtime / Telegram PA / Context & Intent / Model Routing

## 当前状态（Current State）

未完全落地但已达成的系统共识，统一记录在：
- [内核共识待办](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_CONSENSUS_BACKLOG.md)

项目主链已经从“多入口、多语义”收口到：

`Submitter Adapter -> Canonical Task Ingress -> Query-Gated Runtime -> Assistant Loop -> Verify -> Consumer Adapter`

当前已完成的关键能力：
- repo-tracked `AgentProfileV2` / `SoulProfileV1` 默认配置已落地，并支持 `data/` override。
- 规范任务入口（Canonical Task Ingress）已升级为 `IngressEnvelopeV1 + runtime_request`。
- 单一运行时（Single Runtime）与规范任务入口（Canonical Task Ingress）已经落地。
- Runtime Snapshot 已文件化为 `RuntimeSnapshotV1`，并作为会话恢复的 canonical 状态层。
- 查询编译（Query Compile）已产出 `TaskEnvelopeV1`、`DeliveryContractV1`、`execution_prefix`、`communication_prefix`。
- 查询编译（Query Compile）已新增 `SolutionQueryV1`，开始先从状态、继续合同与本地操作符线索推导“先怎么解决”，再展开 plan。
- 查询编译（Query Compile）已开始消费 `Global Capsule`、`Project Capsule`、theorem 候选与 operator catalog 结果。
- 查询编译（Query Compile）已新增 `TaskRequirementsV1`，开始以“证据/操作/交付需求”而不是表层关键词驱动复杂度与计划。
- Theorem/SOP 持久化与 `operator.search` 已有可运行实现，开始进入 assistant 主链。
- assistant loop 计划对象已经收敛为 `operator_plan_v1`，followup/scheduler 持久化链开始写 `operator_ref/arguments`。
- `channel-http`、`channel-stdio`、`ui-run-once`、remote payload、turn manifest 已切到 canonical `operator_ref/arguments`。
- 交付生命周期（Delivery Lifecycle）`ack/progress/blocker/done` 已进入 trace 与 rehydration。
- `OutputEventV1` 与 runtime event log 已落地，TG polling 已消费 `ack/progress/reply_delta`。
- Telegram polling 已接入 canonical runtime，并恢复原生流式回复。
- C2 记忆召回已增加 tag 子集匹配、强时效 -> 弱时效 -> 软删除 fallback 分层过滤。
- 上下文依赖输入已进入最小意图恢复（Intent Recovery）链路，支持固定选项 + 可选备注，并开始使用 `Continuation Contract` 而不是直接回写低信息短语。
- PA memory context 已开始从全文拼接转向 `capsules` 摘要装配。
- 运行时已产出最小模型路由策略（Model Routing Policy）对象，用于区分 `task|confirm|status|chat`。
- 上下文术语已开始收敛为 `Meta Context + L0 Snapshot + L1 Index + L2 Retrieved Evidence Pack`，`C0/C1/C2/C3/C4` 退化为兼容别名。
- AgentProfile / Query Compile / Assistant Plan 已开始同时输出 `operator_resolution` 与 legacy `capability_resolution`。
- policy evidence 已新增 canonical `policy_disposition=allow|ask|deny`，并兼容既有 `decision=allow|deny|require_approval`。

## 目标状态（Target State）

目标不是“更会聊天”，而是：
- 可推导
- 可执行
- 可审计
- 可自演进

面向个人助理（Personal Assistant）场景，目标态还要求：
- 多项目切换不污染上下文
- `开始 / OK / 继续` 一类输入具备稳定工程解释
- 模型能力可以按复杂度、交互模式与用户偏好动态路由

## 当前差距（Gap Analysis）

还未完全收敛的点主要有六个：

1. 项目级上下文（Project Capsule）尚未正式落地
- 当前已有 `ProjectCapsuleV1 + ActiveProjectResolverV1` 雏形，但项目命名空间与多项目切换治理还未完全冻结。

2. Solution Query 已立住，但 LLM 自查仍是轻量版
- 当前已具备 `local_skill_first / theorem_guided / llm_self_check` 的结构化 contract，也能避免低信息 follow-up 覆盖原合同。
- 但真正的单次 LLM 自查还没有完全升级成独立、稳定的内核 operator。

3. Continuation Contract 仍是最小版
- 当前已避免把 `OK/继续` 写成待办任务，但 `expected_next_user_act`、`active_project_id`、`last_clarification_question` 的利用还不够充分。

4. 模型路由策略尚未真正驱动多模型调度
- 当前已冻结策略对象与交互模式，但还没有真正的 `weak_to_strong` / `planner_first` 动态执行器。

5. 用户显式控制面尚未开放
- 还没有把“省钱优先 / 平衡 / 高质量 / 闲聊优先”等模式正式开放给用户选择。

6. LLM 主契约仍未完全从 Skill Output Schema 脱钩
- 当前 planner 已是 `operator_plan_v1`，但 skill 执行层仍会把 `outputs_schema` 直接用于 LLM 输出 contract。
- assistant runtime 虽已放宽对 `reply` 的硬依赖，但还没有完全切到“模型只产 operator plan”的终态。

## 下一步（Next Steps）

建议按以下顺序推进：

1. 完成 `OperatorPlanV1` 与 skill `outputs_schema` 的彻底脱钩。
2. 收掉残余 `skill_ref/input` active path（当前主要剩 legacy EV1 / registry 历史命名 / 少量文档与测试样例）。
3. 冻结 `Project Capsule` 与 `Active Project Resolver` 规范。
4. 把 `SolutionQueryV2` 的 `llm_self_check` 升级为真正单次推理内核能力。
5. 把模型路由策略从审计对象升级为真实 runtime 决策。
6. 增加用户可覆盖的交互模式/模型偏好入口。
