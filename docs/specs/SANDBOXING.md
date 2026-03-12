# 沙箱隔离（Sandboxing）

## 目的（Purpose）

定义本地/云端沙箱的默认隔离边界、资源配额与网络出口（egress）控制，支撑第三方技能生态安全运行。

## 范围（Scope）

涵盖：
- 本地沙箱（WASM/WASI）默认规则
- 云端沙箱默认规则（容器/WASM 皆可）
- egress、文件系统、CPU/内存/时间限制

## 核心概念（Concepts）

见 `docs/glossary.md`：沙箱（Sandbox）、本地沙箱（Local Sandbox）、云端沙箱（Remote Sandbox）。

## 接口/数据结构（Interfaces/Data）

沙箱配置必须（MUST）可被审计并写入 Evidence：
- `fs_allowlist`
- `net_allowlist`
- `cpu_ms_limit`
- `mem_mb_limit`
- `wall_time_ms_limit`

## 语义与状态机（Semantics/State Machine）

- 若沙箱拒绝执行，必须返回 `E_SANDBOX_DENY` 并写 Evidence。

## 错误与重试（Errors/Retry）

- 资源超限必须可区分：超时、内存超限、网络拒绝等。

## 安全与隐私（Security/Privacy）

- 默认禁止任意网络访问，除非合同明确声明并经策略允许。
- secrets 不得以明文进入第三方执行环境（见 `SECRETS_BROKER.md`）。

## 可观测性（Observability）

- 每次执行需记录沙箱策略指纹（policy fingerprint）。

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

- 第三方技能尝试读取本地敏感文件/访问任意网络必须失败并可审计。

