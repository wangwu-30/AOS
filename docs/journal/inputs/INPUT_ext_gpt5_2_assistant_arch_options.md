id: `20260224-ext_gpt5_2-assistant-arch-001`
author: `ext_gpt5_2`
topic: `个人助理应用层（assistant app layer）参考架构：OpenClaw（能力对标）× ai-tutor（架构模式）择优组合`
position:
- 我同意 host 的澄清：对标 OpenClaw 是能力对标（capability benchmark），不是架构对标；我们不应“照抄 OpenClaw 架构”，而应以 AgentOS Next 的不变量为第一约束，在上层应用中择优吸收模式。
- 我建议本轮 3 个决策点的推荐口径为：Decision001 选 C（Hybrid event-driven minimal core）、Decision002 选 B（插件系统 P1 再引入）、Decision003 选 A（P0 引入最小 Golden Trace/Golden Tests）。理由：event-driven 对 daemon/channels 的治理与可回放更自然，但完整插件系统是高抽象高复杂度，建议延后；Golden Trace 则是防止“交互层变复杂后回归不可见”的关键抓手。
- 我建议把 ai-tutor 的“显式状态机 + 权限边界 + 黑名单双闸门”作为 P0 UI/HITL 的设计母体；把 dev_wjh_robot 的“Single-leader + commit、tool feedback aggregation、soft-cancel safety、send_status 固定模板、Golden Trace”作为 P0 运行时约束来源；而 OpenClaw 只作为能力 checklist（channels/voice/canvas 等）。
evidence:
- THREAD-015 裁决（能力 roadmap：D/B/A）：`docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
- ai-tutor main：`/Users/wangwu/.openclaw/workspace/ai-tutor/docs/architecture.md`（显式状态机/权限边界/黑名单）
- ai-tutor main：`/Users/wangwu/.openclaw/workspace/ai-tutor/docs/ai_native_architecture.md`（Progressive Disclosure 技能管理、动态 prompt）
- ai-tutor robot：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:README.md`（Single-leader、aggregation、soft-cancel、Golden Trace、OAuth provider）
- ai-tutor robot：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:PLUGIN_ARCHITECTURE.md`（plugin/hook system 的范围与接口）
- ai-tutor robot：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:EVENT_DRIVEN_QUICKSTART.md`（event-driven runtime + trace visualizer）
- AgentOS Next 现有不变量与约束：`docs/specs/EVIDENCE_TRACE.md`、`docs/specs/EXECUTOR_API.md`
- 回归基线：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前全绿）
tradeoffs:
- 选 Hybrid event-driven minimal core（Decision001-C）：
  - 收益：对 daemon/channels/trigger/follow-up 这种“长期运行 + 事件触发”的语义更贴合；更容易把所有动作收敛为 trace/evidence 的事件流；天然支持 yield/打断。
  - 成本/风险：引入 event bus 与任务队列的复杂度；若没有 Golden Trace/严格 gate，容易出现“事件风暴/重复触发”的灰区 bug。
- 插件系统延后（Decision002-B）：
  - 收益：P0 少一层抽象，降低引入错误面；先用明确接口与模块边界交付 UI/HITL/channels/daemon。
  - 成本/风险：短期可替换性较弱；后续再抽 plugin 时可能有迁移成本。
- P0 引入最小 Golden Trace（Decision003-A）：
  - 收益：把“可回放/可审计”从原则变成可执行断言（尤其对 UI/HITL/daemon）；利于多专家协作减少口径偏差。
  - 成本/风险：需要设计最小 GT schema 与断言集；可能拉长 P0 首次交付时间，但可控。
open_questions:
- Hybrid 的最小定义边界：event-driven core 需要包含哪些事件类型，哪些仍走现有 assistant loop API？
- Golden Trace 与 AgentOS Next 的 evidence/trace 如何复用：是引用同一 trace schema，还是为 UI 额外导出视图（view）？
- 插件系统的最小落点：是否仅对 Transport（channels）做 plugin，其他仍模块化？
proposal:
- 启动 THREAD-016 并在 Round 1 让各专家分别对 3 个 decision points 给出结论 + bounded spikes + kill criteria：
  - Spike-ED1：event-driven core 最小闭环（USER_INPUT + TRIGGER + TOOL_DONE + SEND_OUTPUT）+ 单写者语义
  - Spike-GT1：最小 Golden Trace（3 条 GT，覆盖 HITL 审批、soft-cancel、follow-up）
  - Spike-PLUG0（可选）：仅 Transport plugin（CLI/WS），验证“引入一类插件”的收益
acceptance:
- 本输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_options.md`
- 本线程三件套存在：
  - `docs/journal/2026-02-24-expert-collab-thread-016.md`
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
confidence: `medium`

