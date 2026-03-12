# DECISIONS: OpenCLAW Assistant Capabilities + Memory (L0/L1/L2) + Remote API Extensions

- `thread_id`: `20260219-OPENCLAW-ASSISTANT-003`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: P0/P1 Capability Split
- **状态**: `accepted`
- **结论**: 采用 ext_gpt5_3 (bus-021) 提出的优先级划分。
- **关键点**:
    - 优先补齐 Memory API 与 Scheduler 机制。
    - 个人助理核心能力（跟进、任务生成）依赖内核级状态机支持。
- **验证**: 后续 MVP-010 实现将对齐此优先级。

## Decision 002: Memory Layering (L0/L1/L2) Landing
- **状态**: `accepted`
- **结论**: 借鉴 OpenViking 架构，将 AgentOS 现有 trace/evidence/artifact 语义对齐到 L0/L1/L2 分层。
- **关键点**:
    - L2 必须是 immutable Artifact。
    - L0/L1 支持 TTL 与 Redaction。
- **验证**: `tests/test_admission_redaction.py` (PASS)。

## Decision 003: Remote API Extension for Memory Context
- **状态**: `accepted`
- **结论**: 采用 `policy_context` 作为扩展点（Spike-MEMCTX1），不修改 `ExecuteRequest` 顶层字段。
- **关键点**:
    - 新增 `policy_context.memory_context` 结构（v1.0.0）：`{ "schema_version": "1.0.0", "l0_session_inline": "...", "l1_short_refs": ["ev_..."], "l2_long_query": {...} }`。
    - **单一硬回退阈值 (One Hard Requirement)**: 若内核/网关需要在不解析 policy blob 的情况下执行 OS 级配额限制或计费治理，则触发 Spike-MEMCTX2 将其升格为顶层字段。
- **验证**:
    - `tests/test_remote_executor_cr1_payload.py` (验证未知键透传 PASS)。
    - 规范落盘：`docs/specs/MVP_010_MEMORY.md`。

## Decision 004: Skill Package Manifest
- **状态**: `accepted`
- **结论**: 保持 ASVP Manifest 最小化。
- **关键点**:
    - 发现元数据（discovery meta）必须作为 `package_meta.json` 存在于包内，而非 Manifest 字段。
- **验证**: `tests/test_skillc_build_compiled_outputs.py` (PASS)。

## Decision 005: Spike-MEMCTX1/MEMCTX2 Consensus (EXT-COLLAB Alignment)
- **状态**: `accepted`
- **结论**:
    - Spike-MEMCTX1：`policy_context["memory_context"]` 是 v1.0.0-frozen Remote API 的前向兼容扩展点，RemoteExecutor MUST 原样透传该字段（不引入 `ExecuteRequest` 顶层字段变更）。
    - Spike-MEMCTX2：仅在触发“单一硬需求”时，才进入顶层字段升格与版本化设计。
- **关键点**:
    - **MEMCTX1 透传语义（MUST）**：
        - `memory_context` MUST 通过 `policy_context` 透传，且执行侧不得重写/规范化内部结构（opaque extension payload）。
    - **MEMCTX2 升格硬触发（MUST）**：
        - 若 Kernel/网关需要在不解析 policy blob 的情况下对 `memory_context` 做一致的 OS 级 quota/深度/计费拦截（governance & enforcement），则 MUST 将 `memory_context` 升格为 `ExecuteRequest` 顶层字段，并通过版本化与回归测试保证兼容。
- **验收 (Acceptance)**:
    - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_remote_executor_cr1_payload.py' -v`
    - `cd agentos-next && PYTHONPATH=src:tests python3 -m unittest -v test_remote_executor_cr1_payload.TestRemoteExecutorCR1Payload.test_memory_context_is_preserved_as_policy_context_extension`
- **证据**:
    - `tests/test_remote_executor_cr1_payload.py`（`test_memory_context_is_preserved_as_policy_context_extension`）
    - `docs/specs/REMOTE_SANDBOX_API.md`（`policy_context` extension point + memory_context note）
    - `docs/specs/MVP_010_MEMORY.md`（MVP-010 记忆系统规范）

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

