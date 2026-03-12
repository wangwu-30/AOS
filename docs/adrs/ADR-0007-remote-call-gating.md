# ADR-0007 远程调用双闸门（Remote Call Double-Gating）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-14
- 相关规范（Related Specs）：`docs/specs/LLM_PROVIDER.md`、`docs/specs/OPENAI_OAUTH_CODEX.md`、`docs/specs/SANDBOXING.md`

## 背景（Context）

在 agentos-next 早期迭代中，需要接入真实远程模型调用以降低“后期验证成本”，但同时必须避免：
- 意外的计费与资源消耗
- 在测试/回放（Replay）中误触发真实网络请求
- 在尚未完善治理前过早打开网络出口（egress）

单一开关容易被误用（例如默认值被改、配置被继承、测试环境变量污染）。

## 决策（Decision）

采用“远程调用双闸门（double-gating）”：
- `remote_calls_armed`：显式武装远程调用（Remote Call Arming）
- `allow_network_egress`：显式允许网络出口（Egress Allow）

规则：
- 两者必须（MUST）同时为 `true` 才允许发起真实远程网络请求。
- 缺省配置必须（MUST）fail closed（默认拒绝）。
- 回放（Replay）模式必须（MUST NOT）触发真实远程调用，除非显式开启额外开关并重新通过策略/闸门。

## 备选方案（Alternatives）

1. 单一开关（allow_remote）：
   - 实现简单，但误触发风险更高。
2. 只依赖策略裁决（Policy）：
   - 策略本身也可能被误配置；缺少“人为确认”的显式信号。
3. 每次远程调用都强制 HITL：
   - 安全但迭代效率低；不适合作为默认开发态。

## 取舍（Tradeoffs）

- 双闸门增加配置成本，但显著降低误用风险，适合“慎用远程调用”的团队约束。

## 后果（Consequences）

- Provider 实现需要暴露双闸门输入，并在调用入口强制检查。
- 规范需要明确双闸门语义并在测试中覆盖。

## 风险与缓解（Risks & Mitigations）

- 风险：开发者为省事把两者默认设为 true。
- 缓解：规范明确默认 false；CI 增加测试断言缺省拒绝；文档强调“慎用”。

## 可观测与验收（Metrics & Acceptance）

- 缺省配置下远程调用必然失败，且错误信息可区分是哪一个闸门未打开。
- 回放路径不产生任何网络请求（通过 FakeTransport/网络禁用环境验证）。

## 后续工作（Follow-ups）

- 在后续执行内核中，将双闸门决策写入 `kind=llm_io` evidence 的 `safety_gate` 摘要字段。

