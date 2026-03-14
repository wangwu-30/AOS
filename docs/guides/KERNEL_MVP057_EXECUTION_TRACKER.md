# Kernel MVP_057 执行跟踪表（Execution Tracker）

- 日期（Date）：2026-03-14
- 状态（Status）：Active
- 单一事实源（SSOT）：本文档是 ADR-0022 / MVP_057 代码推进状态的跟踪面。
- 方案入口（Plan）：
  - [Kernel MVP_057 实施方案](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_IMPLEMENTATION_PLAN.md)

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
- 条目完成后，应同步更新：
  - [Kernel MVP_057 实施方案](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_IMPLEMENTATION_PLAN.md)
  - [变更记录](/Users/wangwu/codex/agentos-next/CHANGELOG.md)

## 当前优先项（Current Priorities）

### W1. OperatorContractV1 最小落地

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/operator_catalog.py`
- 输出（Output）：
  - 为现有 operator 补 `purity`、`visibility`
  - 其余 `OperatorContractV1` 字段走 compatibility default
- 验收（Acceptance）：
  - catalog 中每个 active operator 都能被归类为 `canonical / compat / internal`
  - effect purity 不再只靠散落逻辑推断

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

### W4. ResourceEscalationRequestV1

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 1`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `src/agentos_next/kernel/task_service.py`
- 输出（Output）：
  - `ResourceEscalationRequestV1` 最小结构
  - `max_escalation_count` 与 `side_effect_boundary_reached` 联动
- 验收（Acceptance）：
  - 共享资源升级请求有统一协议
  - 超过升级上限会进入 `hold` 或 `need_context`

### W5. ResourceBudgetV1 admission bridge

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 2`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/execution_lane.py`
- 输出（Output）：
  - 旧 budget 字段与 `ResourceBudgetV1` 并存归一化
  - `legacy_token_budget_to_compute_units(max_total_tokens)` 单点映射
- 验收（Acceptance）：
  - admission trace 可见标准化后的 `ResourceBudgetV1`
  - `side_effect_calls_max` 与 `delivery_ops_max` 先成为硬约束

### W6. TaskContextSnapshotV1 编译基础设施

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 2`
- 优先级（Priority）：`P0`
- 目标文件（Target Files）：
  - `src/agentos_next/kernel/context_compiler.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
  - `src/agentos_next/kernel/task_service.py`
- 输出（Output）：
  - `snapshot_id / frozen_at_generation / context_segments / open_gaps`
  - `content_hash` 计算
  - `token_estimate` 估算
- 验收（Acceptance）：
  - snapshot 在 trace/evidence 中可见
  - stale generation 可被明确判定

### W7. SemanticSyscallV1 首批试点

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 3`
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
  - compat path 默认从 reasoning surface 隐藏

### W8. 应用层语义迁移审计

- 状态（Status）：`todo`
- 阶段（Phase）：`Phase 4`
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

## 推荐近期推进（Next Recommended Moves）

1. 先做 `W2 hold delivery gate`，因为它直接修复最可见的用户问题。
2. 接着做 `W1 OperatorContractV1 最小落地`，为 Phase 2/3 提供 catalog 基础。
3. 然后并行推进 `W3 Information Sufficiency` 和 `W4 ResourceEscalationRequestV1`。
4. Phase 1 完成后再进入 `W5/W6`。

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

- `W1` 到 `W6` 全部完成后，可以认为 Kernel MVP_057 首轮 runtime 基础设施落地完成。
- `W7` 完成后，可以认为 semantic syscall 进入可验证试点阶段。
- `W8` 完成后，可以认为应用层与内核边界开始进入目录级收敛阶段。
