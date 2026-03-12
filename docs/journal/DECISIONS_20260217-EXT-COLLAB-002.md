# DECISIONS: Orchestrator & Remote API & CR1 Integration

- `thread_id`: `20260217-EXT-COLLAB-002`
- `updated_at`: `2026-02-17`
- `status`: `finalized`

## Decision 001: LocalExecutor Timeout Enforcement
-   **状态**: `accepted`
-   **结论**: `LocalExecutor` 必须支持 `deadline_ms`，默认 60s。
-   **实现**: 使用 `asyncio.wait_for` 与线程池执行，确保同步的 `PackageRunner` 调用在超时后被中断。
-   **证据**:
    -   `tests/test_local_executor_timeout.py` (PASS)
    -   `src/agentos_next/runtime/local_executor.py`

## Decision 002: Remote API Schema Freeze (v1.0.0-frozen)
-   **状态**: `accepted`
-   **结论**: 采用 v1.0.0-frozen Schema 作为 Remote API 契约，支持 Spike-CR1/MR1 的前向扩展。
-   **关键点**:
    -   `skill_ref` 必须作为通用资源定位符 (S3/Registry)。
    -   `policy_context` 支持未知键值透传（前向兼容）。
    -   模型路由键统一为 `policy_context["model"]`，`model_id_override` 仅作 Legacy Alias。
-   **证据**:
    -   `docs/specs/REMOTE_SANDBOX_API.md`
    -   `tests/test_remote_executor_cr1_payload.py` (PASS)

## Decision 003: Spike-CR1 Integration & Gates
-   **状态**: `accepted`
-   **结论**: Spike-CR1 的 `ExecuteRequest` 构造逻辑已通过 Remote API 的集成验证，且通过了 4-Gate Review。
-   **关键点**:
    -   Gate-1 (Minimal Schema): PASS (Only minimal SC1 fields used).
    -   Gate-2 (Fail-Closed): PASS (Plan-only, Replay-mode blocks remote).
    -   Gate-3 (Contract Stability): PASS (No regression in CLI/Evidence/Trace).
    -   Gate-4 (Composition Alignment): PASS (Payload matches ExecuteRequest).
-   **证据**:
    -   `bus-015` (GPT-5.2 Verdict: PASS)
    -   `bus-011` (Gemini Flash Verdict: PASS)
    -   `tests/test_remote_executor_cr1_payload.py`

## Decision 004: Replay Mode Safety
-   **状态**: `accepted`
-   **结论**: `replay-mode` 必须强制阻断所有远程 Backend 调用，无论 policy 配置如何。
-   **证据**:
    -   `tests/test_replay_mode_blocks_remote_backend.py` (PASS)

## 后续行动 (Follow-up)
-   在 `docs/specs/VERSIONING_COMPAT.md` 中记录 `model_id_override` 的 Deprecation Timeline。
-   准备下一轮迭代：实现 `RemoteExecutor` 的 HTTP Client 逻辑。

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

