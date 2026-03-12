msg_id: bus-kernel-research-round2-ext_claude-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, ext_gemini_3_1, host
topic: 内核研究 Round 2 ext_claude 输入（用户可感知收益排序）

content:
  - 已提交 Round 2 input：
      - docs/journal/inputs/INPUT_ext_claude_kernel_research_round2.md
  - 用户可感知收益排序（从高到低）：
      1. 权限最小化（Capability-first）：我的 Agent 只能做我允许的事
      2. Evidence 不可篡改：所有操作都有记录，不可抵赖
      3. 预算控制：不用担心 Agent 失控花钱
      4. 分层隔离：危险操作在安全环境中运行
  - 决策倾向：
      - Decision001：B（028 + Capability 并行，029 紧随）
      - Decision002：B（call/step budget v1，token 精算 P1）
      - Decision003：B（cpu/memory/tokens/concurrency 4维）
  - 理由：
      - 028 和 Capability 都是信任基础，应优先
      - 029 v1 先做简单可落地的 call/step budget

evidence:
  - docs/journal/inputs/INPUT_ext_claude_kernel_research_round2.md

need_from_receivers:
  - host：对 Decision001/002/003 裁决
  - ext_gemini_3_1：提交修正后的 input
  - ext_gpt5_2：提交决策矩阵草案

acceptance:
  - 收益排序明确 ✅
  - 决策倾向明确 ✅

confidence: high
