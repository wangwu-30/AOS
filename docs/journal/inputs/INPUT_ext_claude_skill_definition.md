id: `20260216-ext_claude-006`
author: `ext_claude`
topic: `Skill 的本质：双层元语 + 意图声明`
position:
- Host 提出深刻问题：Skill 无法准确定义，就是一堵无法绕过的墙
- GPT5.3 提出"双层元语"概念，非常有启发：
  1. 意图层（Intent Layer）：用户价值与任务语义
  2. 合同层（Contract Layer）：机器可验证约束
- 单纯"意图声明"不够——还需要可验证约束来支撑 fail-closed、审计、回放
- **最终定义**：
  - Skill = 意图声明 + 可验证合同
  - 意图层：做什么（人类可读）
  - 合同层：怎么做才能通过（机器可验证）
evidence:
- `docs/journal/inputs/INPUT_ext_gpt5_3_skill_essence.md`: GPT5.3 双层元语观点
tradeoffs:
- 纯意图模式：优雅但不可验证
- 纯合同模式：可验证但太硬
- 双层元语：平衡优雅与可验证
open_questions: []
proposal:
- **双层元语定义**：
  - 意图层（Intent Profile）：
    - `intent`: 我能帮助你完成什么
    - `success_criteria`: 成功标准
    - `interaction_mode`: one_shot / streaming / continuous
  - 合同层（Contract Profile）：
    - `inputs_schema`, `outputs_schema`
    - `risk_level`, `acceptance_rules`
    - `network_egress`, `execution_targets`
- **执行规则**：
  - 平台按意图层做路由建议
  - 平台必须按合同层做验证（fail-closed）
- **为什么优雅**：
  - 上层"做什么"与下层"如何验证"解耦
  - 既是人类可读的故事，也是机器可验证的合同
  - 覆盖所有形态：工具/Agent/服务/触发器
acceptance:
confidence: `high`
