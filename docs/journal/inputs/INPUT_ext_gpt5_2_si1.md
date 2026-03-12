id: `20260220-ext_gpt5_2-si1-001`
author: `ext_gpt5_2`
topic: `SI1 自主迭代闭环（Self-Improvement Loop）: 受限管线 + HITL + fail-closed`
position:
- SI1 的正确形态是“治理管线（governed pipeline）”而不是“自动改代码并上线”：MVP 阶段先把 Observe/Propose/Validate 的证据闭环做扎实，再讨论 Promote 的自动化程度。
- Promote 必须 HITL（Human-in-the-Loop）门禁：`approved_by_human==true` 是 admission MUST，否则禁止任何写入/发布动作。
- 不新增 ExecuteRequest 顶层字段（top-level API stable）；SI1 相关上下文一律通过 `policy_context` 扩展点前向兼容透传。
evidence:
- `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`
- `docs/specs/RELEASE_CRITERIA.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `tests/test_admission_expert_collab_protocol.py`（线程三件套要求）
tradeoffs:
- 收益：把“持续改进”变为可审计、可终止、可回放流程，减少口头约定与不可复现的人工操作。
- 成本/风险：若过早引入自动 Promote 会放大安全风险与不可控变更；因此必须用 HITL + replay-mode + admission tests 做硬门禁。
open_questions:
- []
proposal:
- 作为 bounded spike（限界实验，bounded spike），优先实现 Observe + Validate 的 CLI/库 API 骨架（不落 Promote 写入），并用 1 条端到端用例验证：
  - 输出 `signals.json/proposal.json/validation.json`
  - Validate 必跑全量单测且失败时 fail-closed
- Promote 在下一轮 thread 再裁决（若引入，必须 HITL gate + 变更包落盘 + 回滚说明）。
acceptance:
- `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md` 存在且包含：Non-Negotiables / Stage Semantics / Error Codes / Rollback / Kill Criteria。
- 本线程三件套存在（thread/synthesis/decisions）。
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿（新增文档不应破坏 admission）。
confidence: `medium`

