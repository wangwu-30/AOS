# SYNTHESIS: FU1 Follow-up Plan (Plan-Only)

- `thread_id`: `20260219-FU1-FOLLOWUP-007`
- `updated_at`: `2026-02-19`
- `status`: `resolved`
- `owner`: `human + codex`

## Summary（综合摘要）

本线程将 follow-up（主动跟进）以“plan-only + deterministic + bounded”方式落到 assistant loop：
- 每次 assistant loop 结束都会生成 follow-up plan evidence（`kind=artifact_draft`）
- follow-up plan 不包含时间戳（no ts），确保跨 data_dir 可复现（evidence ref 内容寻址稳定）
- 条目数 bounded（<= 5）
- assistant-loop / assistant-loop-stdio 输出都携带 `followup_plan_ref`，便于上层消费（未来接入 scheduler 时仍以该 plan 为真相源输入）

## Evidence（证据）

- `src/agentos_next/apps/assistant_loop.py`（`_build_followup_plan` + evidence 落盘）
- `tests/test_spike_fu1_followup_plan_deterministic.py`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
