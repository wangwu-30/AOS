id: `20260224-ext_gpt5_3-017-018`
author: `ext_gpt5_3`
topic: `THREAD-017/018 交付：HY2 等价门禁 + GT2 量化门禁`
position:
- 已交付最小 Hybrid runtime 包装层（event-dispatch shell + direct fallback），并通过 4 场景等价测试（HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP_SUCCESS / TOOL_FAIL）。
- 已交付 GT2 量化门禁实现（flake<=1%、连续10次通过、连续2次失败触发回退）与结构化 gate report。
- 未新增 ExecuteRequest 顶层字段；扩展与策略语义保持 policy_context 路径，fail-closed/replay-mode/double-gating 不降级。
evidence:
- `src/agentos_next/apps/assistant_runtime.py`
- `src/agentos_next/apps/golden_trace_gate.py`
- `src/agentos_next/cli.py`
- `tests/hybrid_gate_helpers.py`
- `tests/test_spike_hy2_hybrid_equivalence.py`
- `tests/test_spike_gt2_golden_trace_gate.py`
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`
- `docs/journal/2026-02-24-expert-collab-thread-017.md`
- `docs/journal/SYNTHESIS_20260224-HY2-HYBRID-EQUIVALENCE-017.md`
- `docs/journal/DECISIONS_20260224-HY2-HYBRID-EQUIVALENCE-017.md`
- `docs/journal/2026-02-24-expert-collab-thread-018.md`
- `docs/journal/SYNTHESIS_20260224-GT2-GOLDEN-TRACE-GATE-018.md`
- `docs/journal/DECISIONS_20260224-GT2-GOLDEN-TRACE-GATE-018.md`
tradeoffs:
- 收益：把 THREAD-016 的 accepted 条件从“口头约束”升级为可执行 gate（代码+测试）。
- 成本：增加了少量 runtime 包装与 golden gate 维护成本。
- 风险控制：通过 deterministic local-only 约束与 fail-closed 回退触发，降低抖动与误判。
open_questions:
- GT2 阈值是否在后续引入 daemon/channels 后需要分场景调整（例如按通道分别统计）？
- 是否需要在 release-pack 中追加 GT2 report 摘要作为 RC 审计材料？
proposal:
- 维持当前 HY2/GT2 作为 P0 门禁；后续若引入更复杂 event-driven runtime，必须先扩展 HY2 场景矩阵再改默认行为。
- 建议下一轮把 GT2 gate 报告接入 release-pack（additive，不破坏现有 manifest 字段契约）。
acceptance:
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_hy2_hybrid_equivalence.py' -v` 通过。
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_gt2_golden_trace_gate.py' -v` 通过。
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`
