id: `20260224-ext_gpt5_2-ai-tutor-ref-001`
author: `ext_gpt5_2`
topic: `ai-tutor（main / dev_wjh_robot）可借鉴架构：作为 AgentOS Next 的上层 App/Skills 参考，而非 Kernel 约束`
position:
- 我不同意“必须照着 OpenClaw 的架构来”。对标 OpenClaw 的正确用法是把它当作**产品能力标杆（capability benchmark）**，用于定义 P0/P1 能力差距与用户可感知的闭环；实现方式必须服从 AgentOS Next 的不变量（fail-closed / replay-mode 无副作用 / evidence-by-default / ExecuteRequest 顶层字段稳定）。
- ai-tutor（main）提供了一套“AI-Native 应用（agent app）”的实用分层：动态 Prompt 生成器（prompt generator）+ Skill 管理（Progressive Disclosure）+ 记忆（memory）+ 调度（scheduler）+ 黑名单双闸门（blacklist double gating）+ 人工介入（HITL escalation）。这套分层更适合作为我们 D/B/A 里“UI-first + Channels-embedded”的上层实现参考。
- ai-tutor（dev_wjh_robot）把上述能力进一步工程化为：事件驱动运行时（event-driven runtime）+ 插件架构（plugin architecture）+ WebSocket 传输（transport）+ trace 可视化（trace visualizer）+ Golden Trace 回归测试（golden tests）。它对我们 P0 的 daemon（Decision002-B）与通道嵌入（Decision001-D）尤其有启发，但不建议把“插件系统”直接下沉进 AgentOS Kernel；应先以 bounded spike 形式在上层 App 试验其收益/复杂度比。
evidence:
- `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/architecture.md`（显式状态机 + 权限边界 + 黑名单双闸门）
- `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/ai_native_architecture.md`（动态 Prompt + Progressive Disclosure 技能管理）
- `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/memory_scheduler_model.md`（semantic/episodic + scheduler + blacklist）
- dev_wjh_robot diff 统计：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor diff --stat main..dev_wjh_robot`
- dev_wjh_robot 新增文档：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:PLUGIN_ARCHITECTURE.md`
- dev_wjh_robot 新增文档：`git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:EVENT_DRIVEN_QUICKSTART.md`
- THREAD-015 裁决：`docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`（D/B/A）
tradeoffs:
- 收益：
  - 直接复用“产品级闭环”经验：状态机约束、HITL、黑名单、调度与记忆的组合套路，能更快把 UI-first 变成可用的用户体验。
  - dev_wjh_robot 的 Golden Trace / trace 可视化提供了“可回放（replayable）”的工程抓手，和 AgentOS Next 的 evidence/trace 目标一致。
- 成本/风险：
  - 插件系统与事件驱动框架容易过早“平台化”，引入大量抽象层；若不以 bounded spike 控制范围，会拖慢 P0 交付。
  - ai-tutor 是垂直场景（家教）应用，其 Skill/Memory 的字段与分类不能直接当成 AgentOS 的通用标准，需要抽象到我们现有的 Skills contract 与 Memory API 之上。
open_questions:
- UI/HITL 的 P0 入口：先做 TUI 还是 Web UI？（对标 dev_wjh_robot 的 WebSocket + Web UI，可能更贴近 Channels-embedded，但工程量更大）
- “事件驱动 runtime”是否以 daemon 的内部实现细节存在即可，还是需要显式暴露为平台扩展点（plugin/hook）？建议先 P0 bounded spike 验证其必要性。
proposal:
- 将 ai-tutor 的可借鉴点作为 THREAD-015 的补充参考，不改变已裁决的 D/B/A，但用于细化 P0 spikes 的 acceptance：
  - UI1：HITL 审批流 + trace 可视化（参考 ai-tutor 的 state machine + trace visualizer 思路）。
  - CH1：local gateway channel（参考 WebSocketTransport：msg -> event -> loop -> send）。
  - DM2：daemon 恢复/健康检查（参考 event-driven runtime 的事件总线与任务队列，但保持 deterministic fallback）。
acceptance:
- 本输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_2_ai_tutor_reference.md`
- THREAD-015 的 SYNTHESIS/DECISIONS 引用本输入，且 thread 状态保持已裁决（不回滚到 needs_decision）。
confidence: `medium`

