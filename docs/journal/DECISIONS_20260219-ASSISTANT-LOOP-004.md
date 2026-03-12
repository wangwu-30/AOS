# DECISIONS: Assistant Loop (Tool-Calling / Multi-Step) Bounded Spike (AL1)

- `thread_id`: `20260219-ASSISTANT-LOOP-004`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: Spike-AL1 Landing Shape

- **状态**: `accepted`
- **结论**: assistant loop 作为 `Orchestrator.execute(ExecuteRequest)` 之上的多步控制层（control layer），以最小侵入方式落地为新增 CLI 与 app 模块；工具调用（tool-calling）一律通过 Orchestrator/Executor 链路执行，不允许旁路 PackageRunner/LocalExecutor 产生不可审计副作用。
- **实现落点（Landing）**:
  - App: `src/agentos_next/apps/assistant_loop.py`
  - CLI: `python -m agentos_next.cli mvp assistant-loop ...`

## Gate（必须通过的门禁）

1. **Boundedness（有界性）**：
   - 必须（MUST）有硬上限：`deadline_ms`；且步数必须有限（MVP 允许固定步数或显式 `max_steps`）。
2. **Fail-Closed（失败即关闭）**：
   - 任一步失败必须（MUST）终止后续自动执行，返回稳定错误码，不泄露堆栈。
3. **Remote Safety（远程安全闸门不降级）**：
   - replay-mode 下必须（MUST）禁止任何远程调用（remote call），即使 gates 打开也不允许。
   - 远程 LLM 调用必须（MUST）继续遵守双闸门：`remote_calls_armed` + `allow_network_egress`。
4. **Auditability（可审计/可回放）**：
   - 每一步执行必须（MUST）落盘 evidence/trace（复用既有机制）。
   - “检索链回放”（retrieval chain replay）必须（MUST）有明确 trace/evidence 语义（对齐 `RETRIEVAL_CHAIN`）。
5. **契约不回归**：
   - 不得（MUST NOT）破坏既有 CLI 稳定 JSON 输出与 evidence/trace schema；新增命令应仅增加回归覆盖。

## Acceptance（可验证验收）

- 全量回归：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- assistant loop 最小闭环（含至少一次 builtin memory.* tool call）：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_al1_assistant_loop.py' -v`
- retrieval chain 语义存在：
  - `cd agentos-next && rg -n \"RETRIEVAL_CHAIN\" docs/specs/EVIDENCE_TRACE.md src/agentos_next/kernel/types.py`

## Evidence（证据）

- Thread: `docs/journal/2026-02-19-expert-collab-thread-004.md`
- Synthesis: `docs/journal/SYNTHESIS_20260219-ASSISTANT-LOOP-004.md`
- Inputs:
  - `docs/journal/inputs/INPUT_ext_claude_assistant_loop_al1.md`
- Code/Test:
  - `src/agentos_next/apps/assistant_loop.py`
  - `src/agentos_next/cli.py`
  - `tests/test_spike_al1_assistant_loop.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

