id: `20260225-ext_gpt5_2-dm2-001`
author: `ext_gpt5_2`
topic: `DM2（Daemon）Round-1 评审：最小可运行 daemon + 严格门禁（single-writer/WAL/health）`
position:
- 同意以最小 CLI 入口落地：新增 `mvp daemon run|run-once|status`（仅新增子命令，不改既有命令输出契约），并且所有输出必须是稳定 JSON（`ok/error_code/evidence_refs` 结构对齐现有 CLI 习惯）。
- 同意 single-writer 作为 P0 不变量：必须用 leader lock + stale recovery 保证“同一 data_dir 同时仅 1 个 daemon 实例”写入（避免并发重复 fire），且 lock 机制应复用现有 proven pattern（`open("x")` + `ts` + stale 回收）。
- WAL 最小事件集“可恢复且可审计”的下限：`TICK_STARTED`、`FIRE_STARTED`、`FIRE_FINISHED`、`HEALTH_BLOCKED`（或等价字段），每个 FIRE 必须记录 `task_id/attempt/idempotency_key/trace_id/ts`，用于重启后识别“running 卡死”并恢复。
- 强制保留 `scheduler-tick` fallback（deterministic）：daemon 的 run-once/run 都应复用或共享 `tick.lock`（与现有 `mvp scheduler-tick` 互斥），确保在 daemon 异常时可通过 tick 进行可回放恢复/排障。
- replay-mode 必须强阻断（fail-closed）：daemon 在 replay-mode 下不得写入 WAL/证据/trace，不得触发任何执行（否则立刻回退）。
- 健康阈值“连续 2 次失败阻断”的前提：必须明确失败定义为“daemon 自身不可恢复的内部错误”（如 WAL 读写失败/锁异常/恢复逻辑异常），而不是单个任务执行失败；否则一个坏 Skill 会把系统整体停掉，违背可用性与治理预期。
evidence:
- `src/agentos_next/apps/scheduler_tick.py`（tick.lock + stale recovery；写入 `scheduler_fire_started`/`scheduler_fire` evidence；并通过 `policy_context["trigger"]` 注入触发信息）
- `src/agentos_next/kernel/skill_registry.py`（lock + stale lock 清理模式，可复用到 leader lock）
- `src/agentos_next/kernel/idempotency_store.py`（路径段 sanitize/hash + 原子替换写入，适合作为 fire 重试的安全底座）
- `src/agentos_next/kernel/evidence_store.py`（`open("xb")`/`open("x")` 的并发安全写入策略，可作为 WAL/evidence 的写入基线）
- `src/agentos_next/kernel/trace_logger.py`（append-only JSONL，可作为 daemon WAL 的存储形态参考）
- `src/agentos_next/cli.py`（`mvp scheduler-tick` 的稳定 JSON 输出契约与错误处理风格）
- 命令结果：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前基线 77/77 OK，用于 DM2 引入后回归对比）
tradeoffs:
- 收益：daemon 能让 Scheduler/FU 等能力从“显式 tick 驱动”升级为“持续运行”（always-on），更接近个人助理形态，同时保留 deterministic fallback 便于回放与排障。
- 成本/风险：引入常驻状态机与恢复逻辑，错误边界更复杂（重复触发/漏触发/不一致状态）；需要把 lock/WAL/health 做到可审计且 fail-closed，否则会破坏我们已建立的治理基线。
open_questions:
- WAL 作为独立文件（`data/daemon/wal.jsonl`）还是写入 trace（`tr_daemon_...`）？两者都可行，但需明确“恢复真相源（source of truth）”以避免实现分叉。
- “恢复一致性 >=99%”指标在 MVP 阶段的可操作定义：是按 fire 计数、按 side-effect 计数，还是按 ExecuteResult accepted 计数？建议在 spec 中把口径固定为“执行侧幂等（idempotency_key）保证不产生重复副作用”，并把“重复 fire 尝试”单独计入审计指标。
proposal:
- CLI（最小且 non-breaking）：
  - `mvp daemon run`：循环运行（带 sleep/backoff），每轮调用内部 tick/fire；遇到 HEALTH_BLOCKED 退出非 0。
  - `mvp daemon run-once`：执行单轮 tick/fire（用于测试与 deterministic recovery）。
  - `mvp daemon status`：输出 leader/health/last_tick_ts/blocked_reason（建议 P0 保持最小，避免引入新契约负担）。
- leader lock（single-writer）：
  - 文件：`data/daemon/leader.lock`（JSON：`pid/ts/daemon_id`），实现采用 `open("x")` + stale 回收（参考 `scheduler_tick._acquire_tick_lock` 与 `skill_registry._acquire_lock`）。
  - daemon 与手动 `scheduler-tick` 的互斥：共享 `data/scheduler/tick.lock`（避免并发 fire）。
- WAL 最小 schema（恢复 + 审计）：
  - JSONL event：`{schema_version,type,ts,daemon_id,tick_id,task_id,attempt,idempotency_key,trace_id,status?,error_code?}`。
  - 恢复策略（MVP）：若发现 task `status=="running"` 且对应 FIRE_FINISHED 缺失，则将 task 退回 `scheduled`（attempt 不变），允许下一轮 fire；依赖 `idempotency_key` 防重复副作用。
- 建议最小测试矩阵（<=5）：
  1. `test_dm2_single_writer_blocks_second_instance`：并发 run-once，第二个必须 fail-closed（稳定 error_code），且不得 fire。
  2. `test_dm2_run_once_mutual_exclusion_with_scheduler_tick`：daemon run-once 占用 tick.lock 时，`mvp scheduler-tick` 必须返回稳定错误（或反向）。
  3. `test_dm2_wal_recovery_requeues_running_task`：模拟崩溃遗留 running 任务，重启后可恢复并最终进入 done/failed（且 evidence/trace 可回放）。
  4. `test_dm2_replay_mode_has_no_writes`：replay_mode=true 时必须 zero-write + 不执行。
  5. `test_dm2_health_blocks_after_two_internal_failures`：注入 WAL 写失败/解析失败，连续 2 次后进入 HEALTH_BLOCKED 并阻断后续 fire。
- kill criteria（任一触发立即停止 DM2 并回退到 tick-only）：
  - replay-mode 下出现任何新副作用（写盘/远程/不可回放）。
  - single-writer 失效导致并发重复 fire（无互斥锁或锁可绕过）。
  - 任一错误路径产生 traceback（未转为稳定 JSON error_code + evidence）。
acceptance:
- 新增 DM2 仅以新增子命令/新增文件形式落地，不改变既有 CLI 输出字段集合（non-breaking）。
- DM2 相关测试全绿，且全量回归保持全绿：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_dm2_*.py' -v`
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 代码层面保持不变量：
  - 不新增 `ExecuteRequest` 顶层字段（policy 扩展仅 `policy_context`）。
  - fail-closed / replay-mode / double-gating / evidence-by-default 语义不降级（由回归测试与 evidence/trace 检查覆盖）。
confidence: `high`

