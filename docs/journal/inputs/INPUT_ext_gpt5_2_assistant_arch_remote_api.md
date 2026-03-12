id: `20260224-ext_gpt5_2-assistant-arch-remote-001`
author: `ext_gpt5_2`
topic: `THREAD-016 Remote/API 边界评审（代替 ext_gemini_flash）：assistant app 引入 event-driven/plugin/GT 的前向兼容策略`
position:
- 我认为 THREAD-016 的 3 个决策点（runtime / plugin / golden trace）必须首先服从 Remote/API 的不变量：**不新增 ExecuteRequest 顶层字段**、扩展仅通过 `policy_context`，并保持 `REMOTE_SANDBOX_API.md` 的 forward-compatible 语义（unknown keys preserve/ignore）。
- 结论倾向：Decision001 选 C（Hybrid event-driven minimal core）、Decision002 选 B（P0 不引入完整 plugin/hook system，P1 再引入）、Decision003 选 A（P0 引入最小 Golden Trace）。其中 Remote 视角的关键理由是：
  - event-driven core 更容易把 daemon/channels/trigger/follow-up 统一收敛为“可审计事件流”，并天然对齐 trace_context / idempotency / deadline 的治理语义；
  - 过早引入 plugin/hook system 很容易让“policy_context 透传、replay-mode 阻断、double gating”在不同插件里发生不一致（治理面分叉），导致远程执行边界失控；
  - 最小 Golden Trace（Golden Tests/Golden Trace）能把 remote boundary 变成可执行断言，避免“交互层复杂化后，远程副作用/不可回放行为偷偷溜进来”。
- Remote/API 的硬边界建议：
  - assistant app 侧新增的事件字段（例如 `dialog_trace_id`、`trigger`、`memory_context`）一律先落 `policy_context`，并由 Kernel 执行点作为 PEP（Policy Enforcement Point）统一校验（replay-mode、double gating、HITL）。
  - 若未来出现“OS 级配额/计费拦截必须不解析 policy blob”的硬需求，再用 bounded spike 触发顶层字段升级（类似 MEMCTX2 的 hard requirement）。
evidence:
- Remote API 扩展点定义：`docs/specs/REMOTE_SANDBOX_API.md`（`policy_context` 是 extension point；包含 `model` / `memory_context` 示例）
- ExecuteRequest 顶层稳定性约束：`docs/specs/EXECUTOR_API.md`（policy_context、路径安全、idempotency/replay 要求）
- RemoteExecutor 当前透传实现：`src/agentos_next/runtime/remote_executor.py`（preserve unknown keys；`model` 优先/legacy alias）
- Assistant Loop 的 replay/double-gating 语义：`docs/specs/MVP_011_ASSISTANT_LOOP.md`
- Scheduler 的 deterministic fallback 约束（daemon 也需保留 runner/tick）：`docs/specs/MVP_012_SCHEDULER.md`
- 回归基线：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前全绿）
tradeoffs:
- Hybrid event-driven minimal core（Decision001-C）：
  - 收益：对 remote payload 的边界更清晰（event→task→ExecuteRequest）；更利于在单一执行点统一 enforce replay/double-gating/HITL。
  - 成本/风险：引入事件流的复杂度；若缺少 Golden Trace，容易出现“事件触发重复/时序 bug”而难以复现。
- Plugin system 延后（Decision002-B）：
  - 收益：减少“治理分叉点”；remote boundary 与 policy enforcement 更容易集中在 Kernel/Orchestrator/Executor。
  - 成本/风险：短期可替换性弱；但可用 bounded spike（仅 Transport plugin）验证收益后再扩展。
- 最小 Golden Trace（Decision003-A）：
  - 收益：把 remote boundary 写成断言（例如 replay-mode 0 副作用、unknown policy keys 透传保持、双闸门必须同时满足）。
  - 成本/风险：需要维护少量 golden 断言与稳定 trace view 导出；但比事后排查远程副作用成本更低。
open_questions:
- Golden Trace 与现有 evidence/trace 的复用方式：是直接断言 JSONL/evidence refs，还是额外导出 UI view（建议优先断言现有 schema，UI view 作为衍生物）。
- Transport plugin 的最小边界：若要 P0 尝试插件化，是否只允许“输入输出适配层”插件化（CLI/WS），并禁止插件直接影响 policy gates？
proposal:
- Bounded spikes（均需 kill criteria）：
  - Spike-ED1：event-driven core 最小闭环（USER_INPUT + TRIGGER + TOOL_CALL + SEND_OUTPUT），所有执行仍落到 Orchestrator/Executor；kill：出现重复触发导致非幂等副作用，或 trace/evidence 不可回放。
  - Spike-GT1：最小 Golden Trace（3 条 GT）：replay-mode 0 副作用、double gating 必须同时满足、unknown policy_context keys 远程 payload 保留；kill：任一 GT 不稳定（flaky）或无法在本地 deterministic 重放。
  - Spike-PLUG0（可选）：仅 Transport plugin（CLI/WS），禁止插件改写 policy_context/replay/gates；kill：出现绕过 PEP 的路径或 policy 不一致。
acceptance:
- 该输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_remote_api.md`
- THREAD-016 三件套存在：
  - `docs/journal/2026-02-24-expert-collab-thread-016.md`
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
confidence: `medium`

