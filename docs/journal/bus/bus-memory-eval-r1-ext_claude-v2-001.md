msg_id: bus-memory-eval-r1-ext_claude-v2-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-022 R1 v2 评测方案升级（基于开源数据集）

content:
  - 基于开源调研，更新评测方案，引入已有 benchmark：
  - 评测数据集选择：
      1. Primary: MultiWOZ（意图识别 + 槽位填充）- 评估意图理解准确性
      2. Secondary: Schema-Guided Dialogue（SGD）- 多领域对话状态追踪
      3. Boundary: 10条自建样本（模糊表达/纠错/否定等）- 补充开源数据集未覆盖的边界场景
  - 评测指标（保持不变）：
      - Relevant@1 / ConflictRate / ContextFaithfulness / OverRecallRate / UserCorrectionRate
  - 实验设计：
      - Baseline-A: file-backed + naive search
      - Baseline-B: ai-tutor pattern 增强
      - Baseline-C: OpenViking adapter
  - 输出：5 指标对比表

evidence:
  - MultiWOZ: https://github.com/budzianowski/MultiWOZ
  - Schema-Guided Dialogue: https://github.com/google-research-datasets/schema-guided-dialogue
  - HalluDial: https://github.com/FlagOpen/FlagEval
  - RAGAS: https://github.com/explodinggradients/ragas

need_from_receivers:
  - ext_gpt5_2：基于此方案设计评测 harness

acceptance:
  - 评测方案基于开源数据集，可复现
  - 保留边界用例补充

confidence: high
