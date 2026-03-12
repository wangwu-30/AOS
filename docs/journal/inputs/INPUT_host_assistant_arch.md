id: `20260224-host-assistant-arch-001`
author: `host_codex`
topic: `THREAD-016 Round 1：北极星指标（North Star）+ assistant app 参考架构裁决倾向（best-of-breed）`
position:
- 我确认本线程的前提：OpenClaw 作为**能力对标（capability benchmark）**，ai-tutor 作为**应用层架构模式参考（assistant app architecture patterns）**；两者皆不构成对 AgentOS Next Kernel 的“必须照抄”约束。
- 对 3 个决策点的裁决倾向（proposal-ready）：
  - Decision001（runtime 形态）：倾向选 `C) Hybrid`（event-driven minimal core + single-leader/single-writer + direct loop fallback）。
  - Decision002（plugin/hook）：倾向选 `B) P1 再引入`（P0 先用明确模块边界与 adapter 接口）。
  - Decision003（Golden Trace）：倾向选 `A) P0 引入最小 GT`（把可回放/可审计变成门禁，而不是口号）。
- 北极星指标（North Star Metrics）优先级建议：
  - 可验证性（Verifiability）：每个关键闭环都有可执行断言（GT）与稳定 evidence/trace 链路。
  - 治理一致性（Governance Consistency）：replay-mode 零副作用、double gating/HITL 不可绕过、fail-closed 默认拒绝。
  - 漂移控制（Drift Control）：Hybrid 与 direct fallback 的失败路径必须语义等价（error_code/evidence_refs/trace 结构等价）。
evidence:
- THREAD-015 能力 roadmap（D/B/A）：`docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
- ext_gpt5_2 方案：`docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_options.md`
- ext_gpt5_2 Remote/API 守门：`docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_remote_api.md`
- ext_gpt5_3 方案（最小 Hybrid 边界 + kill criteria）：`docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_options.md`
- ext_claude 方案（信任闭环 + fallback）：`docs/journal/inputs/INPUT_ext_claude_assistant_arch.md`
- Remote/API 扩展点：`docs/specs/REMOTE_SANDBOX_API.md`
- Kernel 不变量：`docs/specs/EXECUTOR_API.md`、`docs/specs/EVIDENCE_TRACE.md`
tradeoffs:
- Hybrid（Decision001-C）：
  - 收益：更贴合 daemon/channels/trigger/follow-up 的长期运行语义；事件流更利于审计与回放；保留 direct loop 降低早期不确定性。
  - 成本/风险：事件模型与 single-writer 边界需要定义清晰，否则会引入并发写竞态与重复触发。
- plugin 延后（Decision002-B）：
  - 收益：P0 复杂度更可控，治理面更集中（避免 policy 分叉）。
  - 成本/风险：短期可扩展性稍弱；可用“仅 transport adapter”最小验证缓解。
- Golden Trace P0（Decision003-A）：
  - 收益：把信任闭环做成工程门禁；降低后期排障成本。
  - 成本/风险：需要维护最小 GT 样本与断言；但可控且收益长期复利。
open_questions:
- GT 的最小集合是否锁定为 3 条（HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP_SUCCESS），还是需要加 1 条“失败路径等价（error equivalence）”？
- P0 是否需要固定一个 UI view 导出格式（给前端渲染），还是只要求 UI 从现有 trace/evidence 计算派生？
proposal:
- 若你（human host）认可该裁决倾向，可在 Round 4 直接裁决为 `C/B/A`，并绑定 2 个 bounded spikes：
  - Spike-RT1：Hybrid minimal core + direct fallback（single-writer 语义明确）
  - Spike-GT1：最小 GT + 失败路径等价断言（防漂移 gate）
acceptance:
- 本输入文件存在：`docs/journal/inputs/INPUT_host_assistant_arch.md`
- THREAD-016 三件套存在：
  - `docs/journal/2026-02-24-expert-collab-thread-016.md`
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
- 回归门：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
confidence: `medium`

