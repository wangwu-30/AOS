id: `20260225-ext_claude-react-bc-round1-001`
author: `ext_claude`
topic: `THREAD-023 Round 1：产品视角 - HITL 分级与 open mode 用户体验`
position:
- 基于背景收敛，给出产品视角 stance：
- A. ReAct 动作契约：**接受 6 动作增强集 + open mode**。建议 open mode 默认关闭（安全优先），用户可选开启。
- B. 递归拆解边界：接受 depth=3 默认值；建议预算门为 step<=20 或 time<=60s（哪个先到）；循环检测阈值建议连续 3 次相同 action 触发。
- C. HITL 分级：**建议 2 级制**
  - 高风险动作（强制 HITL）：`delete`、`execute_shell`、`send_message`、`modify_file`
  - 低风险动作（自动执行）：`search`、`read`、`write_draft`、`summarize`
  - 错误码映射：`E_HITL_REQUIRED` = 高风险动作待审批，`E_APPROVED` = 已批准执行
- D. B/C 融合接口：**确认不新增 ExecuteRequest 顶层字段**，policy_context.memory_context 承载即可。
- open mode 用户体验：
  - 关闭时：所有动作自动执行（除高风险）
  - 开启时：用户可实时审批每一步（类似 ChatGPT4 Canvas）
  - 建议提供"会话级"和"全局"两种开关
evidence:
- THREAD-015/016/019/020/022 成果
- docs/specs/MVP_011_ASSISTANT_LOOP.md
- docs/specs/MVP_014_DIALOG_STATE_MACHINE.md
tradeoffs:
- HITL 2级 vs 3级：
  - 2级：简单、用户理解成本低
  - 3级：更精细但复杂度上升
  - 建议：2级起步，后续可扩展
- open mode 会话级 vs 全局：
  - 会话级：灵活但用户需每次设置
  - 全局：省事但风险更高
  - 建议：默认全局关闭，会话级可覆盖
open_questions:
- 高风险动作清单是否需要动态扩展（用户可配置）？
- open mode 下是否有"批量审批"功能需求？
proposal:
- Spike-ReAct1（P0）：
  - 6 动作：search/read/write/delete/execute/summarize
  - 默认 depth=3，预算门 step<=20/time<=60s
  - 循环检测：连续3次相同 action 触发
- Spike-HITL1（P0）：
  - 2级分类：高风险（强制 HITL）/ 低风险（自动）
  - 高风险清单：delete, execute_shell, send_message, modify_file
- Spike-OpenMode1（P1）：
  - 会话级/全局开关
  - 实时审批 UI
acceptance:
- ReAct 动作契约接受 ✅
- HITL 2级制可落地 ✅
- policy_context 承载 B/C 接口确认 ✅
- open mode 用户体验有清晰口径 ✅
confidence: `high`
