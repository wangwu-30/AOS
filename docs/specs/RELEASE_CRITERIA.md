# RELEASE_CRITERIA

- 状态（Status）：Draft
- 日期（Date）：2026-03-10
- 相关规范（Related Specs）：
  - `docs/specs/MVP_044_PA_POLLING_MODE.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`

## 目的（Purpose）

定义 AgentOS Next 的统一 runtime 发布门（Release Gate），把“主干回归通过”与“统一 runtime 验证通过”明确区分。

## 发布口径（Release Statements）

- 只有 `pa-polling` 端到端门通过，才可以（MAY）表述：
  - “统一 runtime 验证通过”
- 若仅单元测试、局部回归或非 polling 路径通过，只能（MAY）表述：
  - “主干回归通过”

## 必备门禁（MUST）

1. 全量单元/回归测试通过：
   - `PYTHONPATH=src:tests python3 -m unittest discover -s tests -v`
2. `pa-polling` 发布门通过：
   - `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
3. Playwright 运行时前置条件已满足：
   - `python3 -m pip install playwright`
   - `python3 -m playwright install chromium`
4. Prompt 不得暴露 BrowserUse、Telegram primitive 或 search provider 枚举。
5. EffectiveRuntimeCapabilitiesV1 必须作为唯一能力真相参与 polling 主链。

## 边界条件（Boundary Conditions）

- 发布门不得（MUST NOT）依赖公网真实搜索结果。
- 发布门必须（MUST）使用本地 fixture、mock 或稳定受控 backend。
- 若 Playwright 未安装，相关门必须（MUST）稳定失败，而不是隐式跳过。

## 兼容策略（Compatibility）

- 发布门口径替换旧“只要主干回归通过即可宣称 runtime 统一”的说法。
- 文档中的测试命令必须（MUST）统一使用 `PYTHONPATH=src:tests`。

## 测试与验收（Tests/Acceptance）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
