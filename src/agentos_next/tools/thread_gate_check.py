from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "1.0.0"

REQUIRED_MESSAGE_CONTRACT_FIELDS = {
    "id",
    "author",
    "topic",
    "position",
    "evidence",
    "tradeoffs",
    "open_questions",
    "proposal",
    "acceptance",
    "confidence",
}

ALLOWED_CONFIDENCE = {"low", "medium", "high"}

# v1 fixed tokens (literal match) to avoid doc wording drift.
NON_NEGOTIABLE_TOKENS = [
    "top_level_api_stable",
    "fail_closed",
    "replay_mode_no_side_effects",
]


@dataclass(frozen=True)
class GateItem:
    code: str
    message: str
    path: Optional[str] = None
    hint: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "hint": self.hint,
        }


def _unwrap_md_scalar(value: str) -> str:
    s = str(value or "").strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def _project_root_from_journal_dir(journal_dir: Path) -> Path:
    # Expect: <root>/docs/journal
    jd = journal_dir.resolve()
    if jd.name == "journal" and jd.parent.name == "docs":
        return jd.parent.parent
    # Fallback: treat the given journal_dir as root-ish and hope for the best.
    return jd.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_thread_meta(thread_text: str, *, thread_path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key in ("thread_id", "status", "updated_at", "owner"):
        m = re.search(rf"^\s*-\s*`{re.escape(key)}`\s*:\s*`([^`]+)`\s*$", thread_text, re.M)
        if m:
            meta[key] = m.group(1)
    return meta


def _extract_backticked_paths(md_text: str) -> list[str]:
    # Extract paths from markdown backticks. Keep conservative: no nested backticks.
    return re.findall(r"`([^`]+)`", md_text)


def _split_message_blocks(md_text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    cur: dict[str, str] = {}

    for raw in md_text.splitlines():
        line = raw.rstrip("\n")
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1)
        value = m.group(2).strip()
        if key == "id" and cur:
            blocks.append(cur)
            cur = {}
        cur[key] = value

    if cur:
        blocks.append(cur)
    return blocks


def _input_satisfies_message_contract(path: Path) -> tuple[bool, Optional[str]]:
    try:
        text = _read_text(path)
    except Exception as e:
        return False, f"cannot read input file: {e}"

    blocks = _split_message_blocks(text)
    if not blocks:
        return False, "no message blocks found (missing `id:` etc)"

    for fields in blocks:
        missing = REQUIRED_MESSAGE_CONTRACT_FIELDS - set(fields.keys())
        if missing:
            continue
        conf_raw = fields.get("confidence", "")
        conf = _unwrap_md_scalar(conf_raw)
        if conf not in ALLOWED_CONFIDENCE:
            continue
        return True, None

    # Provide the most informative violation from the first block.
    first = blocks[0]
    missing = sorted(REQUIRED_MESSAGE_CONTRACT_FIELDS - set(first.keys()))
    if missing:
        return False, f"missing fields: {missing}"
    conf = _unwrap_md_scalar(first.get("confidence", ""))
    return False, f"invalid confidence: {conf!r}"


def _has_cross_review_ref(input_paths: list[str]) -> bool:
    for p in input_paths:
        name = Path(p).name
        if "_round2_" in name or "_cross_review" in name:
            return True
    return False


def _contains_any_unittest_cmd(decisions_text: str) -> bool:
    t = decisions_text
    return ("python3 -m unittest" in t) or ("python -m unittest" in t) or ("PYTHONPATH=src python3 -m unittest" in t)


def _run_checks_for_thread(
    *,
    project_root: Path,
    journal_dir: Path,
    thread_path: Path,
) -> dict[str, Any]:
    errors: list[GateItem] = []
    warnings: list[GateItem] = []
    checks: list[dict[str, Any]] = []

    def _add_check(check_id: str, ok: bool, detail: dict[str, Any]) -> None:
        checks.append({"check_id": check_id, "ok": bool(ok), "detail": detail})

    thread_text = _read_text(thread_path)
    meta = _parse_thread_meta(thread_text, thread_path=thread_path)
    tid = meta.get("thread_id") or ""
    status = meta.get("status") or ""

    # check_thread_metadata_keys
    missing_meta = [k for k in ("thread_id", "status", "updated_at", "owner") if k not in meta]
    ok_meta = not missing_meta
    _add_check("check_thread_metadata_keys", ok_meta, {"missing": missing_meta})
    if not ok_meta:
        errors.append(
            GateItem(
                code="E_PROTOCOL_SCHEMA_INVALID",
                message=f"thread file missing required metadata keys: {missing_meta}",
                path=str(thread_path),
                hint="Add the missing `thread_id/status/updated_at/owner` metadata lines.",
            )
        )

    # check_thread_triplet_exists
    synthesis = journal_dir / f"SYNTHESIS_{tid}.md"
    decisions = journal_dir / f"DECISIONS_{tid}.md"
    ok_triplet = bool(tid) and synthesis.exists() and decisions.exists()
    _add_check(
        "check_thread_triplet_exists",
        ok_triplet,
        {
            "thread_id": tid,
            "synthesis_exists": synthesis.exists(),
            "decisions_exists": decisions.exists(),
        },
    )
    if not ok_triplet:
        errors.append(
            GateItem(
                code="E_THREAD_FILES_MISSING",
                message="missing synthesis/decisions file for thread",
                path=str(thread_path),
                hint=f"Expected: {synthesis} and {decisions}",
            )
        )
        # Can't proceed with later checks safely.
        return {
            "thread_id": tid or str(thread_path),
            "ok": False,
            "errors": [e.to_json() for e in errors],
            "warnings": [w.to_json() for w in warnings],
            "checks": checks,
        }

    # Resolve referenced input files from backticked paths across the entire thread document.
    backticked = _extract_backticked_paths(thread_text)
    referenced_inputs: list[str] = []
    for p in backticked:
        if not p.endswith(".md"):
            continue
        if "INPUT_" not in p:
            continue
        # Normalize to repo-root-relative path when possible.
        referenced_inputs.append(p)

    # Filter to input files under docs/journal/inputs by default.
    referenced_inputs = [p for p in referenced_inputs if "docs/journal/inputs/INPUT_" in p]
    referenced_inputs = list(dict.fromkeys(referenced_inputs))

    # check_inputs_message_contract_for_referenced_inputs
    bad_inputs: list[dict[str, Any]] = []
    for rel in referenced_inputs:
        ip = (project_root / rel).resolve()
        if not ip.exists():
            bad_inputs.append({"path": rel, "error": "missing file"})
            continue
        ok, err = _input_satisfies_message_contract(ip)
        if not ok:
            bad_inputs.append({"path": rel, "error": err or "invalid"})
    ok_inputs = len(bad_inputs) == 0
    _add_check(
        "check_inputs_message_contract_for_referenced_inputs",
        ok_inputs,
        {"referenced_inputs": referenced_inputs, "invalid": bad_inputs},
    )
    if not ok_inputs:
        errors.append(
            GateItem(
                code="E_PROTOCOL_SCHEMA_INVALID",
                message="referenced INPUT_*.md does not satisfy Message Contract",
                path=str(thread_path),
                hint="Fix the referenced input file(s) to include all Message Contract fields + valid confidence.",
            )
        )

    # check_round2_cross_review_naming_when_round2_or_more
    need_round2 = status in {"round_2_completed", "round_3_completed", "round_4_completed"}
    ok_round2 = (not need_round2) or _has_cross_review_ref(referenced_inputs)
    _add_check(
        "check_round2_cross_review_naming_when_round2_or_more",
        ok_round2,
        {"status": status, "need_round2": need_round2, "referenced_inputs": referenced_inputs},
    )
    if need_round2 and not ok_round2:
        errors.append(
            GateItem(
                code="E_CROSS_REVIEW_MISSING",
                message="missing Round2 cross-review input reference (filename must include _round2_ or _cross_review)",
                path=str(thread_path),
                hint="Add at least one referenced INPUT_*.md with `_round2_` or `_cross_review` in its filename.",
            )
        )

    decisions_text = _read_text(decisions)

    # check_evidence_gate_when_needs_decision_present
    needs_decision = "needs_decision" in decisions_text
    lower = decisions_text.lower()
    ok_evidence_gate = True
    violations: list[str] = []
    if needs_decision:
        if "bounded spike" not in lower:
            violations.append("missing 'bounded spike'")
        if "kill criteria" not in lower:
            violations.append("missing 'kill criteria'")
        if not _contains_any_unittest_cmd(decisions_text):
            violations.append("missing executable acceptance command (python -m unittest)")
        ok_evidence_gate = len(violations) == 0
    _add_check(
        "check_evidence_gate_when_needs_decision_present",
        ok_evidence_gate,
        {"needs_decision": needs_decision, "violations": violations},
    )
    if needs_decision and not ok_evidence_gate:
        errors.append(
            GateItem(
                code="E_BOUNDED_SPIKE_REQUIRED",
                message="needs_decision present but bounded spike evidence gate not satisfied",
                path=str(decisions),
                hint="Add bounded spike + kill criteria + executable acceptance command to DECISIONS.",
            )
        )

    # check_nonnegotiables_tokens_present_in_decisions
    missing_tokens = [t for t in NON_NEGOTIABLE_TOKENS if t not in decisions_text]
    ok_tokens = len(missing_tokens) == 0
    _add_check(
        "check_nonnegotiables_tokens_present_in_decisions",
        ok_tokens,
        {"missing_tokens": missing_tokens},
    )
    if not ok_tokens:
        errors.append(
            GateItem(
                code="E_NONNEGOTIABLES_MISSING",
                message=f"DECISIONS missing non-negotiables token(s): {missing_tokens}",
                path=str(decisions),
                hint="Add the fixed tokens to the DECISIONS file (literal match).",
            )
        )

    return {
        "thread_id": tid,
        "ok": len(errors) == 0,
        "errors": [e.to_json() for e in errors],
        "warnings": [w.to_json() for w in warnings],
        "checks": checks,
    }


def run(argv: Optional[list[str]] = None) -> tuple[int, dict[str, Any]]:
    ap = argparse.ArgumentParser(prog="thread_gate_check", add_help=True)
    ap.add_argument("--thread-id", help="Only check a single thread_id (default: all threads)")
    ap.add_argument("--journal-dir", default="docs/journal", help="Journal dir path (default: docs/journal)")
    args = ap.parse_args(argv)

    journal_dir = Path(args.journal_dir)
    if not journal_dir.exists():
        out = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "summary": {"threads_checked": 0, "errors": 1, "warnings": 0},
            "results": [],
            "errors": [
                GateItem(
                    code="E_TOOL_ERROR",
                    message="journal dir does not exist",
                    path=str(journal_dir),
                    hint="Pass --journal-dir pointing to <root>/docs/journal.",
                ).to_json()
            ],
        }
        return 3, out

    project_root = _project_root_from_journal_dir(journal_dir)
    protocol_doc = project_root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md"
    if not protocol_doc.exists():
        out = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "summary": {"threads_checked": 0, "errors": 1, "warnings": 0},
            "results": [],
            "errors": [
                GateItem(
                    code="E_THREAD_FILES_MISSING",
                    message="missing protocol doc",
                    path=str(protocol_doc),
                    hint="Expected protocol doc at docs/specs/EXPERT_COLLAB_PROTOCOL.md",
                ).to_json()
            ],
        }
        return 2, out

    thread_files = sorted(journal_dir.glob("*-expert-collab-thread-*.md"))
    if not thread_files:
        out = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "summary": {"threads_checked": 0, "errors": 1, "warnings": 0},
            "results": [],
            "errors": [
                GateItem(
                    code="E_THREAD_FILES_MISSING",
                    message="no expert-collab thread file(s) found",
                    path=str(journal_dir),
                    hint="Expected files matching *-expert-collab-thread-*.md",
                ).to_json()
            ],
        }
        return 2, out

    if args.thread_id:
        wanted = str(args.thread_id).strip()
        filtered: list[Path] = []
        for tf in thread_files:
            meta = _parse_thread_meta(_read_text(tf), thread_path=tf)
            if meta.get("thread_id") == wanted:
                filtered.append(tf)
        thread_files = filtered
        if not thread_files:
            out = {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "summary": {"threads_checked": 0, "errors": 1, "warnings": 0},
                "results": [],
                "errors": [
                    GateItem(
                        code="E_THREAD_FILES_MISSING",
                        message="thread_id not found",
                        path=str(journal_dir),
                        hint=f"Unknown thread_id: {wanted}",
                    ).to_json()
                ],
            }
            return 2, out

    results: list[dict[str, Any]] = []
    for tf in thread_files:
        try:
            results.append(_run_checks_for_thread(project_root=project_root, journal_dir=journal_dir, thread_path=tf))
        except Exception as e:
            results.append(
                {
                    "thread_id": tf.name,
                    "ok": False,
                    "errors": [
                        GateItem(
                            code="E_TOOL_ERROR",
                            message=f"exception while checking thread: {e}",
                            path=str(tf),
                            hint="Fix tool bug or thread file parse issue.",
                        ).to_json()
                    ],
                    "warnings": [],
                    "checks": [],
                }
            )

    err_count = sum(len(r.get("errors", []) or []) for r in results)
    warn_count = sum(len(r.get("warnings", []) or []) for r in results)
    ok = all(bool(r.get("ok")) for r in results)

    out = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "summary": {"threads_checked": len(results), "errors": err_count, "warnings": warn_count},
        "results": results,
    }
    return (0 if ok else 2), out


def main() -> None:
    code, out = run()
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()

