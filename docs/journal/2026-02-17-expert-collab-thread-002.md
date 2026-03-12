# 2026-02-17 外部专家协作线程 002 (External Expert Collaboration Thread 002)

- `thread_id`: `20260217-EXT-COLLAB-002`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-17`
- `owner`: `ext_gemini_flash`

## 问题陈述 (Problem Statement)

验收 Spike-005 产出的 `Orchestrator` 与 `LocalExecutor` 稳定性，补齐本地运行时缺失（超时控制），并定义 `RemoteExecutor` 的 API 契约与 Spike-CR1 的集成边界。

## 范围 (In Scope)

-   `LocalExecutor` 超时机制 (`deadline_ms`)。
-   `RemoteExecutor` API 契约 (`docs/specs/REMOTE_SANDBOX_API.md`)。
-   `RemoteExecutor` 与 Spike-CR1/MR1 的集成验证（Payload 结构、Policy Context 透传）。
-   验证 `replay-mode` 下远程调用的阻断行为。

## 轮次进度 (Rounds)

-   Round 0 (线程设定): 完成
-   Round 1 (独立提案): 完成 (INPUT_ext_gemini_flash.md)
-   Round 2 (交叉评审): 完成 (bus-005, bus-010, bus-012, bus-014, bus-015)
-   Round 3 (综合): 完成
-   Round 4 (裁决): 完成

## 最终裁决摘要 (Final Decision Summary)

### Decision 001: LocalExecutor Timeout
-   **状态**: `accepted`
-   **结论**: `LocalExecutor` 必须支持 `deadline_ms`，默认 60s。
-   **实现**: 使用 `asyncio.wait_for` 与线程池执行。
-   **验证**: `tests/test_local_executor_timeout.py` (PASS)。

### Decision 002: Remote API Schema
-   **状态**: `accepted`
-   **结论**: 采用 v1.0.0-frozen Schema。
-   **关键点**:
    -   `skill_ref` 作为通用资源定位符。
    -   `policy_context` 支持前向扩展，未知键值应被 Log 但不报错。
    -   模型路由键统一为 `policy_context["model"]`，`model_id_override` 作为 Legacy Alias。
-   **验证**: `tests/test_remote_executor_cr1_payload.py` (PASS)。

### Decision 003: CR1 Integration
-   **状态**: `accepted`
-   **结论**: Spike-CR1 的 `ExecuteRequest` 构造逻辑与 Remote API Schema 对齐。
-   **验证**: 集成测试通过，Trace/Policy Context 映射正确。

### Decision 004: Replay Mode Safety
-   **状态**: `accepted`
-   **结论**: `replay-mode` 必须阻断所有远程 Backend 调用。
-   **验证**: `tests/test_replay_mode_blocks_remote_backend.py` (PASS)。

## 输出产物 (Artifacts)

-   `docs/specs/REMOTE_SANDBOX_API.md`
-   `src/agentos_next/runtime/local_executor.py`
-   `src/agentos_next/runtime/remote_executor.py`
-   `tests/test_local_executor_timeout.py`
-   `tests/test_remote_executor_cr1_payload.py`

## 下一步 (Next Steps)

-   合并 CR1/MR1/Remote API 相关改动。
-   准备下一轮迭代：实现真实的 Remote Sandbox Client 或本地 Docker Sandbox。

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260217_EXT_COLLAB_002_round2_cross_review.md`

