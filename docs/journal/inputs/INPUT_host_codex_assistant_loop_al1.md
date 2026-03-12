id: `20260219-host_codex-AL1-001`
author: `host_codex`
topic: `Spike-AL1: assistant loop（tool-calling/多步执行）验收口径与门禁`
position:
- assistant loop 必须建立在现有 `Orchestrator.execute(ExecuteRequest)` 之上，工具执行不得旁路；以保持证据链、幂等/超时语义与 fail-closed 一致。
- 先用 deterministic planner/stub 验证控制流与门禁，再逐步替换为真实 LLM planner（避免不可控变量导致难以回归）。
evidence:
- `docs/specs/EXECUTOR_API.md`: ExecuteRequest/ExecuteResult 幂等/超时语义与稳定错误码要求。
- `docs/specs/EVIDENCE_TRACE.md`: evidence/trace 作为可回放真相源（source of truth）。
- `docs/specs/LLM_PROVIDER.md`: replay-mode 与远程调用双闸门（double gating）。
tradeoffs:
- 先落 CLI + library 形态：收益是可测试、回归面小；成本是暂时缺少长期对话 UI 与复杂多轮策略。
- 若将 loop 下沉到 Orchestrator：收益是入口统一；风险是职责膨胀且容易引入不可控回归。
open_questions: []
proposal:
- 落地 Spike-AL1：新增 `mvp assistant-loop`（单轮）+ 最小测试；确保 boundedness/fail-closed/replay-mode 闸门不降级。
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_al1_assistant_loop.py' -v` 通过，并确认包含至少一次 builtin memory.* 执行。
confidence: `high`

