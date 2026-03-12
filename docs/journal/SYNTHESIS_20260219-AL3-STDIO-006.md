# SYNTHESIS: AL3 Assistant Loop Stdio Session

- `thread_id`: `20260219-AL3-STDIO-006`
- `updated_at`: `2026-02-19`
- `status`: `resolved`
- `owner`: `human + codex`

## Summary（综合摘要）

本线程将 assistant loop 接入 stdio session，并以新命令避免破坏 `mvp channel-stdio` 契约：
- 新增 `mvp assistant-loop-stdio`：stdin 每行触发一次 assistant loop
- session 复用 `trace_id`，并为每行派生可回放的 `turn_id/span_id`
- 每行输出 1 条稳定 JSON（JSONL），并 `flush=True` 便于管道消费

安全边界保持不变：
- replay-mode 仍禁远程；双闸门不降级
- 工具执行仍走 `run_assistant_loop_async -> Orchestrator.execute -> LocalExecutor` 链路

## Evidence（证据）

- `src/agentos_next/cli.py`（`assistant-loop-stdio`）
- `tests/test_spike_al3_assistant_loop_stdio.py`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
