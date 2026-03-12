id: `20260224-ext_claude-assistant-arch-001`
author: `ext_claude`
topic: `THREAD-016 Round 1：从用户信任闭环角度评审 3 个决策点（runtime / plugin / golden trace）`
position:
- 冲突 1（P0 runtime 形态）我建议 **C) Hybrid**（event-driven 最小核 + 明确边界，插件化延后）。理由：从用户信任闭环角度看，event-driven 天然适合 daemon/channels/trigger/follow-up 的事件流治理；但完整 event-driven 抽象过高，Hybrid 允许保留现有 direct loop 作为可回放 fallback。
- 冲突 2（P0 plugin/hook system）我建议 **B) P1 再引入**。理由：插件化会增加复杂度与不可预测性，可能破坏"用户信任闭环"的可预测性；P0 应保持简单接口，降低用户理解成本；插件化应基于明确接口契约，不应急于 P0。
- 冲突 3（P0 Golden Trace/Golden Tests）我建议 **A) P0 引入最小 Golden Trace**。理由：这正是"用户信任闭环"的核心——可回放、可审计；覆盖 HITL 审批、soft-cancel、follow-up 三个关键场景的 GT 断言即可满足 P0 可验证性需求。
- 非协商约束保持：不新增 `ExecuteRequest` 顶层字段；扩展走 `policy_context`；replay-mode 无副作用；fail-closed/double-gating 不降级。
evidence:
- THREAD-015 裁决（D/B/A）：`docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
- ai-tutor robot：`dev_wjh_robot:Golden Trace`、`dev_wjh_robot:EVENT_DRIVEN_QUICKSTART.md`（event-driven runtime + trace visualizer）
- AgentOS Next 现有不变量：`docs/specs/EVIDENCE_TRACE.md`、`docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`（HITL 已有基线）
- 当前回归基线：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
tradeoffs:
- Hybrid runtime（P0）：
  - 收益：对 daemon/channels/trigger 语义更自然；事件流天然收敛到 trace/evidence；支持 yield/打断。
  - 风险：event bus 复杂度；若边界不清可能事件风暴；需要保留 direct loop fallback 测试路径。
- plugin 延后 P1：
  - 收益：P0 降低抽象层级，交付更可预测；用户信任来自可理解性而非可扩展性。
  - 风险：后续抽插件可能有迁移成本；但 P0 模块化接口可预留。
- Golden Trace P0：
  - 收益：把"可回放/可审计"从原则变成可执行断言；用户信任闭环的核心支撑。
  - 风险：需要设计最小 GT schema；可能拉长 P0 交付但可控。
open_questions:
- Hybrid 的最小边界：event-driven core 应包含哪些事件类型（USER_INPUT/TRIGGER/TOOL_DONE/SEND_OUTPUT）？哪些仍走现有 assistant loop API？
- Golden Trace 与现有 evidence/trace 复用方式：是引用同一 schema 还是为 UI 额外导出视图？
- plugin P1 的落点：是否仅对 Transport（channels）做 plugin？
proposal:
- Spike-HY1（P0）：Hybrid runtime 最小闭环
  - 范围：event-driven core（USER_INPUT + TRIGGER + TOOL_DONE + SEND_OUTPUT）+ 保留 direct loop 作为 fallback + 单写者语义。
  - 约束：不改 ExecuteRequest 顶层；事件元数据放 policy_context。
  - Kill criteria：
    - event storm 导致任务重复触发超过 1% 阈值；
    - direct loop fallback 无法复现 event-driven 路径结果；
    - replay-mode 下事件序列不可复现。
- Spike-GT1（P0）：最小 Golden Trace
  - 范围：3 条 GT 断言（HITL 审批链路、soft-cancel 可回放、follow-up 触发可追溯）。
  - 约束：复用现有 evidence/trace schema，仅扩展断言层。
  - Kill criteria：
    - 任一 GT 断言失败且无审计日志；
    - GT 覆盖场景无法在 replay-mode 下验证；
    - GT 引入新的副作用或远程调用。
- Spike-PLUG0（可选 P1）：Transport plugin 最小验证
  - 范围：仅对 CLI/WS transport 做 plugin 验证。
  - 约束：仅验证引入一类插件的收益，不进入 P0。
  - Kill criteria：
    - plugin 引入导致原有接口契约破坏；
    - plugin 热加载失败无优雅降级。
acceptance:
- 冲突 1（Hybrid runtime）验收：
  - event-driven + direct loop fallback 两条路径可产出等价结果；
  - 事件流可追溯到 trace_id + evidence_refs；
  - replay-mode 下事件序列可复现。
- 冲突 2（plugin 延后）验收：
  - P0 保持现有模块化接口，不因缺少 plugin 系统而无法交付 UI/HITL/channels；
  - 后续插件化不破坏现有接口契约。
- 冲突 3（Golden Trace P0）验收：
  - 3 条 GT 断言可执行且覆盖核心用户信任场景；
  - GT 失败有明确审计日志；
  - GT 可在 replay-mode 下验证。
- 回归门：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`
