# ADR-0004 本地第三方默认 WASM/WASI 沙箱（WASM/WASI Local Sandbox）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/SANDBOXING.md`、`docs/specs/SKILL_CONTRACT.md`

## 背景（Context）

签名（ASVP）只能证明来源，不能保证安全执行。第三方技能若在本地运行，必须有强隔离底座。

## 决策（Decision）

- 本地第三方技能默认以 WASM/WASI 作为隔离执行底座（Local Sandbox）。
- 对需要更高权限的能力，必须走受控的工具接口（Tool API），而不是放开本地系统调用。

## 备选方案（Alternatives）

1. 容器/轻虚拟化：
   - 隔离强，但端上分发与性能/体验成本高。
2. 受限脚本进程：
   - 实现快，但安全边界弱，后期高概率推倒重来。

## 取舍（Tradeoffs）

- WASM/WASI 生态建设需要时间，但最符合“可分发、可验证、可隔离”的 OS 级目标。

## 后果（Consequences）

- Skill contract 需要声明是否支持 WASM 目标与所需能力（capabilities）。

## 风险与缓解（Risks & Mitigations）

- 风险：WASI 能力不覆盖某些真实场景。
- 缓解：通过受控 Tool API 扩展能力，并将高风险动作强制远端执行或审批。

## 可观测与验收（Metrics & Acceptance）

- 本地运行的第三方技能无法直接访问明文 secrets、任意网络与任意文件路径。

## 后续工作（Follow-ups）

- 在 `SANDBOXING.md` 定义默认 allowlist 与 egress 规则。

