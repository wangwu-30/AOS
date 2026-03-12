id: `20260224-ext_gpt5_3-assistant-arch-002`
author: `ext_gpt5_3`
topic: `THREAD-016 Round 2 交叉评审：Hybrid/fallback 防漂移与 Golden Trace kill criteria 可执行性`
position:
- strongest point（ext_claude）：把“用户信任闭环（UI/HITL/可视化 trace）”作为 P0 第一目标，并明确要求 Hybrid 必须保留 direct fallback，这是防止 event-driven 早期不稳定导致不可回放的关键。
- strongest point（gpt5.2）：Remote/API 守门口径清晰且与不变量一致（扩展仅 `policy_context`，不动 `ExecuteRequest` 顶层），可避免应用层演进把内核契约拖偏。
- key risk（Hybrid/fallback 漂移）：若两条路径在 `idempotency_key` 派生、policy gate 顺序、error 映射上没有“逐场景等价断言”，会出现成功路径一致但失败路径分叉。
- key risk（GT kill criteria 不可执行）：当前 kill criteria 偏描述性，缺少可量化阈值（flake、字段漂移、回放一致性），容易出现“看起来都通过，实际上持续抖动”。
- 结论：维持 `C/B/A`，但必须把“语义等价 gate + 可量化 GT gate”升为 Round 3/4 的硬前置。
evidence:
- `docs/journal/inputs/INPUT_ext_claude_assistant_arch.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_cross_review.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_remote_api.md`
- `docs/journal/inputs/INPUT_host_assistant_arch.md`
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/specs/EXECUTOR_API.md`
- `docs/specs/REMOTE_SANDBOX_API.md`
tradeoffs:
- 立即裁决 C/B/A：
  - 收益：讨论快速收口，进入实现迭代。
  - 风险：若缺语义等价与 GT 量化门禁，会把漂移风险后移到实现期。
- 先补两道硬 gate 再裁决：
  - 收益：把主要风险前移并可测，降低后续返工。
  - 风险：Round 3 需要补充少量测试设计工作。
open_questions:
- fallback 等价是否要求“字段全集等价”还是“稳定键等价”（建议稳定键等价：`status/error_code/evidence_refs(traceable)` + trace 结构一致）？
- GT 稳定性阈值是否采用“连续 N 次全绿 + flake<=X%”作为进入 accepted 的门槛？
proposal:
- Spike-HY2（bounded）：Hybrid/direct fallback 语义等价 harness
  - 场景最小集：`HITL_BLOCK`、`REPLAY_BLOCK`、`SCHED_FOLLOWUP_SUCCESS`、`TOOL_FAIL`
  - 断言：两路径在稳定字段（`status`、`error_code`、关键 `evidence_refs` 可追溯）与 trace 结构等价
  - kill criteria：
    - 任一场景两路径输出语义不一致；
    - 需要新增 `ExecuteRequest` 顶层字段才能完成等价；
    - replay-mode 出现副作用
- Spike-GT2（bounded）：Golden Trace 量化门禁
  - 建议阈值：连续 10 次回放全绿；GT flake rate <= 1%；稳定键新增可放宽、删除/改义即失败
  - kill criteria：
    - flake rate > 1% 持续 2 天；
    - 为通过 GT 必须放宽 fail-closed 或减少 evidence 字段；
    - 任一 GT 场景无法本地 deterministic 回放
acceptance:
- 本输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_cross_review.md`
- Round 2 completion 最低条件（我方）：
  - strongest point >= 1，key risk >= 1，均已绑定 bounded spike + kill criteria
  - `THREAD-016` 的 SYNTHESIS 可推进到 Round 3 对比矩阵
- 回归基线不回退：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 继续全绿
confidence: `high`
