# 2026-02-25 外部专家协作线程 020 (External Expert Collaboration Thread 020)

- `thread_id`: `20260225-CH1-LOCAL-GATEWAY-020`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-25`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

基于 host 对 CH1 的 A/A/A 裁决，落地最小本地网关通道：`channel-stdio` 与 `channel-http` 共享单执行核（single-core + thin transport），并保持 non-negotiables 不降级。

## 范围 (In Scope)

- `mvp channel-http`（`POST /v1/channel/messages`）
- 共用执行核：`ChannelGatewayService`
- 输出契约与 `channel-stdio` 稳定键集合对齐
- policy_context 治理键服务端覆盖
- replay/fail-closed/double-gating 与现有语义保持一致

## 非范围 (Out of Scope)

- WebSocket / SSE
- daemon session cache
- token auth / rate limit（P1 bounded spike）
- ExecuteRequest 顶层字段扩张

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级
- replay-mode 无新增副作用
- ExecuteRequest 顶层字段稳定（policy_context only）
- evidence/trace 可回放

## 轮次进度 (Rounds)

- Round 0: 已完成（立项与边界）
- Round 1: 已完成（ext_claude/ext_gpt5_2 输入）
- Round 2: 已完成（A/A/A 收敛）
- Round 3: 已完成（实现与测试）
- Round 4: 已完成（accepted）

## Evidence (Links)

- `docs/specs/MVP_020_LOCAL_GATEWAY_CHANNEL.md`
- `src/agentos_next/apps/channel_gateway.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_ch1_local_gateway.py`
- `tests/test_spike_oc1_channel_stdio.py`
- `docs/journal/inputs/INPUT_ext_claude_ch1_round1.md`
- `docs/journal/inputs/INPUT_ext_gpt5_2_ch1_local_gateway_round1.md`
- `docs/journal/inputs/INPUT_ext_gpt5_3_ch1_round2_converged.md`
- `docs/journal/SYNTHESIS_20260225-CH1-LOCAL-GATEWAY-020.md`
- `docs/journal/DECISIONS_20260225-CH1-LOCAL-GATEWAY-020.md`
