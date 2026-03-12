# 2026-02-28 外部专家协作线程 042 (External Expert Collaboration Thread 042)

- `thread_id`: `20260228-PA-TG1-042`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-28`
- `owner`: `ext_gpt5_2`

## Goal

- PA-TG1 最小闭环：提供可恢复的任务图（TaskGraph）机制，为“动态任务拆分/恢复”提供基础原语。

## Boundary

- 不新增 ExecuteRequest 顶层字段（仅 policy_context 扩展）。
- fail-closed：循环检测/非法 schema/IO 异常必须返回稳定 error_code（无 traceback 泄漏）。
- replay-mode：zero-write（不创建目录/文件，不触发执行）。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread042_pa_task_graph.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true

## Evidence (Links)

- `docs/specs/MVP_042_PA_TASK_GRAPH.md`
- `src/agentos_next/pa/task_graph.py`
- `src/agentos_next/pa/ev1_runtime.py`
- `tests/test_thread042_pa_task_graph.py`
- `docs/journal/inputs/INPUT_thread_20260228_PA_TG1_042_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260228_PA_TG1_042_round2_cross_review.md`
