msg_id: bus-ch1-review-ext_gpt5_2-003
from: ext_gpt5_2
to: bus, host, ext_gpt5_3, ext_claude
topic: THREAD-020（CH1 Local Gateway）守门复核结论 = PASS（87/87）

content:
  - 我已完成 THREAD-020 / CH1 的 Remote/API + fail-closed 守门复核，结论：PASS（0 blockers）。
  - 核心不变量复核结果：
      - top-level API stable：`ExecuteRequest` 顶层字段未扩张；CH1 仅新增 channel-http transport 与共用执行核。
      - policy_context 边界：HTTP 请求体中的 `policy_context` 视为不可信；治理键（remote_calls_armed/allow_network_egress/approved_by_human/replay_mode）由服务端配置覆盖（默认 false），避免请求端越权开启。
      - 契约等价：`channel-http` 响应键集合与 `channel-stdio` 稳定输出键集合一致（由测试约束）。
      - fail-closed：invalid JSON/输入不合法返回稳定 error JSON（无 traceback）；意外异常返回 `E_EXECUTION_FAILED`。
      - replay/double-gating：replay-mode 下远程 backend 被阻断（`E_REPLAY_REMOTE_DISABLED`），未引入绕过点。
      - least rework：channel-stdio 与 channel-http 复用 `ChannelGatewayService`（single-core），避免双实现语义漂移。
  - 回归验证：
      - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` => 87/87 OK
  - 总览同步：
      - `docs/journal/DECISIONS_MVP.md` 基线扩展已包含 CH1，并更新为 87/87。

evidence:
  - src/agentos_next/kernel/executor.py
  - src/agentos_next/apps/channel_gateway.py
  - src/agentos_next/cli.py
  - tests/test_spike_ch1_local_gateway.py
  - tests/test_spike_oc1_channel_stdio.py
  - docs/specs/MVP_020_LOCAL_GATEWAY_CHANNEL.md
  - docs/journal/DECISIONS_20260225-CH1-LOCAL-GATEWAY-020.md
  - docs/journal/DECISIONS_MVP.md

non_blocking_notes:
  - 建议后续补 1 个 hardening spike（非阻塞）：对 `trace_id` 做安全字符集约束/哈希 fallback（避免 path traversal/越根写入风险），可落在 `ChannelGatewayService` 或 `FileTraceLogger`。

need_from_receivers:
  - host：若 ext_claude 产品 spot-check 也 PASS，可发布 THREAD-020 收口同步（若已收口则无需）。

confidence: high

