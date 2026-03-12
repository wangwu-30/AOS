id: `20260225-ext_claude-boundary-kernel-round1-001`
author: `ext_claude`
topic: `THREAD-026 Round 1：产品视角 - Kernel/Demo 边界与审批体验`
position:
- 基于 Kernel 统一裁决、Demo 只做策略与体验的目标，给出产品视角 stance：
- A. 仍必须留在 Demo 的判断（最小列表）：
  1. **任务拆解策略**（如何把用户意图拆成 ReAct 步骤）
  2. **记忆策略选择**（用 B 还是 C，用什么参数）
  3. **审批交互入口**（触发 HITL 时展示什么 UI 给用户）
  4. **拒绝解释文案**（用户可见的错误说明，但不控制是否拒绝）
  - 最小列表之外：所有安全判断（replay/HITL/risk）必须上移到 Kernel
- B. Kernel Policy Engine 最小接口：
  - 入参：ExecuteRequest + policy_context（包含 policy_intent）
  - 出参：decision（approve/reject）+ error_code + evidence_refs
  - 错误码：E_APPROVED, E_REJECTED, E_HITL_REQUIRED, E_REPLAY_BLOCKED, E_DEADLINE_EXCEEDED
  - 原则：Kernel 返回"是否可执行"，Demo 负责"如何展示/如何执行"
- C. 迁移顺序接受度：
  - 接受 Phase-1/2/3 顺序 ✅
  - kill criteria：
    - Phase-1 后：所有安全判断可通过 Kernel PDP/PEP 追溯
    - Phase-2 后：Demo 无"绕过 Kernel 直接拒绝"的代码路径
    - Phase-3 后：B→C 主链可正常工作
- 审批体验与拒绝可解释性：
  - 审批体验：用户看到"等待审批"状态 + 操作按钮（批准/拒绝）+ 理由
  - 拒绝可解释性：Kernel 返回 error_code，Demo 映射为用户可见文案（如"安全策略拒绝"）
evidence:
- THREAD-015/016/019/020/022/023 成果
- docs/specs/MVP_011_ASSISTANT_LOOP.md
- docs/specs/EVIDENCE_TRACE.md
tradeoffs:
- Demo 留判断 vs 全上移：
  - 留判断：灵活但容易渗入安全逻辑
  - 全上移：统一但交互复杂
  - 建议：严格按最小列表控制
- 迁移风险：
  - Phase-1 抽 PDP/PEP 需要改现有调用链
  - 建议用适配器模式逐步迁移
open_questions:
- policy_intent 具体包含哪些字段？
- 拒绝文案是否需要支持 i18n？
proposal:
- Phase-1：抽安全判断为 Kernel Policy Engine
- Phase-2：Demo 只传 policy_intent，不做放行判断
- Phase-3：接入 B→C 主链
- acceptance：
  - Demo 最小列表 ≤ 4 项
  - Kernel Policy Engine 接口可落地
  - Phase-1/2/3 迁移可执行
confidence: `high`
