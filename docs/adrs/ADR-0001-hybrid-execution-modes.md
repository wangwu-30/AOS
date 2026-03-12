# ADR-0001 混合执行模式（Hybrid Execution Modes）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/HYBRID_ROUTING.md`、`docs/specs/EXECUTOR_API.md`、`docs/specs/EVIDENCE_TRACE.md`

## 背景（Context）

AgentOS 的愿景要求同时支持：
- 纯本地执行（Local-only）
- 纯远端执行（Remote-only）
- 远端能力扩展（Hybrid: local control + remote capability）

如果将“本地”和“云端”视为两套系统，会导致接口割裂、证据不可串联、治理不可统一，最终无法形成 OS 级生态。

## 决策（Decision）

- 内核必须把“执行后端”抽象为统一的执行器（Executor）。
- 所有执行后端必须遵循相同的语义：幂等（Idempotency）、取消（Cancellation）、超时（Timeout）、重试（Retry）、证据引用（Evidence Refs）、审批门（HITL Gate）。

## 备选方案（Alternatives）

1. 只做云端（Cloud-only）：
   - 优点：统一审计/结算/隔离
   - 缺点：隐私与离线能力弱，设备能力难接
2. 只做本地（Local-only）：
   - 优点：隐私与离线强
   - 缺点：第三方生态安全与供应链难做稳，结算与仲裁困难
3. 两套内核（Local kernel + Cloud kernel）：
   - 优点：各自最优
   - 缺点：语义碎片化，生态成本高，长期不可控

## 取舍（Tradeoffs）

- 统一 Executor 语义会增加早期工程成本，但能避免中后期推倒重来。

## 后果（Consequences）

- 需要明确 `Executor API` 与跨后端的 correlation（trace_id/turn_id/span_id）规范。

## 风险与缓解（Risks & Mitigations）

- 风险：接口过早冻结导致迭代困难。
- 缓解：版本化（Versioning）与兼容策略写入 Specs，并用 golden traces 锁住核心语义。

## 可观测与验收（Metrics & Acceptance）

- 任意技能在本地与云端执行，必须产出可串联的 Evidence/Trace，并可回放。
- 同一幂等键重复调用不会产生重复副作用。

## 后续工作（Follow-ups）

- 完成 `docs/specs/EXECUTOR_API.md` 与 `docs/specs/HYBRID_ROUTING.md`。

