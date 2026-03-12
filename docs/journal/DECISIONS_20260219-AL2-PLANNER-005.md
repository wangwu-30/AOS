# DECISIONS: AL2 Planner (deterministic + llm) with Gating

- `thread_id`: `20260219-AL2-PLANNER-005`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: Planner 插拔与门禁

- **状态**: `accepted`
- **结论**:
  - `planner=deterministic` 为默认（baseline），保证可回归
  - `planner=llm` 允许，但必须复用 `LLM_PROVIDER` 的安全闸门语义
  - planner backend 可通过 `--planner-backend` 与 skill backend 分离（便于隔离测试与回归）

## Gate（必须通过的门禁）

1. replay-mode 下 MUST 禁远程：`planner=llm` 时强制 deterministic，并写 evidence 说明。
2. 远程 LLM 调用 MUST 双闸门（double-gating）：`remote_calls_armed` + `allow_network_egress`。
3. 未满足闸门时必须 fail-closed，返回稳定错误码（至少 `E_REMOTE_CALL_NOT_ARMED` / `E_NETWORK_EGRESS_DENY` / `E_REPLAY_REMOTE_DISABLED`）。
4. 不得破坏既有 CLI/evidence/trace 契约；新增参数仅影响新命令或新路径。

## Acceptance（可验证验收）

- 全量回归：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- AL2 gating：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_al2_planner_gating.py' -v`

## Evidence（证据）

- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_al2_planner_gating.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

