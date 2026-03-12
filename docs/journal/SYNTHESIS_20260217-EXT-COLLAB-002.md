# Synthesis: Orchestrator & Remote API & CR1 Integration

- `thread_id`: `20260217-EXT-COLLAB-002`
- `updated_at`: `2026-02-17`
- `sources`:
  - `docs/journal/inputs/INPUT_ext_gemini_flash.md`
  - `bus-010` (from gpt5.2: CR1/MR1 model key alignment)
  - `bus-015` (from gpt5.2: CR1 4-Gate Review)
  - `bus-011` (from ext_gemini_flash: Payload Integration)

## Consensus

1.  **LocalExecutor Timeout**: `LocalExecutor` 必须通过 `deadline_ms` 参数强制执行超时，以防止长时间阻塞本地资源。默认 60s 是合理的 MVP 设定。
2.  **Remote API Schema**: 采用 V1.0.0-frozen Schema，明确 `skill_ref` 为通用资源定位符，`policy_context` 支持前向扩展。
3.  **Spike-CR1 Integration**: Spike-CR1 生成的 `ExecuteRequest` 结构必须与 Remote API Schema 对齐，并通过 mock payload check 验证。
4.  **Model Routing**: 模型路由参数统一通过 `policy_context["model"]` 传递，`model_id_override` 仅作为 Legacy Alias 保留。
5.  **Replay Mode**: `replay-mode` 必须作为绝对安全闸门，阻断所有远程 Backend 调用。

## Conflicts

-   `model_id_override` vs `model`: 初期存在字段命名不一致。
    -   **Resolution**: 统一为 `model` (Preferred)，保留 `model_id_override` (Legacy Alias)。
    -   **Impact**: 已更新 Spec 文档与测试用例，未引入 Breaking Change。

## Issue Status

-   `LocalExecutor Timeout`: `resolved` (Implemented & Tested)
-   `Remote API Schema`: `resolved` (Frozen v1.0.0)
-   `CR1 Integration`: `resolved` (Verified Payload Structure)
-   `Replay Mode Safety`: `resolved` (Verified Blocks Remote Calls)

## Recommended Direction

-   **Next Phase**: 实现真实的 Remote Sandbox Client 或本地 Docker Sandbox。
-   **Documentation**: 在 `docs/specs/VERSIONING_COMPAT.md` 中记录 `model_id_override` 的 Deprecation Timeline。
