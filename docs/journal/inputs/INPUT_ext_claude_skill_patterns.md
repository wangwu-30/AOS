id: `20260215-ext_claude-004`
author: `ext_claude`
topic: `Skill 模式：用能力描述替代 Input/Output 界定`
position:
- Host 指出"Skill 模式丰富多样，用 Input/Output 界定不合适"。深表认同。
- Input/Output 只能描述"数据传输"，无法描述：
  - 什么触发 Skill 执行
  - Skill 执行多长时间
  - Skill 是单次执行还是持续运行
  - Skill 是否产生副作用
- 建议从"能力"角度重新定义 Skill，而非"数据结构"
evidence: []
tradeoffs: []
open_questions: []
proposal:
- **Skill 模式分类（按执行特征）**：
  - 触发式（Triggered）：定时器/事件触发，如"每天早上8点发天气"
  - 请求式（Requested）：用户请求触发，如"帮我查天气"
  - 转换式（Transformational）：输入转换输出，如"翻译这段话"
  - 持续式（Continuous）：持续运行，如"对话机器人"
  - 副作用式（Effectful）：产生外部影响，如"发送邮件"

- **Skill 定义重构**：
  ```
  skill:
    capability: "我是什么能力"  # 核心：能做什么
    trigger: "怎么触发我"       # 可选：定时/事件/请求
    lifecycle: "执行模式"       # one_shot / streaming / continuous
    constraints: "约束"         # 超时/成本/权限
    contract: "怎么调用"        # 接口定义（可选）
  ```

- **示例**：
  - 天气查询 Skill：capability=查询天气, trigger=请求, lifecycle=one_shot
  - 对话机器人 Skill：capability=对话, trigger=请求, lifecycle=continuous
  - 定时提醒 Skill：capability=提醒, trigger=定时, lifecycle=continuous
  - 翻译 Skill：capability=翻译, trigger=请求, lifecycle=one_shot
acceptance:
confidence: `medium`
