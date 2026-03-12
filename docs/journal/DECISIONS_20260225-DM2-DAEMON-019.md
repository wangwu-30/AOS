# DECISIONS: DM2 Daemon（P0）

- `thread_id`: `20260225-DM2-DAEMON-019`
- `updated_at`: `2026-02-25`
- `status`: `accepted`

## Decision 001: DM2 是否进入实现

- **状态**: `accepted`
- **结论**: 接受（A）
  - 交付最小 daemon：`run|run-once|status`
  - 保留 `scheduler-tick` fallback

## Decision 002: 健康失败计数口径

- **状态**: `accepted`
- **结论**: 接受（A）
  - 仅统计 daemon 内部错误
  - 不统计单个任务业务失败

## Decision 003: 阈值策略

- **状态**: `accepted`
- **结论**: 接受（A）
  - 默认：连续 3 次内部错误阻断
  - `--strict-mode`：连续 1 次内部错误阻断

## Gate

1. replay-mode 必须 zero-write + 不执行（`E_DAEMON_POLICY_VIOLATION`）
2. single-writer 失效即阻断（`E_DAEMON_LOCKED`）
3. 互斥、恢复、幂等路径必须有回归测试
4. ExecuteRequest 顶层字段保持稳定（policy_context only）

## Acceptance

- `tests/test_spike_dm2_daemon.py` 通过
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 线程三件套存在：
  - `docs/journal/2026-02-25-expert-collab-thread-019.md`
  - `docs/journal/SYNTHESIS_20260225-DM2-DAEMON-019.md`
  - `docs/journal/DECISIONS_20260225-DM2-DAEMON-019.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

