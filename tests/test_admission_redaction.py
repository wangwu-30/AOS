from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from admission_helpers import make_minimal_skill_package

from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.package_runner import PackageRunner, PackageRunRequest


class TestAdmissionRedaction(unittest.TestCase):
    def test_sensitive_patterns_are_redacted_in_evidence(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_admission_redact_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_adm_redact", turn_id="turn_adm_redact", span_id="span_adm_redact")
            runner = PackageRunner.for_data_dir(data_dir)

            # Put sensitive-looking strings into inputs so they flow into the prompt evidence.
            inp = {
                "q": "Authorization: Bearer sk-test-123\nOPENAI_FOO_TOKEN=abc\n-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----"
            }
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj=inp,
                    workspace_id="ws_adm_redact",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            self.assertTrue(res.ok, msg=f"runner failed: {res.error_code}")

            blobs_dir = data_dir / "evidence" / "blobs"
            meta_dir = data_dir / "evidence" / "meta"
            self.assertTrue(blobs_dir.exists())
            self.assertTrue(meta_dir.exists())

            # Scan all evidence blobs written for this run.
            saw_redaction = False
            for er in res.evidence_refs:
                meta = json.loads((meta_dir / f"{er.ref}.json").read_text(encoding="utf-8"))
                ct = meta.get("content_type", "")
                if ct not in ("application/json",) and not str(ct).startswith("text/"):
                    continue
                content = (blobs_dir / er.ref).read_bytes().decode("utf-8", errors="replace")

                self.assertNotIn("Authorization: Bearer sk-test-123", content)
                self.assertNotIn("OPENAI_FOO_TOKEN=abc", content)
                self.assertNotIn("BEGIN PRIVATE KEY", content)

                if "[REDACTED]" in content:
                    saw_redaction = True

            # Ensure redaction token shows up somewhere, so this isn't a false negative due to filtering.
            self.assertTrue(saw_redaction, msg="no evidence blob contained [REDACTED]")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
