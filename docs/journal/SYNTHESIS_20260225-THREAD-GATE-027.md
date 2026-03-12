# SYNTHESIS: Thread Gate + Evidence Gate（Admission MUST）

- `thread_id`: `20260225-THREAD-GATE-027`
- `updated_at`: `2026-02-25`
- `status`: `accepted`

## 结论（Conclusion）

v1 以“可机器执行（machine-checkable）”为目标，冻结为：

- 工具入口：`PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
- 稳定输出：单行 JSON（stable JSON schema）
- 稳定 exit code：`0=ok, 2=gate_failed, 3=tool_error`
- v1 不做 NLP/LLM 判定；cross-review 通过命名约定判定（`_round2_` / `_cross_review`）

## v1 MUST Checks（Frozen）

1. `docs/specs/EXPERT_COLLAB_PROTOCOL.md` 存在
2. thread 三件套存在（thread/synthesis/decisions）
3. thread metadata keys：`thread_id/status/updated_at/owner`
4. 被 thread 引用的 `INPUT_*.md` 满足 Message Contract 全字段 + `confidence in {low,medium,high}`
5. thread status >= round_2_completed 时，至少 1 个 input 文件名包含 `_round2_` 或 `_cross_review`
6. `DECISIONS_*.md` 若出现 `needs_decision`，必须包含 `bounded spike` + `kill criteria` + `python -m unittest` 验收命令
7. `DECISIONS_*.md` 必须包含 3 tokens：`top_level_api_stable` / `fail_closed` / `replay_mode_no_side_effects`

## Non-Negotiables（Tokens）

- top_level_api_stable
- fail_closed
- replay_mode_no_side_effects

