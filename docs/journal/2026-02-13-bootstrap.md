# 2026-02-13 启动：Docs-First 与混合执行方向

## 结论

- 仓库采用 docs-first：Specs 定义语义真相，ADRs 记录关键权衡，Journal 记录协作过程。
- 语言策略：中文为主，关键术语附英文对照，并纳入 `docs/glossary.md`。
- AgentOS 终局采用混合执行（Hybrid Execution）：本机执行、纯远端执行、远端能力扩展三种模式都支持。

## 关键默认选择（可被 ADR 覆盖）

- 路由：策略引擎自动选择 + 用户可覆盖。
- 第三方技能默认云端沙箱执行；本地第三方执行优先 WASM/WASI 隔离。
- Evidence/Trace 真相源默认本地，云端可选端侧加密同步。

## 待办

- 将“不可逆设计点”落为首批 ADR 与 Specs（见 `docs/adrs/` 与 `docs/specs/`）。
- 接入 Codex OAuth 模式的模型调用，并用“远程调用双闸门”降低误触发成本（见 ADR-0007）。
