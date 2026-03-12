# DECISIONS: CH1 Local Gateway（P0）

- `thread_id`: `20260225-CH1-LOCAL-GATEWAY-020`
- `updated_at`: `2026-02-25`
- `status`: `accepted`

## Decision 001: P0 传输形态

- **状态**: `accepted`
- **结论**: 接受（A）
  - P0 仅实现 HTTP-only（`POST /v1/channel/messages`）
  - WebSocket/SSE 推迟到 P1 bounded spike

## Decision 002: P0 会话模型

- **状态**: `accepted`
- **结论**: 接受（A）
  - stateless-by-trace（服务端不维护 daemon session cache）
  - 由请求端携带/回收 trace_id

## Decision 003: P0 最小门禁

- **状态**: `accepted`
- **结论**: 接受（A）
  - `auth=none`（仅 loopback）
  - `rate_limit=off`
  - token auth/rate limit 进入后续 bounded spike

## Gate

1. `channel-http` 与 `channel-stdio` 稳定输出键集合语义等价。
2. 请求 `policy_context` 中治理键不得被请求端开启，必须由服务端覆盖。
3. replay/fail-closed/double-gating 不降级（含 `E_REPLAY_REMOTE_DISABLED`）。
4. ExecuteRequest 顶层字段不新增（policy_context only）。

## Acceptance

- `tests/test_spike_ch1_local_gateway.py` 通过
- `tests/test_spike_oc1_channel_stdio.py` 通过
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 线程三件套存在：
  - `docs/journal/2026-02-25-expert-collab-thread-020.md`
  - `docs/journal/SYNTHESIS_20260225-CH1-LOCAL-GATEWAY-020.md`
  - `docs/journal/DECISIONS_20260225-CH1-LOCAL-GATEWAY-020.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

