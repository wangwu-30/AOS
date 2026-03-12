# SYNTHESIS: DM2 Daemon（single-writer + WAL + health）

- `thread_id`: `20260225-DM2-DAEMON-019`
- `updated_at`: `2026-02-25`
- `status`: `resolved`

## 综合结论

- DM2 采用最小可运行方案：新增 `mvp daemon run|run-once|status`，不改既有 scheduler/assistant CLI 契约。
- 健康失败仅统计 daemon 内部错误；单任务业务失败不计入 health。
- 阈值按 host 裁决收敛：
  - 默认模式：连续 3 次内部错误阻断
  - strict 模式：连续 1 次内部错误阻断
- replay-mode 下 daemon 走 zero-write fail-closed（不执行、不写盘）。

## 关键分歧收敛

- ext_claude 建议 status 增加 `next_fire_at`，已采纳。
- ext_gpt5_2 建议健康计数仅统计内部错误，已采纳并写入 gate。
- host 裁决：默认阈值 3，strict 阈值 1；已冻结。

## Gate（通过条件）

1. single-writer 与 tick 互斥有效
2. WAL 恢复可复现且幂等
3. replay-mode 无副作用
4. status 最小字段集稳定

## 验收锚点

- `tests/test_spike_dm2_daemon.py`
- `docs/specs/MVP_012_SCHEDULER.md`
