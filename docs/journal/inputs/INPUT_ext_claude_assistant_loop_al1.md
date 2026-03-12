id: `20260219-ext_claude-AL1-001`
author: `ext_claude`
topic: `Spike-AL1: assistant loop（tool-calling/多步执行）限界实验建议`
position:
- 最强点：在 MVP-010（记忆/执行骨架）已通过架构防线后，下一步最关键的是验证“多步 + tool-calling”的闭环能力，否则 Follow-up/主动任务等 P0 助手能力无法落地。
- 关键风险：assistant loop 若无强制 boundedness 与 fail-closed，容易演化为不可控的无界循环，且会绕过既有远程安全闸门与审计链路。
evidence:
- `docs/journal/inputs/INPUT_ext_claude_bus_mvp010_007.md`: 明确提出 “建议下一步：接入 assistant loop 的 bounded spike”。
- `docs/journal/2026-02-19-expert-collab-thread-003.md`: Follow-up/主动循环被定义为 P0 能力，需要多步机制支撑。
tradeoffs:
- 若先做 deterministic loop 骨架：收益是可验证、回归面小；代价是暂时不具备真实 LLM 的灵活规划能力。
- 若直接接入真实 LLM provider：收益是端到端更真实；代价是不可控变量过多，难以归因与设定 kill criteria。
open_questions:
- assistant loop 的最小可审计输出形态：是否需要独立的 `assistant_run_result.json`，或先复用现有 ExecuteResult/evidence？
- replay-mode 下是否允许“仅 LLM 规划、不执行工具”的 dry-run？（建议默认禁止远程与工具执行）
proposal:
- 启动 Spike-AL1：优先验证 boundedness + tool-calling 控制流 + trace/evidence 证据链闭环。
- 实现策略建议：用 deterministic planner/stub 驱动 N 步 tool_call，确保行为可测试、可复核，再逐步替换为真实 planner。
acceptance:
- Gate-1/2/3/4/5 以 `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md` 为准。
- Spike-AL1 实现 PR 合并后：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 必须全绿。
confidence: `high`

