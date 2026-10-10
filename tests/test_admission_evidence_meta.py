from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from admission_helpers import make_minimal_skill_package

from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.package_runner import PackageRunner, PackageRunRequest


class TestAdmissionEvidenceMeta(unittest.TestCase):
    def test_evidence_meta_schema_min_fields_exist(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_admission_meta_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_adm_meta", turn_id="turn_adm_meta", span_id="span_adm_meta")
            runner = PackageRunner.for_data_dir(data_dir)
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_adm_meta",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            self.assertTrue(res.ok, msg=f"runner failed: {res.error_code}")
            self.assertGreaterEqual(len(res.evidence_refs), 1)

            meta_dir = data_dir / "evidence" / "meta"
            self.assertTrue(meta_dir.exists(), msg=f"missing meta dir: {meta_dir}")

            for er in res.evidence_refs:
                meta_path = meta_dir / f"{er.ref}.json"
                self.assertTrue(meta_path.exists(), msg=f"missing evidence meta: {meta_path}")
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

                # Admission requirement: minimal evidence/meta schema fields MUST exist.
                for k in ("ref", "kind", "ts", "content_type", "size_bytes"):
                    self.assertIn(k, meta, msg=f"missing meta field {k} in {meta_path}")

                self.assertEqual(str(meta["ref"]), er.ref)
                self.assertIsInstance(meta["kind"], str)
                self.assertIsInstance(meta["ts"], str)
                self.assertIsInstance(meta["content_type"], str)
                self.assertIsInstance(meta["size_bytes"], int)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
