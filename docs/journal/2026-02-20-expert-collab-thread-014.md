# 2026-02-20 外部专家协作线程 014 (External Expert Collaboration Thread 014)

- `thread_id`: `20260220-SI1-AUTOEVOLVE-014`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-21`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

立项 SI1（自主迭代闭环，Self-Improvement Loop）：在不破坏既有安全与可回放契约（fail-closed / replay-mode / evidence-by-default / ExecuteRequest 顶层稳定）的前提下，引入一个受限闭环：

- Observe（观测）: 从本地 evidence/trace/registry 提取可改进信号（signals）
- Propose（提案）: 输出结构化 proposal（含证据、影响、回滚）
- Validate（验证）: 以 replay-mode + 本地回归为硬门禁验证提案
- Promote（推广）: HITL（人工批准）后才允许产出可应用的变更包（change bundle）

目标：把“持续改进”从临时人工操作升级为可审计、可回放、可终止（killable）的治理管线（governed pipeline）。

## 范围 (In Scope)

- 规范化 SI1 四阶段语义与最小接口（spec-first）
- 明确错误码（error codes）、回滚（rollback）、kill criteria
- 明确与现有 fail-closed / replay / evidence/trace 契约的对齐清单

## 非范围 (Out of Scope)

- 自动合并/自动发布（auto-merge / auto-release）
- 远程验证流水线（RemoteSandbox CI）与跨设备同步
- 任何需要新增 ExecuteRequest 顶层字段的扩展（除非未来出现内核级治理硬需求并经 bounded spike 裁决）

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级（任何不确定/缺证据/越权 MUST 拒绝并写 evidence）
- replay-mode 下无新副作用（no new side effects），不得触发远程执行
- ExecuteRequest 顶层字段稳定；扩展点仅使用 policy_context
- Promote 必须 HITL 批准（approved_by_human）

## 轮次进度 (Rounds)

- Round 0 (线程设定): 进行中
- Round 1 (独立提案): 待开始（inputs）
- Round 2 (交叉评审): 待开始
- Round 3 (综合): 待开始（synthesis）
- Round 4 (裁决): 待开始（decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `docs/specs/RELEASE_CRITERIA.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/specs/ADMISSION_TESTS.md`
- `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`（SI1 规范）
- `src/agentos_next/apps/si1.py`（Phase-1 实现：observe/propose/validate）
- `src/agentos_next/cli.py`（新增 mvp 子命令：si1-observe/si1-propose/si1-validate）
- `tests/test_spike_si1_phase1_autoevolve.py`（Phase-1 回归）
- `docs/journal/SYNTHESIS_20260220-SI1-AUTOEVOLVE-014.md`
- `docs/journal/DECISIONS_20260220-SI1-AUTOEVOLVE-014.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260220_SI1_AUTOEVOLVE_014_round2_cross_review.md`

