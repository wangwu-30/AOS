# ADR-0005 第三方技能默认云端沙箱执行（Default Remote Sandbox for 3rd-Party Skills）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/SANDBOXING.md`、`docs/specs/HYBRID_ROUTING.md`、`docs/specs/SECRETS_BROKER.md`

## 背景（Context）

第三方技能生态需要强隔离、可审计、可结算与可治理。将第三方代码默认放在云端沙箱执行，可显著降低端侧供应链风险。

## 决策（Decision）

- 第三方技能默认在云端沙箱执行（Remote/Cloud Sandbox）。
- 端侧仅允许少量“可信内置工具”（Trusted Built-in Tools）访问设备与隐私数据，并受策略强制。

## 备选方案（Alternatives）

1. 默认本地执行：
   - 隐私更强，但供应链与隔离难度更大。
2. 按技能声明自由选择：
   - 灵活，但治理复杂度更高，MVP 不宜。

## 取舍（Tradeoffs）

- 云端默认执行需要网络依赖与延迟管理，但更利于隔离、审计与商业化闭环。

## 后果（Consequences）

- 必须定义云端沙箱的 egress、资源配额与审计语义。

## 风险与缓解（Risks & Mitigations）

- 风险：云端执行触及隐私合规。
- 缓解：默认端侧加密同步，远端只接触最小必要数据；高敏数据要求用户明确授权与可撤销。

## 可观测与验收（Metrics & Acceptance）

- 云端沙箱执行的每次调用必须写 evidence，并可与本地 trace 串联。

## 后续工作（Follow-ups）

- 定义“可信内置工具”集合与权限边界。

