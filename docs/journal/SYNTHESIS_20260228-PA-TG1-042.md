# SYNTHESIS: THREAD-042 PA-TG1 TaskGraph

- `thread_id`: `20260228-PA-TG1-042`
- `updated_at`: `2026-02-28`
- `status`: `resolved`

## Summary

THREAD-042 引入 file-backed TaskGraph 原语（应用层），提供：

- queued/running/succeeded/failed 状态机
- running->queued 的恢复助手（crash recovery）
- 指纹循环检测（重复触发 fail-closed，`E_CYCLE_DETECTED`）
- replay-mode 写入拒绝（zero-write）

并以最小方式接入 EV1：每个 event_id 写入一个 root task 以便后续演进（任务拆分/恢复）。
