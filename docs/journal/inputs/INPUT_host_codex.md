id: `20260214-host_codex-001`
author: `host_codex`
topic: `Round 2 交叉评审：协议自动化准入（Admission Test）与协作文档闭环`
position:
- 最强点：将“协作协议合规”纳入 admission tests 是最低成本的 fail-closed 流程约束，能把“文档存在”升级为“流程可执行”，并能作为 release/audit 的可验证证据来源。
- 关键风险：测试若过度强约束（例如强制所有历史 INPUT 都满足最新字段集），会造成误报与维护负担，反过来促使团队绕过流程；因此应从“至少一个合规输入 + 线程/综合/决策成套存在 + 关键元字段可解析”开始，逐步收敛。
evidence:
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`: 定义了 Message Contract 与文件布局。
- `docs/journal/2026-02-14-expert-collab-thread-001.md`: 具备 `thread_id/status/updated_at/owner` 元字段。
- `docs/journal/SYNTHESIS_20260214-EXT-COLLAB-001.md`: 已列出 sources，并标注冲突项状态机。
- `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md`: 已定义 `E_BOUNDED_SPIKE_REQUIRED` 与决策门。
- `tests/test_admission_expert_collab_protocol.py`: 新增协议准入测试作为 bounded spike 的最小实现。
tradeoffs:
- 收益：将协作协议从“约定”提升为“可执行门禁”，降低流程层绕过风险。
- 风险：若未来把校验扩大到语义层状态机（rounds/评分矩阵），可能引入更多变动与维护成本，需要明确 kill criteria。
open_questions:
- 是否在下一迭代把“Round 2 必须存在至少一个交叉评审输入”升级为 MUST（目前仅文档要求，测试不强制）？
- 是否要求 `SYNTHESIS` 中的 `sources` 覆盖所有 INPUT 文件，避免漏引用？
proposal:
- P0（本轮）：引入最小协议准入测试，覆盖协议文件存在、thread/synthesis/decisions 成套、至少一个 INPUT 满足 Message Contract 与 confidence 值域、thread 元字段可解析。
- P1（下轮）：在不破坏读兼容的前提下，逐步增强校验（例如对 `sources` 的引用一致性校验）。
acceptance:
- `tests/test_admission_expert_collab_protocol.py` 在 `PYTHONPATH=src python3 -m unittest discover -s tests -v` 下通过。
- `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md` 字段集合不被修改，且仍满足 Message Contract。
confidence: `high`

