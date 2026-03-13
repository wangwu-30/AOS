from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"

_COLLAB_THREAD_ID = "20260214-EXT-COLLAB-001"
_COLLAB_REF_PATHS = [
    # Keep repo-root relative paths for portability and audit.
    "docs/journal/2026-02-14-expert-collab-thread-001.md",
    f"docs/journal/SYNTHESIS_{_COLLAB_THREAD_ID}.md",
    f"docs/journal/DECISIONS_{_COLLAB_THREAD_ID}.md",
    "docs/journal/inputs/INPUT_ext_gpt5_3_codex.md",
    "docs/journal/inputs/INPUT_host_codex.md",
]


def _repo_root() -> Path:
    # src/agentos_next/release/pack.py -> repo root is 3 levels up.
    # Keep deterministic so `python -m agentos_next.cli ...` works from any CWD.
    return Path(__file__).resolve().parents[3]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_commit(root: Path) -> str | None:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    s = (p.stdout or "").strip()
    return s if s else None


def _env_with_pythonpath(src_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src_dir) + (os.pathsep + old if old else "")
    return env


@dataclass(frozen=True)
class _CmdRun:
    argv: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> _CmdRun:
    p = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return _CmdRun(
        argv=list(argv),
        cwd=str(cwd),
        returncode=int(p.returncode),
        stdout=p.stdout or "",
        stderr=p.stderr or "",
    )


def _write_text(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _relpath_posix(root: Path, p: Path) -> str:
    try:
        rel = p.relative_to(root)
    except Exception:
        rel = p
    return rel.as_posix()


def _run_admission_tests(root: Path, env: dict[str, str], out_dir: Path) -> tuple[bool, _CmdRun, Path]:
    unittest_path = out_dir / "unittest.txt"
    unittest_argv = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-v",
        "-p",
        "test_admission_*.py",
    ]
    adm = _run(unittest_argv, cwd=root, env=env)
    _write_text(unittest_path, adm.stdout + ("" if adm.stderr == "" else "\n[stderr]\n" + adm.stderr))
    return (adm.returncode == 0), adm, unittest_path


def _run_assistant_demo_replay(
    *,
    root: Path,
    env: dict[str, str],
    out_dir: Path,
    data_dir: Path,
    demo_query: str,
    backend: str,
) -> tuple[bool, int, str | None, list[str] | None, bool, Path | None, Path]:
    demo_path = out_dir / "demo.json"
    trace_out_path = out_dir / "trace.jsonl"

    demo_argv = [
        sys.executable,
        "-m",
        "agentos_next.cli",
        "mvp",
        "assistant-demo",
        "--query",
        str(demo_query),
        "--data-dir",
        str(data_dir),
        "--backend",
        str(backend),
        "--replay-mode",
    ]
    demo = _run(demo_argv, cwd=root, env=env)
    last = _last_nonempty_line(demo.stdout)

    demo_obj: dict[str, Any] | None = None
    demo_parse_error: str | None = None
    if last is None:
        demo_parse_error = "assistant-demo produced no stdout"
    else:
        try:
            demo_obj = json.loads(last)
        except Exception as e:  # pragma: no cover
            demo_parse_error = f"failed to parse last line as JSON: {e}"

    if demo_obj is None:
        _write_json(
            demo_path,
            {
                "ok": False,
                "error": demo_parse_error,
                "returncode": demo.returncode,
                "last_line": last,
            },
        )
    else:
        _write_json(demo_path, demo_obj)

    demo_ok = (demo.returncode == 0) and bool(demo_obj and demo_obj.get("ok") is True)
    trace_id = demo_obj.get("trace_id") if isinstance(demo_obj, dict) else None

    demo_evidence_refs: list[str] | None = None
    if isinstance(demo_obj, dict) and isinstance(demo_obj.get("evidence_refs"), list):
        demo_evidence_refs = [str(x) for x in demo_obj.get("evidence_refs") if isinstance(x, (str, int, float))]

    trace_copied = False
    trace_src: Path | None = None
    if isinstance(trace_id, str) and trace_id.strip():
        trace_src = data_dir / "traces" / f"{trace_id}.jsonl"
        if trace_src.exists():
            shutil.copyfile(trace_src, trace_out_path)
            trace_copied = True

    return demo_ok, int(demo.returncode), trace_id, demo_evidence_refs, trace_copied, trace_src, demo_path


def _run_mvp_exec_and_write_execute_result(
    *,
    root: Path,
    env: dict[str, str],
    out_dir: Path,
    data_dir: Path,
    demo_query: str,
    backend: str,
) -> tuple[bool, int, Path, _CmdRun]:
    """Run `mvp exec` once and persist the stdout JSON as execute_result.json.

    Decision A: rc-pack should emit an ExecuteResult-shaped JSON file without changing run-package output.
    We intentionally treat the CLI stdout JSON as the contract for this file.
    """
    execute_result_path = out_dir / "execute_result.json"

    # Reuse the repo example package as the stable skill_ref for RC evidence.
    skill_ref = root / "examples" / "skills" / "personal_assistant_brief"
    keys_dir = root / "examples" / "keys"

    # Keep input aligned with the demo query while satisfying inputs_schema.
    input_json = json.dumps({"request": str(demo_query)}, ensure_ascii=False, sort_keys=True)

    exec_argv = [
        sys.executable,
        "-m",
        "agentos_next.cli",
        "mvp",
        "exec",
        "--skill-ref",
        str(skill_ref),
        "--keys-dir",
        str(keys_dir),
        "--verify-asvp",
        "--backend",
        str(backend),
        "--replay-mode",
        "--input",
        input_json,
        "--workspace-id",
        "rc_pack",
        "--data-dir",
        str(data_dir),
    ]
    run = _run(exec_argv, cwd=root, env=env)
    last = _last_nonempty_line(run.stdout)

    exec_obj: dict[str, Any] | None = None
    exec_parse_error: str | None = None
    if last is None:
        exec_parse_error = "mvp exec produced no stdout"
    else:
        try:
            obj = json.loads(last)
            if isinstance(obj, dict):
                exec_obj = obj
            else:
                exec_parse_error = f"mvp exec last line JSON was not an object: {type(obj).__name__}"
        except Exception as e:  # pragma: no cover
            exec_parse_error = f"failed to parse last line as JSON: {e}"

    if exec_obj is None:
        _write_json(
            execute_result_path,
            {
                "ok": False,
                "error": exec_parse_error,
                "returncode": run.returncode,
                "last_line": last,
            },
        )
    else:
        _write_json(execute_result_path, exec_obj)

    exec_ok = (run.returncode == 0) and (exec_obj is not None)
    return exec_ok, int(run.returncode), execute_result_path, run


def _collab_refs(root: Path) -> dict[str, Any]:
    paths: list[dict[str, str]] = []
    for rel in _COLLAB_REF_PATHS:
        p = root / rel
        paths.append({"path": _relpath_posix(root, p), "sha256": _sha256_file(p)})
    return {"thread_id": _COLLAB_THREAD_ID, "paths": paths}


_THREAD_ID_RE = re.compile(r"(?m)^\s*-\s*`thread_id`\s*:\s*`([^`]+)`\s*$")


def _collab_threads(root: Path) -> list[dict[str, Any]]:
    """Collect all expert-collab threads and their SYNTHESIS/DECISIONS artifacts.

    This is additive: rc-pack MUST preserve the existing `collab_refs` contract.
    """

    journal_dir = root / "docs" / "journal"
    thread_files = sorted(journal_dir.glob("*-expert-collab-thread-*.md"))

    threads: list[dict[str, Any]] = []
    for tf in thread_files:
        text = tf.read_text(encoding="utf-8")
        m = _THREAD_ID_RE.search(text)
        if not m:
            # Admission tests enforce thread_id presence; keep best-effort here for robustness.
            continue

        thread_id = m.group(1).strip()
        synthesis = journal_dir / f"SYNTHESIS_{thread_id}.md"
        decisions = journal_dir / f"DECISIONS_{thread_id}.md"

        entry_paths = [tf, synthesis, decisions]
        paths: list[dict[str, str]] = []
        missing: list[str] = []
        for p in entry_paths:
            if not p.exists():
                missing.append(_relpath_posix(root, p))
                continue
            paths.append({"path": _relpath_posix(root, p), "sha256": _sha256_file(p)})

        entry: dict[str, Any] = {"thread_id": thread_id, "paths": paths, "ok": len(missing) == 0}
        if missing:
            entry["missing_paths"] = missing
        threads.append(entry)

    threads.sort(key=lambda x: str(x.get("thread_id") or ""))
    return threads


def _last_nonempty_line(s: str) -> str | None:
    for line in reversed(s.splitlines()):
        if line.strip():
            return line
    return None


def cmd_mvp_release_pack(args: argparse.Namespace) -> int:
    root = _repo_root()
    src_dir = root / "src"
    env = _env_with_pythonpath(src_dir)

    release_id = args.release_id or _new_id("rel")
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else (root / "data" / "releases" / release_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    schema_version = "1.1.0"
    created_at_utc = _utc_now_iso()
    git_commit = _git_commit(root)
    python_version = _platform.python_version()
    platform_str = _platform.platform()

    commands: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    # MVP: record SHOULD-level security gates that are not yet automated.
    waivers: list[dict[str, Any]] = [
        {
            "id": "dependency_vulnerability_scan",
            "status": "not_automated",
            "reason": "MVP: dependency vulnerability scanning not wired into pipeline yet",
            "owner": "TBD",
            "due_date_utc": None,
        },
    ]

    # 1) Admission tests (required gate)
    admission_ok, adm, unittest_path = _run_admission_tests(root, env, out_dir)
    results["admission_ok"] = admission_ok
    results["admission_returncode"] = adm.returncode
    commands.append(
        {
            "name": "admission_tests",
            "argv": adm.argv,
            "cwd": adm.cwd,
            "returncode": adm.returncode,
            "stdout_path": str(unittest_path),
        }
    )

    # 3) Manifest
    manifest = {
        "schema_version": schema_version,
        "pack_kind": "release-pack",
        "release_id": release_id,
        "created_at_utc": created_at_utc,
        "git_commit": git_commit,
        "python_version": python_version,
        "platform": platform_str,
        "commands": commands,
        "results": results,
        "waivers": waivers,
        # Additive audit trail. Admission tests enforce thread/synthesis/decisions existence.
        "collab_threads": _collab_threads(root),
    }
    _write_json(out_dir / "manifest.json", manifest)

    return 0 if bool(admission_ok) else 1


def cmd_mvp_rc_pack(args: argparse.Namespace) -> int:
    root = _repo_root()
    src_dir = root / "src"
    env = _env_with_pythonpath(src_dir)

    release_id = args.release_id or _new_id("rc")
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else (root / "data" / "releases" / release_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(args.data_dir).expanduser()
    if not data_dir.is_absolute():
        # Keep behavior aligned with other MVP commands: interpret relative paths under repo root.
        data_dir = root / data_dir

    schema_version = "1.1.0"
    created_at_utc = _utc_now_iso()
    git_commit = _git_commit(root)
    python_version = _platform.python_version()
    platform_str = _platform.platform()

    commands: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    waivers: list[dict[str, Any]] = [
        {
            "id": "dependency_vulnerability_scan",
            "status": "not_automated",
            "reason": "MVP: dependency vulnerability scanning not wired into pipeline yet",
            "owner": "TBD",
            "due_date_utc": None,
        },
    ]

    # 1) Admission tests
    admission_ok, adm, unittest_path = _run_admission_tests(root, env, out_dir)
    results["admission_ok"] = admission_ok
    results["admission_returncode"] = adm.returncode
    commands.append(
        {
            "name": "admission_tests",
            "argv": adm.argv,
            "cwd": adm.cwd,
            "returncode": adm.returncode,
            "stdout_path": str(unittest_path),
        }
    )

    # 2) assistant-demo (replay-mode) + trace copy
    demo_ok, demo_returncode, trace_id, demo_evidence_refs, trace_copied, trace_src, demo_path = _run_assistant_demo_replay(
        root=root,
        env=env,
        out_dir=out_dir,
        data_dir=data_dir,
        demo_query=str(args.demo_query),
        backend=str(args.backend),
    )
    results["demo_ok"] = demo_ok
    results["demo_returncode"] = demo_returncode
    results["trace_id"] = trace_id
    results["demo_evidence_refs"] = demo_evidence_refs
    results["trace_copied"] = trace_copied
    results["trace_source_path"] = str(trace_src) if trace_src else None
    results["trace_out_path"] = str(out_dir / "trace.jsonl")
    commands.append(
        {
            "name": "assistant_demo",
            "argv": [
                sys.executable,
                "-m",
                "agentos_next.cli",
                "mvp",
                "assistant-demo",
                "--query",
                str(args.demo_query),
                "--data-dir",
                str(data_dir),
                "--backend",
                str(args.backend),
                "--replay-mode",
            ],
            "cwd": str(root),
            "returncode": demo_returncode,
            "stdout_last_json_path": str(demo_path),
        }
    )

    # 2b) mvp exec (ExecuteResult stdout JSON) -> execute_result.json
    exec_ok, exec_returncode, execute_result_path, exec_run = _run_mvp_exec_and_write_execute_result(
        root=root,
        env=env,
        out_dir=out_dir,
        data_dir=data_dir,
        demo_query=str(args.demo_query),
        backend=str(args.backend),
    )
    results["exec_ok"] = exec_ok
    results["exec_returncode"] = exec_returncode
    results["execute_result_path"] = str(execute_result_path)
    commands.append(
        {
            "name": "mvp_exec",
            "argv": exec_run.argv,
            "cwd": exec_run.cwd,
            "returncode": exec_run.returncode,
            "stdout_last_json_path": str(execute_result_path),
        }
    )

    # 3) Manifest (+ collab refs)
    manifest = {
        "schema_version": schema_version,
        "pack_kind": "rc-pack",
        "release_id": release_id,
        "created_at_utc": created_at_utc,
        "git_commit": git_commit,
        "python_version": python_version,
        "platform": platform_str,
        "commands": commands,
        "results": results,
        "waivers": waivers,
        "collab_refs": _collab_refs(root),
        # Additive audit trail (do not break collab_refs contract).
        "collab_threads": _collab_threads(root),
    }
    _write_json(out_dir / "manifest.json", manifest)

    ok = bool(admission_ok and demo_ok and trace_copied and exec_ok)
    return 0 if ok else 1
