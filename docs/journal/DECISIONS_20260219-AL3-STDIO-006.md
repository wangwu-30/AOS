# DECISIONS: AL3 Assistant Loop Stdio Session

- `thread_id`: `20260219-AL3-STDIO-006`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: 新增 assistant-loop-stdio 命令

- **状态**: `accepted`
- **结论**: 采用“新增命令”而非改动 `mvp channel-stdio` 的方式接入 assistant loop，避免破坏既有输出契约。

## Gate（必须通过的门禁）

1. 不得破坏 `mvp channel-stdio` 输出契约与既有测试。
2. session correlation 必须可回放（trace_id 复用，turn/span 派生稳定）。
3. replay-mode 与双闸门不降级。

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_al3_assistant_loop_stdio.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Evidence（证据）

- `src/agentos_next/cli.py`
- `tests/test_spike_al3_assistant_loop_stdio.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

