from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "1.0.0"
MAX_SCAN_BYTES = 1_000_000


@dataclass(frozen=True)
class SecretRule:
    rule_id: str
    pattern: re.Pattern[str]
    message: str


@dataclass(frozen=True)
class SecretFinding:
    rule_id: str
    path: str
    message: str
    line: Optional[int] = None
    excerpt: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "path": self.path,
            "message": self.message,
            "line": self.line,
            "excerpt": self.excerpt,
        }


PATH_RULES = (
    SecretRule(
        rule_id="tracked_env_file",
        pattern=re.compile(r"(^|/)\.env(?:\.[^/]+)?$"),
        message="tracked environment file detected",
    ),
    SecretRule(
        rule_id="tracked_token_json",
        pattern=re.compile(r"(^|/)[^/]*token[^/]*\.json$"),
        message="tracked token json detected",
    ),
    SecretRule(
        rule_id="tracked_client_secret",
        pattern=re.compile(r"(^|/)client_secret\.json$"),
        message="tracked OAuth client secret file detected",
    ),
    SecretRule(
        rule_id="tracked_private_key_file",
        pattern=re.compile(r"(^|/)(?:id_(?:rsa|dsa|ecdsa|ed25519)|[^/]+\.(?:pem|p12|pfx|p8|key))$"),
        message="tracked private key or certificate material detected",
    ),
    SecretRule(
        rule_id="tracked_auth_config",
        pattern=re.compile(r"(^|/)\.(?:netrc|npmrc)$"),
        message="tracked auth config file detected",
    ),
)

CONTENT_RULES = (
    SecretRule(
        rule_id="github_token",
        pattern=re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
        message="possible GitHub token detected",
    ),
    SecretRule(
        rule_id="openai_key",
        pattern=re.compile(r"\bsk-(?:proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}\b"),
        message="possible OpenAI-style API key detected",
    ),
    SecretRule(
        rule_id="aws_access_key",
        pattern=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        message="possible AWS access key detected",
    ),
    SecretRule(
        rule_id="bearer_token",
        pattern=re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
        message="possible bearer token detected",
    ),
    SecretRule(
        rule_id="private_key_block",
        pattern=re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
        message="private key block detected",
    ),
)

RULE_PATH_ALLOWLIST = {
    "private_key_block": {
        "tests/test_admission_redaction.py",
        "tests/test_check_repo_secrets.py",
    },
}


def _git_tracked_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "git ls-files failed")
    raw_items = proc.stdout.split(b"\x00")
    out: list[str] = []
    for item in raw_items:
        if not item:
            continue
        out.append(item.decode("utf-8", errors="strict"))
    return out


def _looks_binary(blob: bytes) -> bool:
    head = blob[:4096]
    return b"\x00" in head


def _redacted_excerpt(line: str, start: int, end: int) -> str:
    prefix = line[max(0, start - 20) : start].strip()
    suffix = line[end : end + 12].strip()
    return f"{prefix}[REDACTED]{suffix}"


def _is_allowlisted(*, rule_id: str, rel_path: str) -> bool:
    allowed = RULE_PATH_ALLOWLIST.get(rule_id)
    return bool(allowed and rel_path in allowed)


def scan_repo(*, repo_root: Path, tracked_files: Optional[list[str]] = None) -> list[SecretFinding]:
    root = repo_root.resolve()
    rel_paths = tracked_files if tracked_files is not None else _git_tracked_files(root)
    findings: list[SecretFinding] = []

    for rel_path in sorted(dict.fromkeys(rel_paths)):
        rel_text = rel_path.replace("\\", "/")
        for rule in PATH_RULES:
            if rule.pattern.search(rel_text):
                findings.append(
                    SecretFinding(
                        rule_id=rule.rule_id,
                        path=rel_text,
                        message=rule.message,
                    )
                )

        abs_path = root / rel_path
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            blob = abs_path.read_bytes()
        except OSError:
            continue
        if len(blob) > MAX_SCAN_BYTES or _looks_binary(blob):
            continue
        text = blob.decode("utf-8", errors="replace")
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            for rule in CONTENT_RULES:
                if _is_allowlisted(rule_id=rule.rule_id, rel_path=rel_text):
                    continue
                match = rule.pattern.search(raw_line)
                if match is None:
                    continue
                findings.append(
                    SecretFinding(
                        rule_id=rule.rule_id,
                        path=rel_text,
                        message=rule.message,
                        line=line_no,
                        excerpt=_redacted_excerpt(raw_line, *match.span()),
                    )
                )
    return findings


def run(argv: Optional[list[str]] = None) -> tuple[int, dict[str, Any]]:
    ap = argparse.ArgumentParser(prog="check_repo_secrets", add_help=True)
    ap.add_argument("--repo-root", default=".", help="Repository root to scan (default: current directory)")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    findings = scan_repo(repo_root=repo_root)
    out = {
        "schema_version": SCHEMA_VERSION,
        "ok": len(findings) == 0,
        "repo_root": str(repo_root),
        "summary": {
            "findings": len(findings),
        },
        "findings": [finding.to_json() for finding in findings],
    }
    return (0 if not findings else 2), out


def main() -> None:
    try:
        code, out = run()
    except SystemExit:
        raise
    except Exception as exc:
        code = 3
        out = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": "E_TOOL_ERROR",
            "message": str(exc),
        }
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
