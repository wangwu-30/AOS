# SYNTHESIS: Spike-SCHED1 (Scheduler P0 Primitives)

- `thread_id`: `20260219-SCHED1-008`
- `updated_at`: `2026-02-19`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

目标（Goal）：交付 Scheduler P0 原语（Scheduler Primitives），在不引入常驻 daemon 的前提下，支持“持久化的延迟/定时触发（durable delayed/cron trigger）”，并且触发执行语义严格复用 `Orchestrator.execute(ExecuteRequest)`（含 fail-closed、deadline、idempotency、evidence/trace）。

统一口径（Consensus）：
- API 形态：对外（给 Skill/Assistant 使用）提供 `builtin://scheduler.at` 与 `builtin://scheduler.cron` 两个特权技能（privileged skills），仅负责落盘任务定义。
- 触发驱动：MVP 采用显式 runner/tick（显式执行 `scheduler_tick(now)`），由 CLI 或集成测试驱动，不依赖后台常驻。
- 治理（Governance）：任务定义中的 `execute_request.policy_context` 不能在触发时扩权；触发时强制覆盖/锁定 replay-mode、remote_calls_armed、allow_network_egress、approved_by_human 等关键开关，保持 fail-closed。
- 可回放（Replayable）：任务定义快照 + 触发记录必须落 Evidence/Trace，且触发后执行本身的 evidence/trace 仍按现有路径产生。

Bounded Spike（限界实验）建议（用于避免“无 runner 无法验收”）：
- Spike-SCHED1 内允许新增一个 internal runner（CLI 子命令或库函数），以 deterministic `--now` 驱动 due tasks 触发。
- Kill criteria：若 runner/tick 的引入导致既有 CLI 输出字段变化、或破坏 replay-mode 远程禁用/double-gating，则回退为“仅能创建任务，不提供触发机制”，并将触发延期到下一阶段（但该 spike 将标记为 needs_decision）。

## Evidence（证据）

- `docs/specs/MVP_012_SCHEDULER.md`（数据模型/cron 子集/特权技能 I/O/验收）
- `docs/specs/EXECUTOR_API.md`（ExecuteRequest/ExecuteResult 的幂等/超时/目标语义）
- `docs/specs/EVIDENCE_TRACE.md`（Evidence/Trace schema 与可回放约束）
- `docs/specs/LLM_PROVIDER.md`（replay-mode + double-gating 的不可降级约束）
