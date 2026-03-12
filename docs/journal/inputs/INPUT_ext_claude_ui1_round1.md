id: `20260225-ext_claude-ui1-round1-001`
author: `ext_claude`
topic: `THREAD-021 Round 1：产品流与验收口径（最小 TUI + HITL 审批 + trace 可视化）`
position:
- 基于 THREAD-026 Kernel Policy Engine 边界，给出 UI1 产品视角输入：
- P0 目标：
  1. 最小 TUI 交互入口：任务输入 + 状态展示
  2. HITL 审批视图：pending/approved/rejected + reason + evidence_refs
  3. trace/evidence 可视化最小闭环
- 建议 UI 流：
  1. 用户输入任务 → 进入 "pending" 状态
  2. 若需要审批 → 展示 HITL 审批视图（显示 reason + evidence_refs）
  3. 用户批准/拒绝 → 返回结果
  4. 执行完成 → 展示 trace/evidence 可视化
- 审批体验字段（基于 THREAD-026）：
  - status: pending_approval | approved | rejected
  - action: [approve, reject, modify]
  - risk_level: high | medium | low
  - reason: 结构化理由
  - evidence_refs: 关联证据
- 状态机（建议）：
  - pending → approved → done
  - pending → rejected → done
  - pending → timeout → done
evidence:
- THREAD-026 成果（Kernel Policy Engine）
- docs/specs/MVP_014_DIALOG_STATE_MACHINE.md
- docs/specs/EVIDENCE_TRACE.md
tradeoffs:
- TUI vs Web UI：
  - TUI：快速实现、调试友好
  - Web UI：交互更丰富
  - 建议：P0 TUI 起步
- 审批流设计：
  - 同步审批：用户在线等待
  - 异步审批：用户可离开，后续回来查看
  - 建议：P0 同步审批，后续可扩展异步
open_questions:
- 是否需要"修改任务"功能（审批时允许修改后重批）？
- trace 可视化是否需要支持"折叠/展开"？
proposal:
- Spike-UI1（P0）：
  - TUI 入口：mvp assistant tui
  - 审批视图：展示 status/action/risk_level/reason/evidence_refs
  - trace 可视化：展示完整执行链路
  - Kill criteria：
    - replay-mode 下 UI 操作产生副作用 → 回退
    - 审批状态无法追溯到 evidence_refs → 回退
    - 违反 fail-closed / double-gating → 回退
acceptance:
- TUI 可输入任务并展示状态 ✅
- HITL 审批视图完整 ✅
- trace/evidence 可追溯 ✅
- 约束保持 ✅
confidence: `high`
