# 运维与维护指南（Operations and Maintenance Guides）

本目录存放非规范性文档，用于帮助开发、排障、交接与复盘。这里的文档解释系统如何工作、出现问题时先看哪里、过去修过什么坑；规范性要求仍以 `docs/specs/` 和 `docs/adrs/` 为准。

## 文档索引

- [PA 值班速查卡](/Users/wangwu/codex/agentos-next/docs/guides/PA_ONCALL_QUICK_REFERENCE.md)
  - 面向值班与临时排障的 5 分钟入口，只保留最短定位路径。
- [PA 日志字段说明](/Users/wangwu/codex/agentos-next/docs/guides/PA_LOG_FIELD_REFERENCE.md)
  - 面向排障与值班的日志字典，解释常见日志行、字段含义与典型判断方式。
- [PA 架构总览](/Users/wangwu/codex/agentos-next/docs/guides/PA_ARCHITECTURE_OVERVIEW.md)
  - 面向维护者的端到端链路说明，覆盖 Telegram 入站、canonical runtime、LLM provider、流式回复与持久化落点。
- [PA 排障手册](/Users/wangwu/codex/agentos-next/docs/guides/PA_TROUBLESHOOTING_RUNBOOK.md)
  - 面向值班和本地调试的操作手册，按症状给出定位顺序、证据位置与修复建议。
- [PA 修复经验](/Users/wangwu/codex/agentos-next/docs/guides/PA_REPAIR_NOTES_2026Q1.md)
  - 记录近期真实故障的根因、修复动作与沉淀出的长期规则。
- [项目状态汇报 2026-03-08](/Users/wangwu/codex/agentos-next/docs/guides/PROJECT_STATUS_REPORT_2026-03-08.md)
  - 汇总当前 runtime/context/intent/model routing 的已完成项、差距与下一步。
- [内核共识待办](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_CONSENSUS_BACKLOG.md)
  - 作为“已达成但尚未完全落地”的系统共识 SSOT，用于持续推进而不是散落在聊天里。
- [故障复盘模板](/Users/wangwu/codex/agentos-next/docs/guides/INCIDENT_TEMPLATE.md)
  - 面向后续新增故障条目的统一模板，约束症状、根因、证据、修复与防再发信息。
- [变更记录](/Users/wangwu/codex/agentos-next/CHANGELOG.md)
  - 汇总近期面向用户与维护者可感知的变更。

## 使用边界

- 要看“必须怎么做”，去 `docs/specs/`。
- 要看“为什么这么做”，去 `docs/adrs/`。
- 要看“现在坏了怎么修”，先读本目录。
