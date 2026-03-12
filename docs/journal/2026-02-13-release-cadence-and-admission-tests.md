# 2026-02-13：迭代节奏与准入测试引入原因

## 结论（Decisions）

- 迭代节奏（cadence）以“可审计的可上线标准（Release Criteria）”为中心组织：
  - 规范先行（specs-first），实现与测试对齐规范。
  - 每次形成发布候选（RC）时，必须能产出最小发布证据包（release evidence pack）。
- 将“可上线标准”拆解为两层：
  - 规范层：`docs/specs/RELEASE_CRITERIA.md` 定义 MUST/SHOULD 的上线门槛。
  - 自动化层：`docs/specs/ADMISSION_TESTS.md` 定义 MUST 阻断门（block release）的准入测试集合。

## 为什么引入准入测试（Why Admission Tests）

动机：把“上线前大家口头确认的事项”变成可重复执行、可回放、可复核的自动化检查，避免在发布窗口才发现关键能力退化。

准入测试重点覆盖以下不可妥协项（non-negotiables）：
- 远程调用默认禁止（fail-closed）与双闸门（double gating）不被回归破坏。
- evidence/trace 必须落盘且结构稳定，支持仲裁与回放（replay）。
- 示例技能包链路可验证（ASVP）且 demo 可在 `local_mock` 下运行，不依赖网络/真实 token。
- 基础脱敏（redaction）要求可被测试覆盖，避免日志/trace 误写入敏感信息（Sensitive Information）或 PII。

## 取舍与后续（Tradeoffs & Follow-ups）

- 取舍：
  - 引入准入测试会增加维护成本（测试需要随协议/落盘结构演进同步更新）。
  - 但换来发布稳定性与可审计性，减少隐性回归导致的运维/发布风险。
- 后续：
  - 将安全门（Security Gates）的输出逐步纳入发布证据包（先人工记录，后自动化落地）。
  - 补齐“常见敏感模式”不落盘的回归用例，并将其纳入准入测试或等价阻断门。

