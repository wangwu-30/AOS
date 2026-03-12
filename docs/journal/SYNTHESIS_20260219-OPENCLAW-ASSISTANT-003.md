# SYNTHESIS: OpenCLAW Assistant Capabilities (P0/P1) + Memory (L0/L1/L2) + Remote API Extensions

- `thread_id`: `20260219-OPENCLAW-ASSISTANT-003`
- `updated_at`: `2026-02-19`
- `status`: `resolved`
- `owner`: `ext_gemini_flash`

## Summary（综合摘要）

本线程完成了 OpenCLAW 风格助手能力的拆解与 AgentOS Skills 映射，确立了分层记忆（L0/L1/L2）架构，并定义了 Remote API 对调度、通道及记忆上下文的扩展。

### 1. 能力拆分与优先级 (P0/P1)
- **P0 (核心基石)**:
    - **Memory API**: 映射为 `memory-read/write/compact` Skills。支持 L0 (Session), L1 (Short-term), L2 (Long-term/Artifacts)。
    - **Scheduler**: 映射为 `scheduler-cron/at`。通过 `ExecuteRequest` 的 `trigger` 字段支持。
    - **Follow-up**: 主动任务跟进循环，依赖内核 Orchestrator 状态机。
    - **HITL Policy**: 高风险操作强制人类确认。
- **P1 (能力放大)**:
    - **Coding**: `coding-assistant` Skill。支持补丁生成与测试。
    - **Delegation**: `delegation-orchestrator` Skill。产出子任务 `ExecuteRequest`。
    - **Channels**: `channel-telegram/discord` Skills。作为交互适配层。

### 2. 分层记忆架构 (OpenViking 借鉴)
- **L0_session**: 当前会话上下文。映射为 trace + session snapshot。Remote API 采用内联 (inline) 传递。
- **L1_short**: 短期记忆。映射为 evidence + draft artifact。Remote API 采用引用 (refs) 传递。
- **L2_long**: 长期记忆。映射为已归档 Artifact (不可篡改)。Remote API 采用查询参数 (query_params) 传递。
- **治理**: 强制 PII 脱敏（复用 `redaction.py`）与 TTL 删除语义。

### 3. Remote API 扩展与治理
- **ExecuteRequest**:
    - 新增 `trigger` (optional): 支持调度任务。
    - 新增 `policy_context.streaming`: 支持流式回传。
    - 新增 `policy_context.budget_limit`: 治理预算。
    - 新增 `policy_context.memory_context`: 分层上下文透传。
- **Callback**: 定义 `POST /v1/callback` 用于异步消息/流式数据回传。

### 4. Skill 包形态
- 坚持 **ASVP** 最小 Manifest 集。
- 发现/组合元数据作为内容文件（如 `package_meta.json`）纳入 Manifest，不扩张顶层字段。

## Conflicts & Spikes（冲突与实验）

- **冲突**: 是否在 `ExecuteRequest` 顶层增加 `memory_context`？
- **实验 (Spike-MEMCTX1)**: 验证将 `memory_context` 放入 `policy_context` 的前向兼容性。
- **结论**: 采用 B方案（放入 `policy_context`），避免破坏既有 Kernel 顶层 API。

## Evidence（证据）

- `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md` (bus-021)
- `docs/journal/inputs/INPUT_ext_claude_openviking_analysis.md` (bus-029)
- `docs/journal/inputs/INPUT_ext_gpt5_2.md` (20260219-ext_gpt5_2-013)
- `tests/test_remote_executor_cr1_payload.py` (验证 policy_context 扩展性)

## Addendum（追加）：Spike-MEMCTX1/MEMCTX2 共识（EXT-COLLAB 对齐）

- **共识 (Spike-MEMCTX1)**:
    - `memory_context` MUST 作为 `policy_context["memory_context"]` 的扩展点进行透传（forward-compatible extension point）。
    - `memory_context` 在 Remote API / RemoteExecutor 侧 SHOULD 视为不透明对象（opaque blob）；不得重写/规范化其内部结构与键名，仅负责原样传递。
- **硬触发条件 (Spike-MEMCTX2)**:
    - 仅当 **Kernel 或 API Gateway 需要在不解析任意 policy blob 的情况下**，对 `memory_context` 执行一致的 OS 级配额/深度/计费拦截（quota/billing enforcement）时，才 MUST 将其升格为 `ExecuteRequest` 的顶层字段（并以版本化请求保证兼容）。
- **验收 (Acceptance)**:
    - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_remote_executor_cr1_payload.py' -v`
    - `cd agentos-next && PYTHONPATH=src:tests python3 -m unittest -v test_remote_executor_cr1_payload.TestRemoteExecutorCR1Payload.test_memory_context_is_preserved_as_policy_context_extension`
