# SYNTHESIS: Assistant Loop (Tool-Calling / Multi-Step) Bounded Spike (AL1)

- `thread_id`: `20260219-ASSISTANT-LOOP-004`
- `updated_at`: `2026-02-19`
- `status`: `resolved`
- `owner`: `human + codex`

## Summary（综合摘要）

本线程将 “assistant loop bounded spike” 从聊天建议落盘为协议化的可执行实验：定义了 assistant loop 的最小闭环语义（多步 + tool-calling + boundedness + 可审计），并给出 Spike-AL1 的交付物、Kill Criteria、Gate 与 Acceptance。

核心共识：
- assistant loop 是位于 `Orchestrator.execute(ExecuteRequest)` 之上的“多步控制层”，负责在 LLM（或替代 planner）与工具执行之间循环，但工具执行必须继续通过 Orchestrator/Executor 以复用既有 fail-closed 与证据链能力。
- Spike-AL1 必须优先验证 boundedness 与审计性，而不是追求“更聪明的规划”。

## Working Definition（assistant loop 工作定义）

assistant loop = 在单个“用户意图/任务”上下文内重复以下步骤，直到完成或触发终止条件：

1. `decide_next_action(state) -> action`
   - action ∈ {tool_call(ExecuteRequest), finalize, ask_human, abort}
2. 若是 tool_call：调用 `Orchestrator.execute(req)` 获取 `ExecuteResult` 与 evidence/trace side-effects
3. 将 observation（结果摘要 + evidence_refs + artifact_refs）写回 state
4. 检查 boundedness / policy：若超过阈值则 fail-closed 终止

## Bounded Spike Proposal（Spike-AL1）

### Goal（目标）

验证 “多步执行 + 工具调用 + 证据链” 可以在不破坏现有契约的前提下闭环：
- bounded：`max_steps` 与 `deadline_ms` 强制上限
- safe：replay-mode/远程策略不被绕过
- auditable：每一步可产生可复核 trace/evidence

### Non-Goals（非目标）

- 不要求接入真实 LLM Provider；允许通过 deterministic planner/stub 产生 tool_call 序列以验证控制流。
- 不要求实现完整的对话式 UI、长期记忆整理、复杂 multi-agent 协作。

### Minimal Architecture（最小架构选择）

选择 A（最小侵入）：
- 新增 `AssistantLoopRunner`（或等价组件），作为 library/API + 受控 CLI（可选）。
- Runner 通过依赖注入的 `Planner` 产出下一步 action；Planner 可为 stub（deterministic）或未来 LLM planner。
- 工具执行仍统一走 `Orchestrator.execute`（不在 loop 内旁路调用 LocalExecutor/PackageRunner）。

拒绝 B（本轮不做）：
- 将 assistant loop 内嵌入 Orchestrator 或更底层执行器，导致职责混乱与回归风险上升。

## Gates & Acceptance（门禁与验收口径）

本线程将 gates/acceptance 作为 Spike-AL1 实现 PR 的验收标准，详见：
- `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md`

## Evidence（证据）

- `docs/journal/inputs/INPUT_ext_claude_bus_mvp010_007.md`（提出下一步：assistant loop bounded spike）
- `docs/journal/inputs/INPUT_ext_claude_assistant_loop_al1.md`
- `docs/journal/inputs/INPUT_host_codex_assistant_loop_al1.md`
- `docs/journal/2026-02-19-expert-collab-thread-003.md`（Follow-up/主动循环作为 P0 能力来源）

## Addendum（追加）：AL1 当前落地形态（as of 2026-02-19）

- 实现落点：
  - `src/agentos_next/apps/assistant_loop.py`（deterministic 计划 + 多步 `Orchestrator.execute`）
  - `src/agentos_next/cli.py`（`mvp assistant-loop`）
- 验收证据：
  - `tests/test_spike_al1_assistant_loop.py`（至少一次 `builtin://memory.*` tool call + 个人助理 skill，并验证 evidence/trace 落盘）
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（全绿）
