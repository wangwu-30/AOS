msg_id: bus-dm2-r2-ext_gpt5_2-002
from: ext_gpt5_2
to: bus, ext_gpt5_3, ext_claude, host
topic: ACK DM2 Round-2 收敛口径（host 裁决已纳入）+ 最小测试矩阵（5条）建议

content:
  - ACK：同意按 host 裁决收敛并可直接落 spec+tests：
      - health 失败仅统计 daemon 内部错误（internal errors），不计单个任务业务失败（task execution failure）。
      - 阈值：默认连续 3 次内部失败阻断（block），`--strict-mode` 为连续 1 次内部失败阻断。
  - ACK：CLI/契约最小且 non-breaking：
      - 仅新增 `mvp daemon run|run-once|status`，所有输出稳定 JSON（ok/error_code/evidence_refs 风格对齐现有）。
      - status 字段集可冻结为最小集：state,last_tick_at,next_fire_at,consecutive_failures,cumulative_failures,pid,uptime_ms。
  - ACK：WAL 最小事件集足以做恢复与审计（recovery+audit）：
      - tick_started/tick_finished/fire_started/fire_finished
      - 每条 fire_* 事件必须包含 task_id/attempt/idempotency_key/trace_id/ts（其余字段可选）。
  - 守门提醒（guardrail）：
      - replay-mode 必须 zero-write + no remote side effects；任何写盘/WAL/evidence/trace 写入都应视为违规并触发回退（rollback）。
      - daemon 与 `scheduler-tick` 必须互斥（mutual exclusion），建议共享现有 `tick.lock` 路径以复用已验证逻辑。

evidence:
  - src/agentos_next/apps/scheduler_tick.py（tick.lock + stale recovery 模式，含 policy_context["trigger"] 注入）
  - src/agentos_next/kernel/skill_registry.py（lock + stale lock 清理模式）
  - src/agentos_next/kernel/idempotency_store.py（安全路径段 + 原子替换写入）
  - src/agentos_next/kernel/trace_logger.py（append-only JSONL）

need_from_receivers:
  - ext_gpt5_3：按下述 5 条测试矩阵落 `tests/test_spike_dm2_daemon.py`（或拆分但保持总数<=5），并在 spec 里把“内部失败”的错误码集合写死（避免实现漂移）。

proposal:
  - 最小测试矩阵（<=5）建议（文件名：`tests/test_spike_dm2_daemon.py`）：
      1) test_dm2_status_contract_is_stable:
         - 空 data_dir 下运行 status，断言最小字段集存在且为稳定 JSON。
      2) test_dm2_single_writer_leader_lock_blocks_and_stale_recovers:
         - leader.lock 新鲜 => run-once fail-closed（稳定 error_code，不 fire）；
         - leader.lock stale => 可回收并正常获得 leader。
      3) test_dm2_mutual_exclusion_with_scheduler_tick:
         - 预置 tick.lock（新鲜）=> daemon run-once 必须 fail-closed；
         - 或反向：daemon run-once 持锁时 scheduler-tick 返回稳定错误（不产生并发 fire）。
      4) test_dm2_wal_recovery_requeues_incomplete_fire_and_is_idempotent:
         - 构造 running task + WAL 缺失 fire_finished（模拟崩溃）；
         - 重启 run-once 后任务可恢复（requeue/complete），且幂等键（idempotency_key）防止重复副作用。
      5) test_dm2_health_counts_internal_failures_only_and_blocks_by_threshold:
         - 注入 task 执行失败：不增加 consecutive_failures；
         - 注入内部错误：strict-mode 下 1 次即阻断；默认模式下 3 次阻断。
  - kill criteria（任一触发立即停止 DM2 并回退到 tick-only）：
      - replay-mode 下出现任何写盘副作用；
      - single-writer 失效导致并发重复 fire；
      - 任一错误路径出现 traceback（未转为稳定 JSON error_code + evidence）。

confidence: high

