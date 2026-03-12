# MVP-018: 自主迭代闭环（Self-Improvement Loop, SI1）

本规范定义 AgentOS Next 的“自主迭代（self-improvement）”最小闭环：在 **不破坏 fail-closed / replay / evidence** 等既有安全与可回放契约前提下，允许系统基于观测数据提出改进方案，并在严格治理下验证与推广（promote）。

## 目的（Purpose）

- 把“持续改进”从临时人工操作升级为 **可审计（auditable）**、**可回放（replayable）**、**可终止（killable）** 的受限流程。
- 明确边界：SI1 不是“自动改代码并上线”，而是一个 **Observe -> Propose -> Validate -> Promote** 的治理管线（governed pipeline）。

## 非协商约束（Non-Negotiables）

- **fail-closed** 不得降级：任何不确定/缺证据/越权 MUST 拒绝并写 evidence。
- **replay-mode** 下不得产生新副作用（no new side effects），不得触发远程执行（remote execution）。
- **ExecuteRequest 顶层字段稳定（top-level API stable）**：SI1 引入的新信息一律通过 `policy_context` 扩展点透传。
- **evidence-by-default**：每个阶段 MUST 产生可寻址 evidence/trace，且可用于复核“为什么这样做”。
- **HITL（Human-in-the-Loop）门禁**：Promote 阶段 MUST 经过人工批准（approved_by_human），否则禁止写入/发布。

## 范围（Scope）

### In Scope

- 定义 SI1 的阶段语义与最小接口：
  - Observe（观测）：从本地 evidence/trace/registry 解析出候选改进点（signals）。
  - Propose（提案）：输出结构化提案（proposal），包含：变更意图、影响面、证据引用、回滚路径。
  - Validate（验证）：在 replay-mode + 本地测试下验证提案不破坏基线。
  - Promote（推广）：在 HITL 通过后，生成可应用的变更包（change bundle），并记录推广证据。
- 定义错误码（error codes）、回滚（rollback）与 kill criteria。

### Out of Scope（MVP 不做）

- 自动合并到主分支（auto-merge）或自动发布到远程市场（marketplace）。
- 远程沙箱（RemoteSandbox）上的自动化验证流水线（后续可扩展）。
- 跨设备/跨工作区的 SI1 状态同步。

## 术语（Terms）

- SI1：Self-Improvement Loop（自主迭代闭环）
- 信号（signal）：从 evidence/trace 中提取的“可改进点”候选。
- 变更包（change bundle）：可应用的补丁或操作集合（patch + metadata）。

## 阶段语义（Stage Semantics）

## 实施顺序（Phases, MVP Delivery Order）

为降低回归风险与越权风险，建议将 SI1 实现拆为两期（phased delivery）：

- Phase-1（本轮，MVP）：实现 **Observe + Propose + Validate**，但 **不落 Promote 写入**（不产生变更包、不触碰仓库关键路径），以验证“证据闭环（evidence loop）+ fail-closed + replay 约束”可落地。
- Phase-2（下轮）：实现 **Promote**，但必须满足 HITL（`approved_by_human==true`）与回滚包要求（bundle + rollback steps + touched paths），否则一律阻断。

### 1) Observe（观测）

输入（inputs）：
- `data_dir` 下的 traces 与 evidence（本地真相源，source of truth local）。
- （可选）registry index（用于定位技能包版本/依赖）。

输出（outputs）：
- `signals.json`：一组结构化信号（例如：失败率升高、错误码分布、重复调用、非幂等迹象等）。
- `evidence_ref`：记录观测来源集合与统计摘要（不写敏感原文）。

### 2) Propose（提案）

输入：
- `signals.json`
- 人工或策略提供的约束（constraints），例如：不得触碰核心契约文件、不得新增顶层字段等。

输出：
- `proposal.json`（结构化提案）：
  - `intent`（意图）
  - `scope`（影响范围）
  - `evidence_refs`（证据引用）
  - `risk`（风险与回滚）
  - `validation_plan`（验证计划）

### 3) Validate（验证）

输入：
- `proposal.json`

必须执行的最小验证（MUST）：
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 若提案涉及 CLI/manifest/evidence/trace：必须追加对应的回归用例或 golden 验证（等价验证）。

输出：
- `validation.json`：
  - `ok: true|false`
  - `failed_gates: [...]`
  - `commands: [...]`（可复核命令与摘要）
  - `evidence_refs: [...]`

### 4) Promote（推广）

前置条件（MUST）：
- `validation.ok == true`
- `policy_context["approved_by_human"] == true`（HITL）

输出：
- `bundle/`：变更包目录（patch + metadata + rollback instructions）
- `promotion.json`：推广记录（包含 bundle digest、提案摘要、证据引用）

禁止项（MUST NOT）：
- 未批准不得写入仓库关键路径（例如 `src/`、`docs/specs/`）。
- 未显式允许不得触发远程调用或网络出站（network egress）。

## 数据与落盘（Data & Persistence）

建议目录结构（可调整，但需保持可审计）：

- `data/si1/runs/<run_id>/`
  - `signals.json`
  - `proposal.json`
  - `validation.json`
  - `promotion.json`
  - `bundle/`（变更包）

`run_id` 字段约束（MUST）：
- 必须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`
- 禁止包含路径分隔符（`/`、`\`）与 `..`
- 非法 `run_id` 必须 fail-closed：
  - Observe 返回 `E_SI1_OBSERVE_FAILED`
  - Propose/Validate 返回 `E_SI1_PROPOSAL_INVALID`

每个阶段都应写 Evidence（kind=routing 或 kind=meta），并在 trace 中写 SI1 事件（event）。

## 错误码（Error Codes）

建议最小集合（MVP）：
- `E_SI1_OBSERVE_FAILED`
- `E_SI1_PROPOSAL_INVALID`
- `E_SI1_VALIDATION_FAILED`
- `E_SI1_HITL_REQUIRED`
- `E_SI1_POLICY_VIOLATION`

## 回滚（Rollback）

- Promote 输出的 `bundle/` MUST 包含：
  - 变更摘要（summary）
  - 回滚步骤（rollback steps）
  - 影响文件列表（touched paths）
- Kill criteria 触发时，MUST 停止推广并保留 evidence/trace 以便复盘。

## Kill Criteria（终止条件）

出现以下任一情况，SI1 MUST 停止并进入 `blocked_by_policy`：

1. 任何阶段尝试绕过 fail-closed / replay-mode 约束。
2. Validate 失败（单测不全绿）或引入非确定性输出导致无法回放。
3. Promote 未获得 HITL 批准仍试图写入/发布。

## 验收（Acceptance）

本规范阶段（spec-only）的最小验收：
- `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md` 存在并包含：
  - 非协商约束、阶段语义、错误码、回滚、kill criteria
- 新协作线程（thread/synthesis/decisions）三件套存在（见专家协作协议）。

后续实现阶段（implementation）的建议验收（供下一轮 thread 使用）：
- 至少 1 条端到端用例（E2E）覆盖 Observe->Propose->Validate（Promote 需 HITL gate）。
- SI1 事件可回放，且 evidence_refs 可寻址、脱敏策略不回归。

## 相关规范（Related Specs）

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `docs/specs/RELEASE_CRITERIA.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/specs/ADMISSION_TESTS.md`
- `docs/specs/VERSIONING_COMPAT.md`
