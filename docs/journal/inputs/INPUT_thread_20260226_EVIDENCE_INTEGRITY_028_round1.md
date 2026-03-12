id: `input-20260226-evidence-integrity-028-round1-ext_gpt5_2-001`
author: `ext_gpt5_2`
topic: `THREAD-028 Evidence Integrity v1 (Signed Turn Manifest)`
position:
- Adopt additive signed manifest at `data/evidence/manifests/<trace_id>/<turn_id>.json` + `.sig` (Ed25519 raw base64) to provide tamper detection and non-repudiation.
- Seal **once per turn** via explicit finalize API to avoid multi-span collisions; enforce duplicate generation as fail-closed (`E_EVIDENCE_SIGNATURE_EXISTS`).
- `trace_sha256` is a per-turn slice hash over raw JSONL trace lines where `ctx.turn_id == <turn_id>`.
evidence:
- `src/agentos_next/kernel/evidence_manifest.py`
- `src/agentos_next/kernel/orchestrator.py`
- `src/agentos_next/tools/verify_evidence.py`
- `src/agentos_next/tools/perf_bench.py`
- `tests/test_thread028_evidence_integrity.py`
- Command: `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` (112/112 OK)
tradeoffs:
- Pro: additive (no breaking schema); deterministic verification; tamper detection includes both `meta.sha256` and actual blob hash.
- Con: callers must finalize per turn; duplicate finalize invalidates the signed trace slice (intentional fail-closed detection).
open_questions:
- Should we auto-finalize on `DIALOG_EVENT.TURN_FINISHED` in UI/channel runtimes to reduce footguns? (P1)
proposal:
- Keep Kernel single-writer finalize API (`Orchestrator.finalize_turn_manifest`) and integrate into top-level runtimes incrementally.
- Gate perf via `perf_bench` and keep verify tool stable JSON + exit codes.
acceptance:
- `tests/test_thread028_evidence_integrity.py` passes.
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op sign --count 1000` exits 0 (within frozen thresholds).
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op verify --count 1000` exits 0 (within frozen thresholds).
confidence: `high`

