# Kernel MVP_057 执行跟踪表（Execution Tracker）

- 日期（Date）：2026-03-14
- 状态（Status）：Active
- 单一事实源（SSOT）：本文档是 ADR-0022 / MVP_057 代码推进状态的跟踪面。
- 方案入口（Plan）：
  - [Kernel MVP_057 实施方案](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_IMPLEMENTATION_PLAN.md)
- 当前安全回退点（Safety Checkpoint）：
  - `47c850e` `runtime: land kernel charter docs and PA hold fixes`

## 状态定义（Status Legend）

- `todo`：方向明确，尚未开始。
- `in_progress`：已经开始，有代码或测试入口在推进。
- `blocked`：有上游依赖，当前不能安全推进。
- `done`：代码、测试、文档已形成闭环。

## 使用规则（Operating Rules）

- 每个工作流必须包含：
  - `状态（Status）`
  - `阶段（Phase）`
  - `优先级（Priority）`
  - `目标文件（Target Files）`
  - `验收（Acceptance）`
- 推进中若发现需要改变 ADR-0022 或 MVP_057 的冻结边界，必须先改 ADR / Spec，再改状态。
- 当前计划默认直接切到 canonical V1 主路径。
- 条目完成后，应同步更新：
  - [Kernel MVP_057 实施方案](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_IMPLEMENTATION_PLAN.md)
  - [变更记录](/Users/wangwu/codex/agentos-next/CHANGELOG.md)

## 当前优先项（Current Priorities）

### W0. 安全点确认与 canonical V1 类型冻结

- 状态（Status）：`in_progress`
- 阶段（Phase）：`Phase 0`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/types.py`
- 输出（Output）：
  - 安全回退点 commit `47c850e` 已完成（done）
  - canonical V1 类型冻结尚未开始（todo）
  - 在单一类型入口中定义：
    - `ResourceBudgetV1`
    - `ResourceCostVectorV1`
    - `OperatorContractV1`
    - `TaskSpecV1`
    - `TaskContextSnapshotV1`
    - `AssumptionEvidenceV1`
    - `ResourceEscalationRequestV1`
- 验收（Acceptance）：
  - 所有 V1 类型均可从单一模块导入
  - 无需在多个模块重复拼装 canonical schema

### W9. 旧字段全局替换为 ResourceBudgetV1

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/task_execution_graph.py`
  - `src/agentos_next/kernel/execution_lane.py`
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `tests/`
- 输出（Output）：
  - 删除 `tool_budget / token_budget / stop_policy / time_budget_ms`
  - 统一替换为 `resource_budget: ResourceBudgetV1`
  - 删除 `TokenBudget / StopPolicy` 旧类与相关 helper
  - `completion_contract_ref` 统一重命名为 `acceptance_contract_ref`
  - `task_execution_policy` 从 `TaskSpec / TaskRecord / TaskExecutionNode` 移出；其行为策略语义迁移到 `ExecutionLaneProfile` 或等价 `WorkerRuntimeConfig`
  - `StopPolicy.no_progress_window / max_repeated_action_fingerprint_hits / continue_until_terminal` 等行为策略不进入 `ResourceBudgetV1`
- 验收（Acceptance）：
  - `grep -r "tool_budget\\|token_budget\\|stop_policy" src/ tests/` 返回空
  - `execution_lane.py` 中不再保留 `TokenBudget / StopPolicy`
  - `task_service.py`、`task_execution_graph.py` 中不再保留 `completion_contract_ref`

### W1. OperatorContractV1 完整落地

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/operator_catalog.py`
  - `src/agentos_next/kernel/types.py`
- 输出（Output）：
  - 定义 `@dataclass(frozen=True) OperatorContractV1`
  - `_catalog_entries()` 返回结构化 contract，而不是 `dict`
  - `search_operator_catalog()` 返回值改为 `list[OperatorContractV1]` 或等价结构化类型
  - 完整覆盖 spec 要求字段：
    - `operator_ref`
    - `purity`
    - `idempotency_class`
    - `retry_class`
    - `preflight_required`
    - `degraded_behavior`
    - `resource_cost_vector`
    - `visibility`
- 验收（Acceptance）：
  - `operator_catalog.py` 中不再有 raw dict entry 作为主 contract
  - catalog 查询调用方不再依赖 `entry[\"operator_ref\"]` 这类 dict key access
  - 类型检查与现有 catalog 查询路径通过

### W2. hold delivery gate

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/apps/pa_assistant_runtime_dispatcher.py`
  - `src/agentos_next/apps/query_gated_runtime.py`
- 输出（Output）：
  - 在 `hold` 终态校验 delivery artifact
  - 空 `reply_text` / 空 `deliveries` 进入显式错误路径
- 验收（Acceptance）：
  - `E_HOLD_DELIVERY_MISSING` 有真实触发点
  - PA 路径不会再出现 `hold` 但用户无任何可见消息

### W3. Information Sufficiency 入口

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `src/agentos_next/kernel/task_service.py`
- 输出（Output）：
  - 显式 `resolve_information_gap(...)` 或等价入口
  - 四条路径：
    - `auto_enrich`
    - `assumption_continue`
    - `need_context`
    - `leader_escalation`
- 验收（Acceptance）：
  - worker 遇到信息不足时不再只靠 prompt 漫游
  - `need_context` 与 `leader_escalation` 可在 trace 中区分

### W4. ResourceEscalationRequestV1 运行时入口

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/types.py`
- 输出（Output）：
  - `ResourceEscalationRequestV1` 最小结构
  - `max_escalation_count` 与 `side_effect_boundary_reached` 联动
- 验收（Acceptance）：
  - 共享资源升级请求有统一协议
  - 超过升级上限会进入 `hold` 或 `need_context`

### W5. TaskContextSnapshotV1 直接落地

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/context_compiler.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/types.py`
- 输出（Output）：
  - 定义 `@dataclass(frozen=True) TaskContextSnapshotV1`
  - 实现 `compile_snapshot(...)`
  - 实现 `content_hash = sha256(normalized)[:16]`
  - `token_estimate` 首版使用 `len(text) // 4` 或等价 heuristic
- 验收（Acceptance）：
  - snapshot 可以被构造、序列化、反序列化
  - `content_hash` 可稳定计算
  - snapshot 在 trace/evidence 中可见

### W6. SemanticSyscallV1 首批试点

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 2`
- 优先级（Priority）：`P1`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/syscall_registry.py`
  - `src/agentos_next/runtime/builtin_memory.py`
  - `src/agentos_next/skills/llm_execution.py`
  - `src/agentos_next/kernel/operator_catalog.py`
- 输出（Output）：
  - `memory.recall / memory.persist / memory.forget`
  - syscall 到 operator 的 evidence 链
- 验收（Acceptance）：
  - 至少一条 memory 路径不再由模型直接构造 raw operator payload
  - 推理面默认优先 syscall

### W7. 应用层语义迁移审计

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 3`
- 优先级（Priority）：`P1`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/soul_profile.py`
  - `src/agentos_next/kernel/agent_profile.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
  - `src/agentos_next/apps/`
- 输出（Output）：
  - persona / 产品语义 / 应用对象的归属审计
  - `application_context_ref` 的真实使用路径
- 验收（Acceptance）：
  - 能明确区分 kernel contract 与 app semantics
  - PA Program / Workstream 不进入 kernel primitive

### W8. 旧数据迁移或清理脚本

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P1`
- 目标文件（Target Files）：
  - `scripts/`
  - `src/agentos_next/kernel/task_service.py`
  - `docs/guides/`
- 输出（Output）：
  - 若 canonical cutover 后旧持久化数据无法读取，提供一次性 migration script 或手动清理指引
- 验收（Acceptance）：
  - 不依赖运行时 fallback 也能恢复到一致状态

## 推荐近期推进（Next Recommended Moves）

1. 先完成 `W0` 的 canonical 类型冻结。
2. 立即推进 `W9`，把旧 budget 字段全局替换掉。
3. 再做 `W1`，把 operator catalog 从 dict 切成完整 dataclass。
4. 接着推进 `W5`。
5. 然后推进 `W2`、`W3`、`W4`。
6. `Phase 1` 稳定后进入 `W6`，最后再做 `W7`。

## PA 标准用例（PA Standard Scenario）

标准验证输入：

- “把 A/B/C 三个项目都推进一下，先处理公共依赖问题。”

跟踪要求：

- 若 `project_A` worker 执行中才发现共享资源 `dependency:X`，必须记录：
  - 当前 `task_id / generation`
  - `side_effect_boundary_reached`
  - 是否触发 `ResourceEscalationRequestV1`
  - 最终进入 `leader_escalation / hold / need_context` 中的哪一条路径

## 建议测试（Suggested Verification）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_spike_memapi1_builtin_memory -v`

## 退出条件（Exit Criteria）

- `W0` 到 `W5` 与 `W9` 全部完成后，可以认为 canonical V1 cutover 完成。
- `W6` 完成后，可以认为 semantic syscall 进入可验证试点阶段。
- `W7` 完成后，可以认为应用层与内核边界开始进入目录级收敛阶段。
