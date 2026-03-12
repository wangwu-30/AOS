# DECISIONS: AgentOS Next MVP

- `thread_id`: `MVP-20260218`
- `updated_at`: `2026-02-25`
- `status`: `accepted`

---

## Decision MVP-001: MVP Spikes 完成状态

- **状态**: `accepted`
- **结论**: MVP 核心 Spikes 全部完成，并在后续 P0/P1 迭代中持续扩展基线（仍保持非协商约束：fail-closed/replay/evidence-by-default/top-level API stable）。

| Spike | 状态 | 说明 |
|-------|------|------|
| MR1 (模型路由) | ✅ Done | CLI --model 覆盖，policy_context["model"] |
| OC1 (通道) | ✅ Done | channel-stdio |
| SC1 (编译) | ✅ Done | compiled 目录生成 |
| CR1 (Creator) | ✅ Done | discovery + plan-only compose |
| Remote API | ✅ Done | v1.0.0 frozen |

- **回归基线**: 45/45 ✅
- **证据**:
  - `tests/test_spike_orchestrator_routing.py`
  - `tests/test_spike_oc1_channel_stdio.py`
  - `tests/test_skillc_build_compiled_outputs.py`
  - `tests/test_spike_cr1_creator_plan.py`
  - `docs/specs/REMOTE_SANDBOX_API.md`

### 基线扩展（Post-MVP Additions）

- **当前回归基线**: 92/92 ✅（`2026-02-25`）
- **覆盖范围**（示例）：
  - Memory (MVP-010) / Assistant Loop (MVP-011) / Follow-up Scheduling (FU2)
  - Scheduler primitives (SCHED1) / Skill Registry content addressing (REG1)
  - Daemon primitives (DM2) / scheduler-tick deterministic fallback
  - Local gateway channel (CH1 HTTP-only + stateless-by-trace)
  - Memory effect evaluation harness (THREAD-022 A/B/C, effect-first metrics)
  - Dialog State Machine (SM1/SM2) / Registry version+deps (REG2)
  - SI1 Phase-1 (Observe/Propose/Validate) / Assistant App Reference Architecture (THREAD-016) + HY2/GT2 gates
- **证据（新基线）**：
  - `docs/journal/DECISIONS_20260219-OPENCLAW-ASSISTANT-003.md`
  - `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md`
  - `docs/journal/DECISIONS_20260219-AL2-PLANNER-005.md`
  - `docs/journal/DECISIONS_20260219-AL3-STDIO-006.md`
  - `docs/journal/DECISIONS_20260220-FU2-FOLLOWUP-SCHED-012.md`
  - `docs/journal/DECISIONS_20260219-SCHED1-008.md`
  - `docs/journal/DECISIONS_20260219-REG1-009.md`
  - `docs/journal/DECISIONS_20260219-P1-DIALOG-SM-010.md`
  - `docs/journal/DECISIONS_20260220-SM2-SCHED-DIALOG-011.md`
  - `docs/journal/DECISIONS_20260220-REG2-VDEPS-013.md`
  - `docs/journal/DECISIONS_20260220-SI1-AUTOEVOLVE-014.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-HY2-HYBRID-EQUIVALENCE-017.md`
  - `docs/journal/DECISIONS_20260224-GT2-GOLDEN-TRACE-GATE-018.md`
  - `docs/journal/DECISIONS_20260225-DM2-DAEMON-019.md`
  - `docs/journal/DECISIONS_20260225-CH1-LOCAL-GATEWAY-020.md`
  - `docs/specs/MVP_022_MEMORY_EFFECT_EVAL.md`
  - `tests/test_eval_memory_effect.py`
  - `tests/test_eval_memory_compare.py`
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（92/92 OK）

---

## Decision MVP-002: MR1 模型路由链路

- **状态**: `accepted`
- **结论**: 模型覆盖优先级为 CLI --model > skill execution_profile.model_id
- **透传链路**:
  ```
  CLI --model → policy_context["model"] → LocalExecutor → PackageRunRequest.model_id_override → execute_skill_via_llm → backend.complete_json(model_id)
  ```
- **错误码**: 无新增，复用 E_LLM_CALL / E_PROVIDER_BAD_RESPONSE
- **字段收敛**: 远程 payload 只使用 `policy_context["model"]`，不再输出 `model_id_override` 别名
- **证据**:
  - `src/agentos_next/cli.py`
  - `src/agentos_next/runtime/local_executor.py`
  - `src/agentos_next/skills/llm_execution.py`

---

## Decision MVP-003: OC1 通道架构

- **状态**: `accepted`
- **结论**: channel-stdio 支持 stdin 每行消息 -> ExecuteRequest -> JSONL 输出
- **证据**:
  - `tests/test_spike_oc1_channel_stdio.py`
  - trace/evidence 落盘，支持 --json-lines

---

## Decision MVP-004: SC1 编译形态

- **状态**: `accepted`
- **结论**: Skill 编译输出 compiled/ 目录，包含 minimal schema
- **minimal schema 字段**:
  - schema_version
  - constraints
  - name
  - version
  - description
  - intent
- **产物**:
  - prompt_bundle.json
  - execution_ir.json
  - inputs_schema.json
  - outputs_schema.json
  - acceptance_rules.json
  - execution_profile.json
- **证据**:
  - `tests/test_skillc_build_compiled_outputs.py`
  - `docs/specs/SKILL_CONTRACT.md`

---

## Decision MVP-005: CR1 Creator 架构

- **状态**: `accepted`
- **结论**: deterministic discovery + plan-only compose
- **discovery**: 仅依赖 SC1 minimal schema
- **compose**: 产物对齐 ExecuteRequest，模型覆盖通过 policy_context["model"] 透传
- **4-Gate Review**: PASS (0 blockers)
  - Gate-1: 仅依赖 SC1 minimal schema ✅
  - Gate-2: fail-closed/double gating 不降级 ✅
  - Gate-3: CLI/evidence/trace 契约不回归 ✅
  - Gate-4: ExecuteRequest 对齐 ✅
- **错误码**:
  - E_CREATOR_REGISTRY_INVALID
  - E_CREATOR_SCHEMA_UNSUPPORTED
  - E_CREATOR_COMPOSE_INVALID
- **证据**:
  - `src/agentos_next/creator/skill_creator.py`
  - `tests/test_spike_cr1_creator_plan.py`
  - `docs/specs/SKILL_CREATOR.md`

---

## Decision MVP-006: Remote API Schema (v1.0.0-frozen)

- **状态**: `accepted`
- **结论**: Remote API Schema 冻结为 v1.0.0，支持 CR1/MR1 前向扩展
- **关键点**:
  - skill_ref 作为通用资源定位符
  - policy_context 支持未知键值透传
  - 模型路由键统一为 policy_context["model"]
- **证据**:
  - `docs/specs/REMOTE_SANDBOX_API.md`
  - `tests/test_remote_executor_cr1_payload.py`

---

## Decision MVP-007: Replay Mode 安全

- **状态**: `accepted`
- **结论**: replay-mode 必须强制阻断所有远程 Backend 调用
- **证据**:
  - `tests/test_replay_mode_blocks_remote_backend.py`

---

## Decision MVP-008: Orchestrator -> Executor 链路

- **状态**: `accepted`
- **结论**: LocalExecutor 支持 timeout， Orchestrator 路由到 LocalExecutor/RemoteExecutor
- **超时实现**: asyncio.wait_for + 线程池执行
- **证据**:
  - `tests/test_local_executor_timeout.py`
  - `tests/test_spike_orchestrator_routing.py`

---

## 后续行动 (Follow-up)

- [ ] 实现 RemoteExecutor HTTP Client 逻辑
- [ ] 准备下一轮迭代：更多 channel 实现、远程执行优化

---

## 历史参考

- **DECISIONS_20260214-EXT-COLLAB_001**: 协作协议、PackageRunner/Executor 语义收敛
- **DECISIONS_20260217-EXT-COLLAB_002**: LocalExecutor Timeout、Remote API Schema、CR1 Integration、Replay Mode

---

## Decision MVP-009: ASVP 包形态 + Extensible Content Metadata

- **状态**: `accepted`
- **结论**:
  - ASVP 目录包作为唯一默认分发单位
  - manifest 最小 MUST 字段保持不扩张
  - 发现/索引元数据放普通内容文件（如 package_meta.json）并纳入 manifest.files
  - compiled/* 继续 audit-only，作为 deterministic discovery/compose 的主输入，运行时不设硬依赖
- **意义**: Skill 市场可在不改 ASVP 协议的前提下演进检索能力
- **证据**:
  - `docs/specs/SKILL_PACKAGE_ASVP.md`

---

## Decision MVP-010: OpenCLAW 个人助手功能优先级

- **状态**: `accepted`
- **结论**: 功能分层 + Skills 映射 + Remote API 扩展

### 优先级分层

| 层级 | 功能 | 说明 |
|-----|------|------|
| P0 | 记忆管理、主动任务跟进、定时任务、状态机、幂等去重、HITL/blacklist policy gate | 平台最小闭环 |
| P0.5 | 子 Agent（最小 delegation loop） | 最小化先行 |
| P1 | 编程能力、通讯（Telegram/Discord）、多通道 | 能力放大器 |

### Skills 映射

| 功能 | Skills |
|-----|--------|
| 记忆管理 | memory.write, memory.search, memory.compact, memory.delete |
| 主动任务跟进 | followup.plan, followup.dispatch |
| 定时任务 | schedule.create, schedule.tick |
| 编程能力 | code.plan, code.apply, code.test |
| 子 Agent | agent.spawn, agent.join |
| 通讯 | channel.telegram, channel.discord |

### Remote API 扩展

- 新增 `trigger` 字段
- policy_context 新增 `budget_limit`, `streaming`

### 平台机制要求

- workspace namespace + evidence/artifact + redaction policy
- task state machine + idempotency guard
- fail-closed/double gating/replay-mode 禁远程不降级

### 验收标准

- 本地 CLI 跑通闭环：memory.write -> schedule.create -> schedule.tick -> followup.plan -> (需要副作用时) followup.dispatch 进入 HITL
- 全程 evidence/trace 可回放

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

