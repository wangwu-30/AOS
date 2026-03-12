# DECISIONS: SI1 Self-Improvement Loop (自主迭代闭环)

- `thread_id`: `20260220-SI1-AUTOEVOLVE-014`
- `updated_at`: `2026-02-21`
- `status`: `accepted`

## Decision 001: SI1 四阶段闭环是否进入实现（Observe/Propose/Validate/Promote）

- **状态**: `accepted`
- **结论**: 选 A（Phase-1 先实现 Observe/Propose/Validate，不落 Promote 写入）
  - Phase-1（本轮）：Observe + Propose + Validate（不产生变更包、不触碰仓库关键路径）
  - Phase-2（下轮）：Promote（如启用，必须 HITL + bundle + rollback）

## Decision 002: HITL 门禁是否为 Promote 的 admission MUST

- **状态**: `accepted`
- **结论**: 选 A（MUST）：Promote 必须 `approved_by_human==true`，否则必须阻断并写 evidence

## Gate（进入 accepted 前必须通过的门禁）

1. fail-closed / replay-mode / evidence-by-default 不降级
2. 不新增 ExecuteRequest 顶层字段（扩展点仅 policy_context）
3. Promote（如实现）必须 HITL gate 阻断（admission MUST）

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 本线程三件套存在：
  - `docs/journal/2026-02-20-expert-collab-thread-014.md`
  - `docs/journal/SYNTHESIS_20260220-SI1-AUTOEVOLVE-014.md`
  - `docs/journal/DECISIONS_20260220-SI1-AUTOEVOLVE-014.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

