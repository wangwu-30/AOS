# 2026-02-25 外部专家协作线程 019 (External Expert Collaboration Thread 019)

- `thread_id`: `20260225-DM2-DAEMON-019`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-25`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

基于 THREAD-015 的 Decision002（daemon 进 P0 + runner/tick fallback）与 THREAD-016 的架构门禁，落地 DM2：在不破坏现有契约的前提下提供最小常驻 daemon 运行形态。

## 范围 (In Scope)

- `mvp daemon run|run-once|status`
- single-writer（leader lock）+ tick lock 互斥
- WAL 最小事件与恢复
- health/heartbeat 与阻断阈值
- 保留 `scheduler-tick` fallback

## 非范围 (Out of Scope)

- 多实例 leader election
- plugin/hook 系统
- 新通道接入
- ExecuteRequest 顶层字段扩展

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级
- replay-mode 无新副作用（zero-write + no execution）
- policy_context only（top-level API stable）
- evidence/trace 可回放

## 轮次进度 (Rounds)

- Round 0: 已完成（立项与边界）
- Round 1: 已完成（ext_claude/ext_gpt5_2 并行输入）
- Round 2: 已完成（host 裁决收敛）
- Round 3: 已完成（实现与测试）
- Round 4: 已完成（accepted）

## Evidence (Links)

- `docs/specs/MVP_012_SCHEDULER.md`
- `src/agentos_next/apps/daemon_runner.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_dm2_daemon.py`
- `docs/journal/inputs/INPUT_ext_claude_dm2_round1.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_dm2_daemon_round1.md`
- `docs/journal/inputs/INPUT_ext_gpt5_3_dm2_round2_converged.md`
- `docs/journal/SYNTHESIS_20260225-DM2-DAEMON-019.md`
- `docs/journal/DECISIONS_20260225-DM2-DAEMON-019.md`
