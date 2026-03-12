# 2026-02-28 外部专家协作线程 041 (External Expert Collaboration Thread 041)

- `thread_id`: `20260228-PA-WEBHOOK-SERVER-041`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `ext_gpt5_3`

## Goal

- PA-WEBHOOK-SERVER：提供 loopback webhook 服务形态（ingress -> EV1 -> outbox -> reply）并保持 fail-closed/replay zero-write。

## Boundary

- 不新增 ExecuteRequest 顶层字段（仅 policy_context 扩展）。
- fail-closed：校验失败与执行失败必须返回稳定 error_code（无 traceback 泄漏）。
- replay-mode：zero-write（不创建 pa 数据目录，不触发执行与出站副作用）。
- 入口 host 仅允许 loopback（127.0.0.1/localhost/::1）。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread041_pa_webhook_server.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true

## Evidence (Links)

- `docs/specs/MVP_041_PA_WEBHOOK_SERVER.md`
- `src/agentos_next/apps/pa_webhook_server.py`
- `src/agentos_next/cli.py`
- `tests/test_thread041_pa_webhook_server.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_WEBHOOK_SERVER_041_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_WEBHOOK_SERVER_041_round2_cross_review.md`
