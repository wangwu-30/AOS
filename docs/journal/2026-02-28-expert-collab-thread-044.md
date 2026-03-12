# 2026-02-28 外部专家协作线程 044 (External Expert Collaboration Thread 044)

- `thread_id`: `20260228-PA-POLLING-044`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `ext_gpt5_3`

## Goal

- 在无公网 webhook 条件下，提供 Telegram 本地轮询入口（`getUpdates`）并接入既有 PA 执行链路。

## Boundary

- 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）。
- fail-closed：轮询/解析/执行失败必须稳定 error_code。
- replay-mode：zero-write + no-network-side-effects。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread044_pa_polling.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true

## Evidence (Links)

- `docs/specs/MVP_044_PA_POLLING_MODE.md`
- `src/agentos_next/apps/pa_polling_service.py`
- `src/agentos_next/cli.py`
- `tests/test_thread044_pa_polling.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_POLLING_044_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_POLLING_044_round2_cross_review.md`
