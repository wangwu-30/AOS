# DECISIONS: Thread Gate + Evidence Gate（Admission MUST）

- `thread_id`: `20260225-THREAD-GATE-027`
- `updated_at`: `2026-02-25`
- `status`: `accepted`

## Decision 001: v1 是否仅做 machine-checkable（不做 NLP/LLM 语义判定）

- **状态**: `accepted`
- **结论**: v1 仅做 machine-checkable 规则；不做 NLP/LLM 判定，避免 flake 与误伤。

## Decision 002: Round2 cross-review 命名约定是否升为 MUST

- **状态**: `accepted`
- **结论**: MUST
  - 任一 status >= `round_2_completed` 的 thread，必须至少引用 1 个文件名包含 `_round2_` 或 `_cross_review` 的 input。

## Decision 003: Evidence Gate v1 强度（needs_decision 触发）

- **状态**: `accepted`
- **结论**: v1 采用字面匹配（literal match）
  - `needs_decision` 存在 -> DECISIONS 必须包含：
    - `bounded spike`
    - `kill criteria`
    - 至少 1 条可执行 acceptance 命令（`python -m unittest`）

## Decision 004: v1 固定 tokens（Non-negotiables）

- **状态**: `accepted`
- **结论**: v1 固定 3 tokens（字面匹配，避免文案漂移误伤）
  - `top_level_api_stable`
  - `fail_closed`
  - `replay_mode_no_side_effects`

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

