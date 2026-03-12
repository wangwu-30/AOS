# ADR-0003 证据真相源：本地为主 + 端侧加密同步（Local Truth + Client-Side Encrypted Sync）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/EVIDENCE_TRACE.md`、`docs/specs/VERSIONING_COMPAT.md`

## 背景（Context）

AgentOS 需要 Evidence/Trace 支撑回放、仲裁、复盘与回归测试，但默认也要满足消费级隐私与本地优先。

## 决策（Decision）

- Evidence/Trace 的真相源（source of truth）默认在本地。
- 云端同步默认采用端侧加密同步（Client-Side Encrypted Sync）：云端仅存密文与必要的索引元数据。

## 备选方案（Alternatives）

1. 云端明文为真相源：
   - 易检索与观测，但隐私门槛高。
2. 完全不同步：
   - 隐私最好，但跨设备/仲裁/结算能力受限。
3. 双写强一致：
   - 复杂度过高，MVP 不划算。

## 取舍（Tradeoffs）

- 端侧加密同步需要额外密钥管理与索引设计，但可显著降低云端信任负担。

## 后果（Consequences）

- Evidence schema 必须版本化，且同步包必须可迁移。

## 风险与缓解（Risks & Mitigations）

- 风险：加密导致云端难以做语义检索与调试。
- 缓解：允许选择性上传脱敏摘要（需明确 consent），以及本地可导出审计包。

## 可观测与验收（Metrics & Acceptance）

- 回放（Replay）在无云端依赖时可完成。
- 同步失败不影响本地真相与回放能力。

## 后续工作（Follow-ups）

- 定义 evidence 对象模型、内容寻址 ref 与索引元数据最小集。

