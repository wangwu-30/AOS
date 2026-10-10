# AgentOS Next

AgentOS Next 的当前目标不是“更会聊天”，而是一个可开源的查询内核（Query Kernel）与可审计规范（Specs/ADRs）。

当前 canonical 主链：

`Submitter Adapter -> Canonical Task Ingress -> Query-Gated Runtime -> Assistant Loop -> Consumer Adapter`

## 先看什么

1. `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
2. `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
3. `docs/specs/MVP_044_PA_POLLING_MODE.md`
4. `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
5. `docs/adrs/ADR-0011-playwright-runtime-surface-tightening.md`

## 5 分钟跑起来

### 安装

```bash
cd AOS
python3 -m pip install -e ".[dev]"
python3 -m playwright install chromium
```

### 跑测试

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -v
```

### 跑最小 assistant loop

```bash
PYTHONPATH=src python3 -m agentos_next.cli mvp assistant-loop \
  --query "请帮我总结一下今天要做的事" \
  --backend local_mock \
  --no-verify-asvp
```

### 跑 Telegram polling

```bash
PYTHONPATH=src python3 -m agentos_next.cli mvp pa-polling \
  --bot-token "<your-token>" \
  --backend minimax \
  --remote-calls-armed \
  --allow-network-egress \
  --max-cycles 0 \
  --model "codex-MiniMax-M2.5" \
  --memory-context-enabled \
  --memory-context-meta-identity-ref "<ev_meta_identity>" \
  --memory-context-meta-operator-catalog-ref "<ev_meta_operator_catalog>" \
  --budget-slice-remote-llm-calls 9999 \
  --capabilities "fs_read,fs_write,shell_exec,memory_write,memory_search,web_browse,channel_send" \
  --no-verify-asvp
```

MiniMax 远程测试前需要设置：

```bash
export MINIMAX_API_KEY="<your-minimax-key>"
# 中国大陆环境可改成 https://api.minimaxi.com/v1
export MINIMAX_BASE_URL="https://api.minimax.io/v1"
```

## 当前设计要点

- 模型是查询引擎（Query Engine），不是独立客体。
- agent 是约束与编排层（Constraint & Orchestration Layer）。
- 工具（Tool）扩展能力，技能（Skill）沉淀最优/次优求解程序。
- 有效运行时能力（Effective Runtime Capabilities）是唯一能力真相。
- 模型侧不再暴露 BrowserUse、Telegram primitive 或 search provider 选择。
- `web.search` 是纯搜索原语，provider chain 为 `Brave -> DuckDuckGo HTML Search`；`web.browse` 的 canonical backend 才是 Playwright。

## 常用入口

- `src/agentos_next/cli.py`
- `src/agentos_next/apps/canonical_task_ingress.py`
- `src/agentos_next/apps/query_gated_runtime.py`
- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/apps/pa_polling_service.py`

## 发布口径

- 只有 `tests.test_thread044_pa_polling` 通过，才可以表述“统一 runtime 验证通过”。
- 否则只能表述“主干回归通过”。
