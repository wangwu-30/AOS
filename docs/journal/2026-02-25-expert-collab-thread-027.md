# 2026-02-25 外部专家协作线程 027（External Expert Collaboration Thread 027）

- `thread_id`: `20260225-THREAD-GATE-027`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-25`
- `owner`: `human + codex`

## 问题陈述（Problem Statement）

将“Thread Gate + Evidence Gate”从约定升级为自动化准入门禁（admission MUST），把外部专家协作协议的关键要求固化为可机器执行（machine-checkable）的检查工具与 admission tests。

## 范围（In Scope）

- Gate 工具：`PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
- 稳定输出：单行 JSON（stable JSON schema）+ 稳定 exit code（0/2/3）
- MUST checks（v1）：
  - 协议文档存在
  - thread 三件套存在（thread/synthesis/decisions）
  - Message Contract 字段完整性（被 thread 引用的 INPUT_*.md）
  - Round2 cross-review 命名约定（`_round2_` / `_cross_review`）
  - needs_decision -> Evidence Gate（bounded spike + kill criteria + 可执行 acceptance 命令）
  - Non-negotiables tokens（`top_level_api_stable` / `fail_closed` / `replay_mode_no_side_effects`）

## 非范围（Out of Scope）

- NLP/LLM 语义判定（v1 不做）
- 评分矩阵自动打分（v1 不强制）

## 非协商约束（Non-Negotiables）

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## 轮次进度（Rounds）

- Round 0: 已完成（立项与边界）
- Round 1: 已完成（独立提案）
- Round 2: 已完成（交叉评审）
- Round 3: 已完成（综合收敛）
- Round 4: 已完成（裁决 accepted）

## Evidence（Links）

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `src/agentos_next/tools/thread_gate_check.py`
- `tests/test_admission_thread_gate_check.py`
- `docs/journal/inputs/INPUT_ext_claude_thread027_r2.md`
- `docs/journal/inputs/INPUT_thread_20260225_THREAD_GATE_027_round2_cross_review.md`
- `docs/journal/SYNTHESIS_20260225-THREAD-GATE-027.md`
- `docs/journal/DECISIONS_20260225-THREAD-GATE-027.md`

