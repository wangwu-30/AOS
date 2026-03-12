# 2026-02-19 外部专家协作线程 009 (External Expert Collaboration Thread 009)

- `thread_id`: `20260219-REG1-009`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

实现最小 Skill Registry（技能注册表，Skill Registry）机制，以支持内容寻址（content-addressed）形式的 `skill_ref`：

- `registry://<hash>`（基于 ASVP `manifest.json` 的规范化内容哈希）

目标是让执行从“路径依赖”（path-based）向“引用依赖”（ref-based）迁移，同时保持 ASVP 验签（verification）与 evidence/trace 可回放语义不变，并且不引入网络下载逻辑（local-only）。

本线程对应 Spike：`Spike-REG1`。

## 范围 (In Scope)

- 内容寻址 ID（content address / registry id）生成：基于 ASVP `manifest.json` 的 canonical bytes
- 本地只读索引（local read-only index）：`registry_id -> local_path`
- `ExecuteRequest.skill_ref` 支持 `registry://...` 形式并可执行
- 契约对齐：经 registry 引用执行与路径执行在语义上等效（等效验签、等效 output contract）

## 非范围 (Out of Scope)

- 网络下载、市场（marketplace）、远程 registry 服务
- 依赖解析（dependencies）与复杂版本约束（本 spike 先 no-deps）

## 非协商约束 (Non-Negotiables)

- 不得破坏既有 CLI 稳定 JSON 输出与 evidence/trace schema。
- registry 解析失败必须 fail-closed，并返回稳定错误码。
- registry id 必须可复现（deterministic），用于 replay/仲裁。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): N/A（MVP 快速迭代：先落地再补交叉评审）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## 消息记录 (Message Log)

- ext_gpt5_2: 提议并落地 “LocalExecutor 解析 registry:// -> skill_dir” 的最小改动路径，并保持 ASVP verify 语义不变（见 inputs/specs）
- host: 强调 non-negotiables（fail-closed、不破坏 CLI/evidence/trace、local-only 无网络）

## Evidence (Links)

- `docs/specs/MVP_013_REGISTRY.md`（REG1 规范草案）
- `docs/specs/SKILL_PACKAGE_ASVP.md`（ASVP canonical manifest + verification）
- `docs/specs/EXECUTOR_API.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2.md`（message id: `20260219-ext_gpt5_2-009`）
- `src/agentos_next/kernel/skill_registry.py`
- `src/agentos_next/runtime/local_executor.py`
- `tests/test_spike_reg1_skill_registry.py`
- `docs/journal/SYNTHESIS_20260219-REG1-009.md`
- `docs/journal/DECISIONS_20260219-REG1-009.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_REG1_009_round2_cross_review.md`

