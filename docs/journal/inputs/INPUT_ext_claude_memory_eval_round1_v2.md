id: `20260225-ext_claude-memory-eval-round1-v2-001`
author: `ext_claude`
topic: `THREAD-022 Round 1 v2：基于开源数据集的评测方案升级`
position:
- 基于开源调研，更新评测方案，引入已有 benchmark 而非自建样本。
- 原有 10 条自建样本保留作为"边界用例"，核心评测基于开源数据集。
updated_proposal:
- 评测数据集选择：
  - **Primary**: MultiWOZ（意图识别 + 槽位填充）- 适合评估"意图理解准确性"
  - **Secondary**: Schema-Guided Dialogue（SGD）- 多领域对话状态追踪
  - **Boundary**: 自建 10 条边界用例（模糊表达/纠错/否定等）- 覆盖开源数据集未覆盖的边界场景
- 评测指标保持不变：
  1. Relevant@1：首条命中是否真正相关
  2. ConflictRate：是否引用了与当前意图冲突的旧记忆
  3. ContextFaithfulness：回答是否忠实使用检索链证据（可回放）
  4. OverRecallRate：召回过多导致理解偏移的比例
  5. UserCorrectionRate：用户需要纠正"你理解错了"的比例
- 评测方法：
  - 对 MultiWOZ/SGD 的每轮对话，提取用户意图 + 关键槽位
  - 用 memory.search 检索相关记忆
  - 计算 Relevant@1 / ConflictRate 等指标
  - 边界用例单独评估
evidence:
- MultiWOZ: https://github.com/budzianowski/MultiWOZ
- Schema-Guided Dialogue: https://github.com/google-research-datasets/schema-guided-dialogue
- HalluDial (对话幻觉): https://github.com/FlagOpen/FlagEval
- RAGAS (评测框架): https://github.com/explodinggradients/ragas
tradeoffs:
- 优点：已有标注数据、可对比、可复现
- 局限：开源数据集多为英文、需要翻译或适配中文场景
- 边界用例：补充开源数据集未覆盖的场景（模糊指代、纠错等）
open_questions:
- 是否需要中文评测集（中文对话理解）？
- 是否接入自动化评测框架？
proposal RAGAS :
- 评测矩阵：
  - 数据集 1: MultiWOZ（意图识别评估）
  - 数据集 2: Schema-Guided Dialogue（多领域状态追踪）
  - 边界用例: 10条自建样本
- 实验设计：
  - Baseline-A: file-backed + naive search
  - Baseline-B: ai-tutor pattern 增强
  - Baseline-C: OpenViking adapter
- 输出：5 指标对比表
acceptance:
- 评测方案基于开源数据集，可复现
- 保留边界用例补充
- 可进入 harness 设计阶段
confidence: `high`
