# MVP 交付定义（MVP Deliverables）

本规范定义 AgentOS Next 的最小可交付系统（MVP），用于阶段性验收与回归测试。

## 1. 内核（Kernel）

- 系统 MUST 提供可重复运行的执行入口（runner），能够加载并运行一个技能包（skill package）。
- 系统 MUST 为每次运行生成：
  - 证据（evidence）落盘（file-backed）
  - 追踪（trace）落盘（JSONL）
- 系统 MUST 在 `risk_level` 为 `high|critical` 时要求人类批准（HITL, human-in-the-loop），否则 fail-closed。

## 2. 签名与可信执行（Signing + Trusted Execution）

- 系统 MUST 支持技能包清单签名与验证（ASVP: AgentOS Signed Verification Package）。
- 当启用 ASVP 验证时：
  - 系统 MUST 验证 `manifest.json` 中列出的每个文件哈希（integrity）。
  - 系统 MUST 验证 `signature.sig` 与 `signer_id` 对应公钥（authenticity）。
  - 验证失败 MUST 拒绝执行（fail-closed）。

## 3. 远程模型调用（Remote LLM Calls）

- 系统 MUST 默认禁止任何远程模型调用（fail-closed）。
- 系统 MUST 实现双开关（double gating）：
  - `remote_calls_armed=true`
  - `allow_network_egress=true`
- 任一开关未开启时，系统 MUST 返回稳定错误码（stable error code），并且 MUST 不发起网络请求。

## 4. 个人助理 Demo（Personal Assistant Demo）

- 仓库 MUST 内置一个可验证签名的 demo 技能包：
  - `examples/skills/personal_assistant_brief/`
  - `examples/keys/demo.pub`
- 系统 MUST 提供一个 demo 运行命令，走同一条技能包执行链路，并输出稳定 JSON（machine-readable）。

## 5. 验收（Acceptance）

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` MUST 通过。
- demo 命令 MUST 在无网络、无 token 的默认环境下可运行（使用 `local_mock` 后端）。

