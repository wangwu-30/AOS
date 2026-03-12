# 2026-02-14 Codex OAuth 模式 LLM 接入（慎用）

## 结论

- 新增了 LLM 调用规范与 OpenAI OAuth（Codex 模式）规范：
  - `docs/specs/LLM_PROVIDER.md`
  - `docs/specs/OPENAI_OAUTH_CODEX.md`
- 实现了 stdlib-only 的 Codex OAuth 调用封装：
  - `src/agentos_next/llm/openai_codex_oauth.py`
- 采用“远程调用双闸门（Remote Call Double-Gating）”降低误用风险：
  - `remote_calls_armed`
  - `allow_network_egress`
  - 见 `docs/adrs/ADR-0007-remote-call-gating.md`

## 约束

- 默认拒绝远程调用（fail closed）。
- token 文件默认路径为 `openai_oauth_token.json`（由 `OPENAI_OAUTH_TOKEN_PATH` 覆盖）。
- 本次实现仅提供调用封装，不在仓库内存放任何 token/密钥文件（见 `.gitignore`）。

