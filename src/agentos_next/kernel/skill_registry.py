from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from agentos_next.compiler.skill_contract import load_contract
from agentos_next.protocol.asvp.manifest import Manifest, load_manifest


class SkillRegistryError(RuntimeError):
    pass


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def registry_id_for_manifest(manifest: Manifest) -> tuple[str, str]:
    """Return (registry_id, full_sha256) for a manifest's canonical bytes.

    registry_id is a truncated, stable content address:
      rg_<first20hex>
    """
    full = _sha256_hex(manifest.canonical_bytes())
    return ("rg_" + full[:20], full)


def is_registry_skill_ref(skill_ref: str) -> bool:
    return str(skill_ref).startswith("registry://")

def is_registry_query_ref(skill_ref: str) -> bool:
    return str(skill_ref).startswith("registryq://")


def parse_registry_id(skill_ref: str) -> str:
    if not is_registry_skill_ref(skill_ref):
        raise SkillRegistryError("skill_ref is not a registry:// ref")
    rid = str(skill_ref)[len("registry://") :].strip()
    if not rid:
        raise SkillRegistryError("missing registry_id in skill_ref")
    return rid


def parse_registry_query(skill_ref: str) -> tuple[str, str]:
    """Parse registryq://<name>@<constraint> -> (name, constraint)."""
    if not is_registry_query_ref(skill_ref):
        raise SkillRegistryError("skill_ref is not a registryq:// ref")
    rest = str(skill_ref)[len("registryq://") :].strip()
    if "@" not in rest:
        raise SkillRegistryError("registryq ref must include @constraint")
    name, constraint = rest.split("@", 1)
    name = name.strip()
    constraint = constraint.strip()
    if not name:
        raise SkillRegistryError("registryq ref missing name")
    if not constraint:
        raise SkillRegistryError("registryq ref missing constraint")
    return name, constraint


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, s: str) -> "SemVer":
        parts = str(s).strip().split(".")
        if len(parts) != 3:
            raise SkillRegistryError(f"version is not semver x.y.z: {s!r}")
        try:
            a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception as e:
            raise SkillRegistryError(f"version is not semver x.y.z: {s!r}") from e
        if a < 0 or b < 0 or c < 0:
            raise SkillRegistryError(f"version is not semver x.y.z: {s!r}")
        return cls(major=a, minor=b, patch=c)


@dataclass(frozen=True)
class RegistryEntry:
    schema_version: str
    registry_id: str
    skill_dir: str
    manifest_sha256: str
    signer_id: str
    name: Optional[str] = None
    version: Optional[str] = None
    deps: tuple[str, ...] = ()


class FileSkillRegistry:
    """Local-only registry mapping registry_id -> skill_dir.

    Layout (relative to data_dir):
    - registry/index.json

    Spec: docs/specs/MVP_013_REGISTRY.md
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._reg_dir = self._data_dir / "registry"
        self._reg_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._reg_dir / "index.json"
        self._lock_path = self._reg_dir / "index.lock"

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.exists():
            return {"schema_version": self.schema_version, "entries": {}}
        try:
            obj = json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            raise SkillRegistryError(f"failed to read registry index: {e}") from e
        if not isinstance(obj, dict):
            raise SkillRegistryError("registry index must be a JSON object")
        if "entries" not in obj or not isinstance(obj.get("entries"), dict):
            raise SkillRegistryError("registry index missing entries object")
        return obj

    def _write_index(self, obj: dict[str, Any]) -> None:
        # Atomic replace to avoid partial writes under crashes.
        tmp = self._index_path.with_name(f"{self._index_path.name}.tmp.{uuid4().hex}")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._index_path)

    @contextlib.contextmanager
    def _acquire_lock(self, *, timeout_sec: float = 2.0, stale_sec: float = 30.0) -> Any:
        """Best-effort local lock for index read-modify-write.

        This is not a distributed lock; it's enough to prevent obvious clobbering for local-only REG2.
        """
        deadline = time.time() + float(timeout_sec)
        while True:
            now = time.time()
            try:
                with self._lock_path.open("x", encoding="utf-8") as f:
                    f.write(json.dumps({"pid": os.getpid(), "ts": now}) + "\n")
                break
            except FileExistsError:
                stale = False
                try:
                    obj = json.loads(self._lock_path.read_text(encoding="utf-8"))
                    ts = float(obj.get("ts"))
                    stale = (now - ts) > float(stale_sec)
                except Exception:
                    try:
                        stale = (now - self._lock_path.stat().st_mtime) > float(stale_sec)
                    except Exception:
                        stale = False
                if stale:
                    with contextlib.suppress(Exception):
                        self._lock_path.unlink()
                    continue
                if now >= deadline:
                    raise SkillRegistryError("registry index is locked (concurrent writer)") from None
                time.sleep(0.05)

        try:
            yield
        finally:
            try:
                self._lock_path.unlink()
            except Exception:
                pass

    def register(self, *, skill_dir: Path, deps: Optional[list[str]] = None) -> RegistryEntry:
        skill_dir = skill_dir.resolve()
        manifest_path = skill_dir / "manifest.json"
        if not manifest_path.exists():
            raise SkillRegistryError(f"missing manifest.json under: {skill_dir}")
        manifest = load_manifest(manifest_path)
        rid, full_sha = registry_id_for_manifest(manifest)

        # Best-effort extract name/version from contract.skill (kept inside signed package in normal workflows).
        name = None
        version = None
        contract_path = skill_dir / "contract.skill"
        if contract_path.exists():
            try:
                c = load_contract(str(contract_path))
                name = str(getattr(c, "name", "") or "").strip() or None
                version = str(getattr(c, "version", "") or "").strip() or None
            except Exception:
                name, version = None, None

        dep_list: list[str] = []
        for d in deps or []:
            if not isinstance(d, str) or not d.strip():
                continue
            if not is_registry_query_ref(d):
                raise SkillRegistryError(f"deps must be registryq:// refs, got: {d!r}")
            dep_list.append(d.strip())

        with self._acquire_lock():
            obj = self._load_index()
            entries = obj.get("entries")
            assert isinstance(entries, dict)

            existing = entries.get(rid)
            if existing is not None:
                if not isinstance(existing, dict):
                    raise SkillRegistryError("registry entry must be an object")
                prev_dir = str(existing.get("skill_dir") or "")
                if prev_dir and Path(prev_dir).resolve() != skill_dir:
                    raise SkillRegistryError(
                        f"registry_id collision/mismatch: {rid} already mapped to {prev_dir}, not {skill_dir}"
                    )
                # Idempotent re-register.
                return RegistryEntry(
                    schema_version=str(existing.get("schema_version") or self.schema_version),
                    registry_id=rid,
                    skill_dir=str(skill_dir),
                    manifest_sha256=str(existing.get("manifest_sha256") or full_sha),
                    signer_id=str(existing.get("signer_id") or manifest.signer_id),
                    name=str(existing.get("name") or name or ""),
                    version=str(existing.get("version") or version or ""),
                    deps=tuple(existing.get("deps") or []),
                )

            entries[rid] = {
                "schema_version": self.schema_version,
                "skill_dir": str(skill_dir),
                "manifest_sha256": full_sha,
                "signer_id": str(manifest.signer_id),
                "name": name,
                "version": version,
                "deps": dep_list,
            }
            obj["schema_version"] = self.schema_version
            obj["entries"] = entries
            self._write_index(obj)

        return RegistryEntry(
            schema_version=self.schema_version,
            registry_id=rid,
            skill_dir=str(skill_dir),
            manifest_sha256=full_sha,
            signer_id=str(manifest.signer_id),
            name=name,
            version=version,
            deps=tuple(dep_list),
        )

    def resolve(self, *, registry_id: str) -> Path:
        rid = str(registry_id).strip()
        if not rid:
            raise SkillRegistryError("registry_id must be non-empty")

        obj = self._load_index()
        entries = obj.get("entries")
        assert isinstance(entries, dict)
        ent = entries.get(rid)
        if ent is None:
            raise SkillRegistryError(f"registry_id not found: {rid}")
        if not isinstance(ent, dict):
            raise SkillRegistryError("registry entry must be an object")
        skill_dir = str(ent.get("skill_dir") or "").strip()
        if not skill_dir:
            raise SkillRegistryError(f"registry entry missing skill_dir for: {rid}")

        p = Path(skill_dir).resolve()
        if not p.exists():
            raise SkillRegistryError(f"registry entry skill_dir does not exist: {p}")
        return p

    def resolve_skill_ref(self, *, skill_ref: str) -> Path:
        rid = parse_registry_id(skill_ref)
        return self.resolve(registry_id=rid)

    def resolve_query_ref(self, *, query_ref: str) -> str:
        """Resolve registryq://name@constraint -> registry_id (deterministic, fail-closed)."""
        name, constraint = parse_registry_query(query_ref)
        obj = self._load_index()
        entries = obj.get("entries")
        assert isinstance(entries, dict)

        candidates: list[tuple[SemVer, str, dict[str, Any]]] = []
        for rid, ent in entries.items():
            if not isinstance(ent, dict):
                continue
            ename = ent.get("name")
            ever = ent.get("version")
            if not isinstance(ename, str) or not isinstance(ever, str):
                continue
            if ename.strip() != name:
                continue
            try:
                sv = SemVer.parse(ever)
            except Exception:
                raise SkillRegistryError(f"invalid semver for registry entry {rid}: {ever!r}")
            candidates.append((sv, str(rid), ent))

        if not candidates:
            raise SkillRegistryError(f"no registry entries for name: {name}")

        if constraint == "*":
            # Highest semver wins; fail-closed if multiple registry_ids share the same highest version.
            candidates.sort(key=lambda t: t[0])
            best_ver = candidates[-1][0]
            best = [c for c in candidates if c[0] == best_ver]
            if len(best) != 1:
                raise SkillRegistryError(f"ambiguous highest version for {name}@*: {best_ver}")
            return best[0][1]

        # Exact version match.
        want = SemVer.parse(constraint)
        exact = [c for c in candidates if c[0] == want]
        if not exact:
            raise SkillRegistryError(f"no match for {name}@{constraint}")
        if len(exact) != 1:
            raise SkillRegistryError(f"ambiguous match for {name}@{constraint}")
        return exact[0][1]

    def resolve_deps(self, *, root_registry_id: str) -> dict[str, str]:
        """Resolve deps for a registry_id. Returns mapping dep_query_ref -> dep_registry_id."""
        obj = self._load_index()
        entries = obj.get("entries")
        assert isinstance(entries, dict)

        root = str(root_registry_id)
        out: dict[str, str] = {}

        visited: set[str] = set()
        visiting: list[str] = []
        visiting_set: set[str] = set()

        def _cycle_error(rid: str) -> SkillRegistryError:
            chain = visiting + [rid]
            return SkillRegistryError("dependency cycle detected: " + " -> ".join(chain))

        def visit(rid: str) -> None:
            if rid in visiting_set:
                raise _cycle_error(rid)
            if rid in visited:
                return
            ent = entries.get(rid)
            if not isinstance(ent, dict):
                raise SkillRegistryError(f"missing registry entry: {rid}")

            visiting.append(rid)
            visiting_set.add(rid)
            try:
                deps = ent.get("deps") or []
                if deps is None:
                    deps = []
                if not isinstance(deps, list):
                    raise SkillRegistryError(f"deps must be an array for: {rid}")

                # Deterministic processing order: sort by dep_ref string.
                dep_refs: list[str] = []
                for d in deps:
                    if not isinstance(d, str):
                        raise SkillRegistryError(f"deps entries must be strings: {rid}")
                    s = d.strip()
                    if s:
                        dep_refs.append(s)
                for dep_ref in sorted(dep_refs):
                    if not is_registry_query_ref(dep_ref):
                        raise SkillRegistryError(f"deps must be registryq:// refs, got: {dep_ref!r}")
                    dep_rid = self.resolve_query_ref(query_ref=dep_ref)
                    if dep_ref in out and out[dep_ref] != dep_rid:
                        raise SkillRegistryError(f"ambiguous dep resolution for {dep_ref}")
                    out[dep_ref] = dep_rid
                    visit(dep_rid)
            finally:
                visiting.pop()
                visiting_set.remove(rid)
                visited.add(rid)

        visit(root)
        return out


def try_resolve_registry_ref(
    *,
    skill_ref: str,
    registry: FileSkillRegistry,
) -> tuple[Optional[Path], Optional[str]]:
    """Return (skill_dir, registry_id) or (None, None) if not a registry ref."""
    if not is_registry_skill_ref(skill_ref):
        return None, None
    rid = parse_registry_id(skill_ref)
    return registry.resolve(registry_id=rid), rid
