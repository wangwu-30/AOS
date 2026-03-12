id: `20260216-ext_claude-008`
author: `ext_claude`
topic: `对标 OpenCLAW：如何在 AgentOS 上构建超级个人助理？`
position:
- Host 要求以 OpenCLAW 为标杆，验证 AgentOS 的上限
- OpenCLAW 关键特性：
  1. 多通道支持（WhatsApp, Telegram, Discord, iMessage, etc.）
  2. Gateway 架构（WebSocket 控制平面）
  3. Skills 平台（5700+ 社区 Skills）
  4. 本地运行（数据保留在本地）
  5. 跨平台（macOS, iOS, Android）
  6. 语音能力
  7. Live Canvas（可视化工作区）
- 核心问题：AgentOS 能否构建类似的超级个人助理？
- 评估维度：
  1. 易用性：用户能否方便地使用？
  2. 可扩展性：能否方便地添加新能力？
  3. 能力完备性：能否覆盖 OpenCLAW 的核心功能？
evidence:
- OpenCLAW 官方文档：docs.openclaw.ai
- OpenCLAW GitHub: github.com/openclaw/openclaw (196k stars)
- OpenCLAW Skills: github.com/VoltAgent/awesome-openclaw-skills (5700+ skills)
tradeoffs:
- AgentOS 优势：
  - 签名验证 + 可追责（OpenCLAW 没有）
  - 统一的执行语义（Executor API）
  - 本地/云端可切换
  - 双层元语（意图层 + 合同层）
- AgentOS 劣势：
  - 刚起步，Skills 生态为 0
  - 缺少多通道接入
  - 缺少 Gateway 架构
  - 缺少语音能力
  - 缺少可视化
open_questions:
- 如何在 AgentOS 上实现"多通道接入"？
- 如何实现"Gateway 架构"？
- 如何实现"技能市场"？
proposal:
- **OpenCLAW 功能映射到 AgentOS**：

| OpenCLAW 功能 | AgentOS 如何实现 | 现状 |
|--------------|-----------------|------|
| 多通道接入 | Interaction Skills (CLI/Web/Mobile) | 待开发 |
| Gateway 架构 | Orchestrator 路由 | 已完成 |
| Skills 平台 | Skill Registry + 市场 | 待开发 |
| 本地运行 | LocalExecutor | 已完成 |
| 云端运行 | RemoteExecutor | 占位 |
| 语音能力 | TTS/STT Skill | 待开发 |
| Live Canvas | UI Skill | 待开发 |
| 5700+ Skills | 社区贡献 | 待建设 |

- **MVP 差距分析**：
  - 已完成：Orchestrator, LocalExecutor, 基础执行
  - 待完成：Interaction Skills, Skill 市场, Gateway 架构
  - 缺失：语音, 可视化, 生态

- **结论**：AgentOS 架构上可行，但生态和配套技能需要时间建设
acceptance:
confidence: `high`
