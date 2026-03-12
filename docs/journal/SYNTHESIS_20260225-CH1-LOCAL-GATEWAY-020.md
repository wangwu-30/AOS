# SYNTHESIS: CH1 Local Gateway（HTTP-only + stateless-by-trace）

- `thread_id`: `20260225-CH1-LOCAL-GATEWAY-020`
- `updated_at`: `2026-02-25`
- `status`: `resolved`

## 综合结论

- CH1 采用最小返工路径：single-core + thin transport。
  - 共用 `ChannelGatewayService` 作为输入映射与执行核心。
  - `channel-stdio` 与 `channel-http` 复用同一执行语义，避免 contract drift。
- host 已批准 A/A/A：
  - A：P0 仅 HTTP-only。
  - A：P0 会话模型 stateless-by-trace。
  - A：P0 最小门禁（`auth=none@localhost`，`rate_limit=off`）。
- 请求侧 `policy_context` 视为不可信；治理键由服务端覆盖，避免越权开启远程/egress/HITL。

## 关键分歧收敛

- ext_claude 与 ext_gpt5_2 在 CH1 R2 已达一致：字段最小化、non-breaking、P0 先不引入 token/rate-limit。
- 幂等与回放守门保持既有链路：通过 Orchestrator idempotency 与 replay gate，避免重复副作用与远程旁路。

## Gate（通过条件）

1. HTTP 响应键集合与 `channel-stdio` 一致。
2. 输入错误返回稳定 JSON（无 traceback）。
3. `policy_context["model"]` 可透传，治理键不可由请求端开启。
4. replay-mode 下远程副作用被阻断。
5. ExecuteRequest 顶层字段稳定（policy_context only）。

## 验收锚点

- `tests/test_spike_ch1_local_gateway.py`
- `tests/test_spike_oc1_channel_stdio.py`
- `docs/specs/MVP_020_LOCAL_GATEWAY_CHANNEL.md`
