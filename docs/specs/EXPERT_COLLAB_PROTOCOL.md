# 外部专家协作协议（Expert Collaboration Protocol）

本规范定义 AgentOS Next 在“多外部专家异步协作（asynchronous multi-expert collaboration）”场景下的最小协议与决策门（Decision Gate），用于确保讨论结果可审计、可复核、可执行。

## 目的（Purpose）

- 团队 MUST 使用统一的文本协议组织外部专家输入，避免仅依赖聊天历史。
- 关键决策 MUST 具备可追踪证据链（evidence chain）与明确验收标准（acceptance criteria）。
- 协议 MUST 支持冲突处理与限界实验（Bounded Spike）机制，避免“无证据拍板”。

## 范围（Scope）

本规范适用于：
- 外部专家对架构（Architecture）/安全（Security）/工程交付（Engineering Delivery）等主题的评审与建议。
- 线程（Thread）级别的提案、交叉评审、综合与裁决。

本规范不包含：
- 具体模型调用实现细节（属于运行时或 LLM Provider 规范）。
- CI 平台具体配置（属于工程实现层）。

## 核心概念（Concepts）

- 外部专家协作协议（Expert Collaboration Protocol）：约束专家输入结构、流程轮次与决策门的规范。
- 协作线程（Collaboration Thread）：围绕单一主题的一组输入、综合与决策文档。
- 证据评分矩阵（Evidence Scoring Matrix）：对候选方案按安全/可验证/成本/速度打分的统一机制。
- 限界实验（Bounded Spike）：在冲突未解时执行的小规模、可终止验证实验。
- 决策门（Decision Gate）：方案进入最终决策前必须满足的阈值与前置条件。

## 接口/数据结构（Interfaces/Data）

### 1) 文件结构（File Layout）

- 协作线程 MUST 使用以下文件：
  - 线程文件：`docs/journal/<date>-expert-collab-thread-<seq>.md`
  - 专家输入：`docs/journal/inputs/INPUT_<expert_id>.md`
  - 综合文件：`docs/journal/SYNTHESIS_<thread_id>.md`
  - 决策文件：`docs/journal/DECISIONS_<thread_id>.md`

### 2) 标识命名（Identifiers）

- `thread_id` MUST 使用：`YYYYMMDD-<TOPIC>-<NNN>`，例如 `20260214-EXT-COLLAB-001`。
- `expert_id` MUST 使用 snake_case 且包含固定别名与模型名（例如 `ext_gpt5_3_codex`）。
- `expert_id` MUST NOT 使用自由变体（如空格、大小写混用、随机缩写）。

### 3) 消息契约（Message Contract）

每条专家输入 MUST 包含以下字段，且字段名必须完全一致：

- `id`
- `author`
- `topic`
- `position`
- `evidence`
- `tradeoffs`
- `open_questions`
- `proposal`
- `acceptance`
- `confidence`

字段默认值（defaults）：
- `open_questions` 默认空列表（`[]`）。
- `confidence` 默认 `medium`，允许值仅为 `low|medium|high`。

## 语义与状态机（Semantics/State Machine）

### 1) 轮次语义（Rounds）

- Round 0（线程设定）：
  - MUST 写明问题、范围、非目标、约束、验收口径。
- Round 1（独立提案）：
  - 每个专家 MUST 提交且仅提交一份当前版本主提案。
- Round 2（交叉评审）：
  - 每个专家 MUST 至少指出他人 1 个最强点与 1 个关键风险。
- Round 3（综合）：
  - 主持者 MUST 将议题标记为 `resolved|needs_decision|blocked_by_missing_evidence`。
- Round 4（裁决）：
  - 人类裁决与最终结论 MUST 落盘到 `DECISIONS_<thread_id>.md`。

### 2) 决策门（Decision Gate）

- 处于 `needs_decision` 的冲突项 MUST 先执行限界实验，再进入最终裁决。
- 限界实验 MUST 在执行前定义 kill criteria（终止条件）。
- 证据评分矩阵默认权重 MUST 为：
  - 安全与治理（Security/Governance）35
  - 可验证性（Verifiability）30
  - 实施成本（Implementation Cost）20
  - 交付速度（Delivery Speed）15
- 方案通过决策门 MUST 同时满足：
  - 总分 `>= 80`
  - 安全与治理分项 `>= 30`

## 错误与重试（Errors/Retry）

错误码定义：

- `E_PROTOCOL_SCHEMA_INVALID`：消息契约字段缺失、字段名不合法或值域不满足约束。
- `E_BOUNDED_SPIKE_REQUIRED`：冲突项未执行限界实验即尝试进入最终裁决。
- `E_DECISION_GATE_NOT_MET`：评分矩阵未达阈值。

重试策略：

- `E_PROTOCOL_SCHEMA_INVALID` SHOULD 通过补齐字段后重试提交。
- `E_BOUNDED_SPIKE_REQUIRED` MUST 在实验完成后重试。
- `E_DECISION_GATE_NOT_MET` MAY 调整方案后重评估，或降级为 `blocked_by_missing_evidence`。

## 安全与隐私（Security/Privacy）

- 协作文档 MUST NOT 写入 token、密钥、私钥、内部连接串等敏感信息（Sensitive Information）。
- 证据引用 SHOULD 优先使用仓库路径与可复现命令，不应粘贴敏感日志原文。
- 任何外部建议涉及远程调用时 MUST 明确 fail-closed 与闸门策略一致性。

## 可观测性（Observability）

- 每个线程 MUST 记录以下可观测字段：
  - `thread_id`
  - `updated_at`
  - 当前轮次与状态
  - 冲突项状态（resolved/needs_decision/blocked_by_missing_evidence）
- 每条最终决策 MUST 关联至少一个可复核证据来源（文件路径或命令结果摘要）。

## 兼容与版本（Compatibility/Versioning）

- 读兼容（read compatibility）：历史线程 MAY 缺少新字段，读取时可标记为 legacy。
- 写兼容（write compatibility）：新建或更新线程 MUST 满足本规范字段与流程要求。
- 若本协议字段集发生变更，MUST 同步更新：
  - `docs/specs/VERSIONING_COMPAT.md`
  - 相关模板/检查脚本（若存在）

## 测试与验收（Tests/Acceptance）

最小验收（MUST）：

- 协议文件存在且包含本模板全部章节。
- 线程文件、输入文件、综合文件、决策文件均存在且命名满足规范。
- 专家输入字段完整性满足 Message Contract。
- 若存在 `needs_decision` 议题，未提供限界实验结果时 MUST 不能进入最终通过决策。

推荐自动化（SHOULD）：

- 在 `tests/test_admission_*.py` 增加文档契约校验（字段、命名、状态流）。
- 在 release evidence pack 中附带本轮协作摘要（thread/synthesis/decisions refs）。
