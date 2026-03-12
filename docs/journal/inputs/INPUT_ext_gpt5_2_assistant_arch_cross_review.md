id: `20260224-ext_gpt5_2-assistant-arch-002`
author: `ext_gpt5_2`
topic: `THREAD-016 Round 2：交叉评审（cross-review）+ Remote/API 约束补强（ext_gemini_flash 离线替代）`
position:
- 对 ext_claude 的评审：
  - 最强点：把“用户信任闭环（trust loop）”当作 P0 的第一性原则，并明确要求 Hybrid 必须保留 direct loop fallback；这能避免 event-driven 早期不稳定导致无法回放/排障的风险（见 `docs/journal/inputs/INPUT_ext_claude_assistant_arch.md`）。
  - 关键风险：Hybrid + fallback 容易产生“双实现漂移（dual-path drift）”。如果没有明确的“等价语义（semantic equivalence）”断言与 Golden Trace，fallback 可能只在 happy path 等价，失败/边界行为会分叉。
- 对 ext_gpt5_3 的评审：
  - 最强点：给出最小 Hybrid 边界（事件类型集 + single-writer），并把 kill criteria 明确绑定到“顶层字段变更 / replay 副作用 / 重复执行不可幂等吸收”（见 `docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_options.md`）。这是把复杂度锁死在可控范围内的关键。
  - 关键风险：其“5 类事件类型”是 runtime 事件，不是 `TraceEventType`；如果实现时误把 runtime 事件强行映射为新的 `TraceEventType`，会破坏现有类型系统稳定性（见 `src/agentos_next/kernel/types.py`）。建议：runtime 事件内部自定义，落 trace 时只用既有 `TraceEventType`，把 runtime event_name 放进 `TraceEvent.data`。
- 综合结论（建议给 host 的裁决口径）：
  - 我认为当前证据足以推荐直接裁决 `C/B/A`（Hybrid minimal core / plugin P1 / Golden Trace P0）。
  - 但在裁决前应补强 2 个“防漂移 gate”：
    1) 明确 Hybrid 的“单写者（single-writer）”范围：哪些模块允许写持久状态（data/）、哪些只能发事件；否则 daemon+channels 可能引入并发写竞态。
    2) Golden Trace 必须覆盖“失败路径一致性”：同一输入在 Hybrid 与 direct fallback 下，失败时 error_code/evidence_refs/trace 结构必须等价（而不只是成功路径等价）。
evidence:
- `docs/journal/inputs/INPUT_ext_claude_assistant_arch.md`
- `docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_options.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_options.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_remote_api.md`
- `docs/specs/REMOTE_SANDBOX_API.md`（policy_context 前向扩展与透传约束）
- `src/agentos_next/runtime/remote_executor.py`（unknown policy_context keys preserve）
- `src/agentos_next/kernel/types.py`（TraceEventType 枚举稳定性）
- 命令：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前 73/73 全绿基线）
tradeoffs:
- 直接裁决 C/B/A 的收益：尽快把讨论收敛成可执行的 bounded spikes（runtime/GT），避免“讨论拖延导致实现口径分叉”。
- 直接裁决 C/B/A 的成本/风险：host 若更偏速度，可能担心 Golden Trace 增加首轮交付时间；需要用最小 GT（3 条）控制成本，并把 GT 当作“交互层防回归门禁”而非“额外工程”。
open_questions:
- Hybrid 的 direct loop fallback 是否要求“每个事件流都可回放为 direct 流”？还是只要求关键闭环（HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP）可互相回放？
- Golden Trace 的稳定键集合（stable keys）是否由 `EVIDENCE_TRACE.md` 锁定，还是额外定义 UI view（建议优先锁定现有 trace/evidence schema，UI view 作为派生）。
proposal:
- Round 2 行动：
  - host 提交 THREAD-016 Round 1 input（北极星指标 + 裁决倾向），然后进入 Round 3 综合与 Round 4 裁决。
  - 由我（gpt5.2）在 Round 3 提供评分矩阵与“单一硬回退阈值（one hard rollback trigger）”草案，供你最终裁决。
- 对实现侧的 bounded spikes（若进入裁决后执行）：
  - Spike-RT1：Hybrid minimal core（event bus + single-leader/single-writer）+ direct loop fallback
  - Spike-GT1：最小 Golden Trace（HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP_SUCCESS）+ 失败路径等价断言
acceptance:
- 本交叉评审输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_cross_review.md`
- THREAD-016 Round 2 completion（最低条件）：
  - ext_gpt5_2/ext_claude/ext_gpt5_3 各自至少 1 次交叉评审落盘（最强点 + 关键风险）
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md` 更新为 `round_3_completed` 且包含评分矩阵摘要
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md` 更新为 `needs_decision` 或 `accepted`（由人类裁决）
  - 全量回归保持全绿：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
confidence: `medium`

