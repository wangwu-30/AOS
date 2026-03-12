from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestThread040PADemoVisibleRoundtrip(unittest.TestCase):
    def test_visible_roundtrip_webhook_to_outbox_to_reply_stub(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        payload = {
            "update_id": 4242,
            "message": {
                "message_id": 200,
                "date": 1600000000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 555, "is_bot": False, "first_name": "FixtureUser"},
                "text": "Hello Assistant",
            },
        }

        with TemporaryDirectory(prefix="agentos_next_t040_demo_") as td:
            data_dir = Path(td) / "data"
            payload_file = Path(td) / "webhook.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "pa-demo",
                    "--payload-file",
                    str(payload_file),
                    "--expected-secret-token",
                    "demo-secret",
                    "--secret-token",
                    "demo-secret",
                    "--workspace-id",
                    "ws_demo",
                    "--data-dir",
                    str(data_dir),
                    "--no-verify-asvp",
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(p.returncode, 0, msg=f"stderr:\n{p.stderr}\nstdout:\n{p.stdout}")
            self.assertIn("[Telegram Stub] POST", p.stdout)

            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("http_status"), 200)
            self.assertTrue(out.get("reply_sent"))

            outbox_path = data_dir / "pa" / "outbox" / "ws_demo" / "tg_update_4242.json"
            self.assertTrue(outbox_path.exists(), msg=f"missing outbox: {outbox_path}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
