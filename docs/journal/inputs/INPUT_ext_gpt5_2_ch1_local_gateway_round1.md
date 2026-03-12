id: `20260225-ext_gpt5_2-ch1-001`
author: `ext_gpt5_2`
topic: `CH1（Local Gateway Channels）Round-1：Remote/API 守门评审（payload/contract/policy_context/error_code）`
position:
- 传输形态（Transport）：P0 选 HTTP-only（request/response JSON），WS-only/HTTP+WS 都推迟到 P1；若未来需要流式（streaming），优先考虑在 HTTP 上用 SSE（Server-Sent Events）做 bounded spike，而不是立刻引入 WS（降低状态复杂度与回放难度）。
- 会话模型（Session Model）：P0 选 trace 驱动的无状态（stateless-by-trace）：
  - client 每次请求可携带 `trace_id`（用于多轮关联）；server 不维护会话缓存（避免 daemon session cache 漂移）。
  - 允许 server 在缺省时生成 `trace_id/turn_id/span_id`，但必须把它们返回给 client（便于下一轮携带）。
- 输出契约（Output Contract）：CH1 的 HTTP 响应 JSON 必须对齐 `mvp channel-stdio` 的稳定输出键集合与语义（至少包含）：
  - `ok,status,error_code,trace_id,turn_id,span_id,evidence_refs,artifact_refs`
  - 错误路径也必须返回稳定 JSON（不得 traceback 泄漏）。
- 输入 payload（Request Shape）：建议 `POST /v1/channel/messages` JSON body（最小）：
  - `message` (string) 或 `input` (object) 二选一（与 `_parse_channel_line` 一致）
  - 可选：`idempotency_key` (string), `trace_id` (string), `workspace_id` (string), `skill_ref` (string), `preferred_target` (auto|local|remote), `policy_context` (object)
  - `policy_context` 允许未知键透传（forward-compatible），但必须被视为“不可信输入”，治理键（replay/remote_calls_armed/allow_network_egress/approved_by_human）要么由 server 显式覆盖，要么通过统一 PEP 校验后再使用（推荐覆盖默认 false）。
- policy_context 边界（Policy Boundary）：必须保持“不新增 ExecuteRequest 顶层字段（top-level API stable）”，扩展一律走 `policy_context`；并且 fail-closed/double-gating/replay-mode 语义不得降级。
- 错误码（Error Codes）：优先复用既有错误码语义，避免新增同义码：
  - 输入解析/校验失败：`E_BAD_CHANNEL_INPUT` 或 `E_INPUT_SCHEMA`
  - 执行链路失败兜底：`E_EXECUTION_FAILED`
  - 其余沿用 `ExecuteResult.error_code`（例如 `E_TIMEOUT`, `E_HITL_REQUIRED`, `E_REPLAY_REMOTE_DISABLED` 等）
evidence:
- `src/agentos_next/cli.py`（`cmd_mvp_channel_stdio`：将 message->ExecuteRequest，并输出稳定 JSON；policy_context 键集合与默认值）
- `tests/test_spike_oc1_channel_stdio.py`（channel-stdio 行为与 model override 透传）
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`（明确 channel-stdio 输出契约必须保持稳定）
- `src/agentos_next/kernel/executor.py`（ExecuteRequest 顶层字段集合，作为“不得扩张”的守门依据）
- `src/agentos_next/kernel/orchestrator.py`（幂等缓存：idempotency_key/workspace_id -> ExecuteResult）
- `src/agentos_next/runtime/local_executor.py`（policy_context -> PackageRunRequest 的关键治理键映射）
- 命令：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前基线 82/82 OK；CH1 引入后必须保持全绿）
tradeoffs:
- HTTP-only（P0）：
  - 收益：最小依赖（stdlib 可实现）、易测、易回放；错误路径更容易 fail-closed。
  - 成本/风险：缺少 WS/流式体验；但可以用 SSE/分段轮询作为 P1 前的过渡。
- stateless-by-trace（P0）：
  - 收益：不引入 daemon session cache，降低双路径漂移；更符合“请求即证据（evidence-by-default）”。
  - 成本：client 需要保存/回传 trace_id；但这正是可审计交互所需的显式关联键。
- auth/rate-limit（P0）：
  - 收益：更安全；降低本机被其他进程滥用风险。
  - 成本：引入新配置与新错误码；可能拖慢 P0 交付。建议默认 bind `127.0.0.1` 且 auth=none，P1 再强化或做 bounded spike（或仅在 listen 非 loopback 时强制 token）。
open_questions:
- 是否需要在 P0 直接引入 token（local token auth）？若 host 选择加速交付，可先 none（bind localhost）并在 spec 标注 bounded spike（CH1-auth）与 kill criteria（任何非本机监听必须 token）。
proposal:
- 方案裁决建议（供 host / ext_gpt5_3 直接写入 DECISIONS）：
  - Decision001（Transport）：选 A（HTTP-only）
  - Decision002（Session Model）：选 A（stateless-by-trace）
  - Decision003（Gates）：选 A（auth=none, rate_limit=off），并增加安全约束：仅监听 `127.0.0.1`；若未来需要非本机监听，必须先做 bounded spike + token gate。
- 测试建议（最小矩阵，<=5）：
  1) happy path：POST message -> 返回稳定 JSON，且 traces/<trace_id>.jsonl 存在
  2) invalid JSON/body：400 + 稳定 error JSON（`E_BAD_CHANNEL_INPUT`）
  3) model override 透传：`policy_context["model"]` 生效（可 mock backend.complete_json）
  4) idempotency：同 idempotency_key 重复请求不产生重复 trace/evidence（或返回同 ExecuteResult）
  5) replay-mode：`policy_context["replay_mode"]=true` 时不得触发任何远程副作用（可复用现有 replay gate 测试策略）
- kill criteria（任一触发即回退 CH1）：
  - 触碰 `ExecuteRequest` 顶层字段；
  - 任一错误路径出现 traceback（未转为稳定 JSON + error_code）；
  - replay-mode 下出现任何新增副作用（写盘/远程/不可回放）。
acceptance:
- THREAD-020 三件套存在且通过 admission（thread/synthesis/decisions）。
- `tests/test_spike_ch1_local_gateway.py`（或等价命名）覆盖上述最小矩阵并全绿。
- 全量回归保持全绿：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 明确验证 non-negotiables：
  - `src/agentos_next/kernel/executor.py` 未扩张；
  - response JSON 对齐 channel-stdio 输出键集合；
  - policy_context 扩展保持 forward-compatible。
confidence: `high`

