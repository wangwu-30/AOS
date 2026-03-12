# 变更记录（Changelog）

本文件记录近期对维护者和用户可感知的变更。规范文本以 `docs/specs/` 为准。

## 2026-03-08

### Added

- 新增 [项目状态汇报 2026-03-08](/Users/wangwu/codex/agentos-next/docs/guides/PROJECT_STATUS_REPORT_2026-03-08.md)。
- 新增 [内核共识待办](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_CONSENSUS_BACKLOG.md)，作为“已达成但尚未完全落地”的系统共识 SSOT。
- 新增文件化 [会话状态（Conversation State）](/Users/wangwu/codex/agentos-next/src/agentos_next/kernel/conversation_state_store.py) 存储，用于同一会话内恢复最近待办任务与最近交付状态。
- 新增面向新人快速上手的根 [README.md](/Users/wangwu/codex/agentos-next/README.md)，补齐项目定位、阅读顺序、5 分钟启动路径、目录地图与常用命令。

### Changed

- agent/soul 默认配置改为 repo-tracked JSON，运行时优先读 `configs/agent_profiles/*.json` 与 `configs/soul_profiles/*.json`，再读 `data/` override。
- canonical ingress 已升级为 `IngressEnvelopeV1 + runtime_request`，入站 evidence 改为记录 `ingress_envelope`。
- assistant loop 主计划对象已切为 `operator_plan_v1`，followup/scheduler 持久化链已开始写 `operator_ref/arguments`。
- LocalExecutor 与内建 builtin active path 已切到 `operator_ref/arguments`，不再在主链内部使用 `skill_ref/input`。
- PackageRunner 的 HITL policy decision 已收敛为 canonical `allow|ask|deny` 语义。
- 验收与 Telegram 回复提取已放宽为“非空用户可见输出”，不再只接受 `final_output.reply`。
- `llm_execution` prompt 已移除 transport-specific UX 规则，并重排为 `Stable Kernel Prefix -> Communication Prefix -> Task Block -> Memory/Observation -> Skill Output Contract`。
- `channel-http`、`channel-stdio`、`ui-run-once`、remote payload 与 turn manifest 已统一切到 `operator_ref/arguments`，只保留最薄的历史读兼容。
- 例子技能包 `examples/skills/personal_assistant_brief` 已重签，修复默认 ASVP 路径被未签名 `artifacts/compiled/*` 污染后 fail-closed 的问题。
- Query Compile 新增 `solution_query`，在 planner 前先从状态、继续合同与本地操作符线索推导“先怎么解决”，再展开计划。
- assistant loop 现在在 `preserve_pending_contract=true` 时保留原继续合同，低信息 follow-up 不再覆盖原待办目标。
- `simple` 模式下若 `solution_query.approach_strategy=llm_self_check`，允许一次性的 LLM 自查进入 planner，而不是被模式门直接砍掉。
- Query Compile 新增 `intent_recovery`、`interaction_mode`、`model_routing_policy` 三个结构化对象。
- `开始 / OK / 继续 / 结果呢` 一类上下文依赖输入现在优先走固定选项 + 可选备注的工程恢复，而不是默认直接交给执行 prompt 猜测。
- assistant loop 现在会在同一 `conversation_id` 下回收最近任务状态，使后续确认类输入可以恢复到上一任务目标。
- assistant plan 现在显式记录 `interaction_mode` 与模型路由策略摘要，为后续多模型路由铺接口。
- Query Compile 新增 `task_requirements`，开始以“需要什么证据/操作/交付”而不是表层关键词驱动模式选择与计划。
- Assistant Loop 对 workspace-analysis 任务新增 inspect-first 计划，具备 `fs.list/shell.exec` 观测后再交付的最小闭环。
- 会话状态新增 `pending_contract`，运行时不再把 `OK/开始/继续` 一类低信息输入直接写回为待办任务。
- 执行 prompt 改为 kernel-first；存在 `execution_prefix` 时，不再以前置 persona/skill lore 主导执行 prompt。
- PA memory context 开始从 `C0/C1/C2/C3/C4` 全文拼接转向 `capsules` 摘要装配。
- 术语口径开始收敛为 `Meta Context + L0 Snapshot + L1 Index + L2 Retrieved Evidence Pack`，`C0/C1/C2/C3/C4` 退化为兼容别名。
- AgentProfile 与运行时计划开始同时输出 `operator_resolution` 与 legacy `capability_resolution`，为后续术语迁移保留兼容层。
- policy evidence 新增 canonical `policy_disposition=allow|ask|deny`，并兼容既有 `decision=allow|deny|require_approval`。

### Fixed

- 修复上下文依赖短输入在缺少显式状态恢复时被当成新任务原文执行，导致 `开始 / OK / 继续` 易歧义的问题。
- 修复“分析项目/评审代码/给建议”一类任务被误判为 `simple` 并直接输出无证据建议的问题。
- 修复执行 prompt 中旧 persona prompt 压过 `公理 + 约束 + 任务需求` 前缀的问题。
- 修复标准模式无条件插入 `memory.search` 导致 capability 不满足时平白失败的问题。

### Docs

- 更新 Query-Gated Runtime、Agent Axioms、ADR 与 Axiom Kernel 设计文档，冻结 `Solution Query`、任务需求推导、继续合同与胶囊化上下文的最小 contract。
- 更新 backlog / 项目状态 / 变更记录，补记 `AgentProfileV2`、`SoulProfileV1`、`IngressEnvelopeV1`、`RuntimeSnapshotV1`、`OutputEventV1` 与 canonical operator 执行语义的当前落地状态。

## 2026-03-07

### Added

- 新增 [运维与维护指南](/Users/wangwu/codex/agentos-next/docs/guides/README.md) 目录。
- 新增 [PA 值班速查卡](/Users/wangwu/codex/agentos-next/docs/guides/PA_ONCALL_QUICK_REFERENCE.md)。
- 新增 [PA 日志字段说明](/Users/wangwu/codex/agentos-next/docs/guides/PA_LOG_FIELD_REFERENCE.md)。
- 新增 [PA 架构总览](/Users/wangwu/codex/agentos-next/docs/guides/PA_ARCHITECTURE_OVERVIEW.md)。
- 新增 [PA 排障手册](/Users/wangwu/codex/agentos-next/docs/guides/PA_TROUBLESHOOTING_RUNBOOK.md)。
- 新增 [PA 修复经验](/Users/wangwu/codex/agentos-next/docs/guides/PA_REPAIR_NOTES_2026Q1.md)。
- 新增 [故障复盘模板](/Users/wangwu/codex/agentos-next/docs/guides/INCIDENT_TEMPLATE.md)。
- PA provider 在“首个 delta 前”的瞬态 TLS EOF 场景增加一次自愈重试。
- Telegram PA 流式回复增加 typing 心跳、后台发送线程与本地 chunk 缓冲。

### Changed

- polling 模式默认从 offset 检查点续跑，不再依赖手工 offset 管理。
- offset 未变化时不再重复打印 checkpoint 日志。
- 内置 `fs.read` / `fs.list` / `shell.exec` 增加工作区路径归一化，支持 `~` 与跨机器仓库绝对路径别名回落到当前 workspace。
- PA 聚合节点现在显式携带工具成功/失败审计摘要，失败不再静默吞掉。
- `agent_profile/context_planes` 现在进入技能执行 prompt，PA 默认公理新增“结果真实性、阻塞转最小纠正、最小能力持续完成”约束。
- PA 错误兜底与运维诊断分离：
  - 用户继续收到稳定兜底文案。
  - 终端与 evidence 保留 provider 细节。
- 搜索能力改为显式路由：
  - `Brave Search API`
  - `Browser Use Bridge`
  - HTML fallback

### Fixed

- 修复 polling 重启后历史 update 回放导致“收到消息但没回复”。
- 修复 EV1 已生成失败 outbox 时，polling 没有稳定发送兜底回复。
- 修复 provider 仅暴露裸 `E_PROVIDER_BAD_RESPONSE` 导致无法诊断。
- 修复近期 Telegram PA 对 `~/codex/agentos-next` 一类仓库路径展开失败，导致项目分析动作全部失败后只返回占位式答复。
- 修复 `editMessageText` 返回 `message is not modified` 时被误记为 Telegram 出站失败。
- 修复 Telegram `editMessageText` 阻塞 provider SSE 读取，导致流式卡顿与超时。
- 修复 typing 状态提前结束。
- 修复流式回复逐字抖动、体验劣化问题。

### Docs

- 补充 Telegram PA 维护文档，统一架构说明、排障路径与历史修复经验。
