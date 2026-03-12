# SYNTHESIS: AL2 Planner (deterministic + llm) with Gating

- `thread_id`: `20260219-AL2-PLANNER-005`
- `updated_at`: `2026-02-19`
- `status`: `resolved`
- `owner`: `human + codex`

## Summary（综合摘要）

本线程将 AL2（Planner 可插拔）以“最小侵入（minimal intrusion）”方式落地到现有 assistant loop：
- 默认 `planner=deterministic`，保持可回归与可解释
- 新增 `planner=llm`，但必须严格遵守 fail-closed / replay-mode / 双闸门（double-gating）
- 为隔离回归面，引入 `--planner-backend`（planner 与 skill 执行 backend 可分离），便于验证 gating 而不影响主执行链

关键收口点：
- replay-mode 下强制 deterministic（并写 evidence 说明）
- 当 `planner-backend=codex_oauth` 且 gates 未开时，planner 调用在“进入 provider/读取 token/触网”之前被稳定错误码拒绝（`E_REMOTE_CALL_NOT_ARMED`）

## Conflicts & Spikes（冲突与实验）

- 冲突：planner 的远程调用是否可能绕过既有安全闸门？
  - 结论：不允许。planner 复用 `LLM_PROVIDER` 的 safety gate（同样受 replay-mode 与 double-gating 限制）。

## Evidence（证据）

- 实现：
  - `src/agentos_next/apps/assistant_loop.py`（新增 `planner` / `planner_backend` 与 LLM planner gating）
  - `src/agentos_next/cli.py`（新增 `--planner` / `--planner-backend` 参数透传）
- 回归：
  - `tests/test_spike_al2_planner_gating.py`（未武装远程时 planner fail-closed）
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`（全量通过）
