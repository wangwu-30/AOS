from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.apps.query_gated_runtime import compile_query_for_assistant_loop
from agentos_next.kernel.runtime_policy_bundle import (
    FileRuntimePolicyBundleStore,
    validate_runtime_policy_bundle_v1,
)
from agentos_next.kernel.types import TraceContext


def _caps(*names: str) -> dict[str, object]:
    effective = [str(name).strip() for name in names if str(name).strip()]
    return {
        "schema_version": "1.0.0",
        "type": "effective_runtime_capabilities_v1",
        "requested_capabilities": effective,
        "effective_capabilities": effective,
        "disabled_capabilities": [],
        "web": {
            "schema_version": "1.0.0",
            "type": "web_runtime_capability_probe_v1",
            "web_search_enabled": "web_search" in effective,
            "web_browse_enabled": "web_browse" in effective,
            "browse_unavailable_reason": None,
            "backends": {
                "available": ["playwright"] if ("web_search" in effective or "web_browse" in effective) else [],
                "unavailable": {},
                "default": "playwright" if ("web_search" in effective or "web_browse" in effective) else None,
            },
        },
        "delivery": {
            "channel_message_enabled": "channel_send" in effective,
            "adapter_mode": "channel_adapter_available",
        },
        "summary_lines": [],
    }


class TestRuntimePolicyBundle(unittest.TestCase):
    def test_store_falls_back_to_repo_default_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_policy_default_") as td:
            store = FileRuntimePolicyBundleStore(data_dir=td)
            bundle = store.get_or_default(workspace_scope="ws_policy_default")

        self.assertEqual(bundle["workspace_policy_id"], "default")
        self.assertEqual(bundle["execution_mode_policy"]["default_mode"], "balanced")
        self.assertEqual(bundle["data_sensitivity_policy"]["default_level"], "L1")
        self.assertEqual(bundle["user_preference_profile"]["communication_style"], ["clear", "honest", "concise"])
        self.assertEqual(bundle["external_evidence_policy"]["search_rounds_max"], 2)
        self.assertEqual(bundle["external_evidence_policy"]["browse_candidates_per_search_max"], 3)
        self.assertEqual(bundle["external_evidence_policy"]["total_browse_steps_max"], 4)

    def test_validate_rejects_invalid_execution_mode(self) -> None:
        bundle, err = validate_runtime_policy_bundle_v1(
            {
                "schema_version": "1.0.0",
                "workspace_policy_id": "bad",
                "workspace_scope": "bad",
                "user_preference_profile": {},
                "execution_mode_policy": {"default_mode": "turbo"},
                "data_sensitivity_policy": {},
                "proactivity_policy": {},
                "external_evidence_policy": {},
            }
        )
        self.assertIsNone(bundle)
        self.assertIn("default_mode", str(err))

    def test_compile_query_uses_workspace_policy_bundle_preferences(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_policy_query_") as td:
            root = Path(td)
            policy_dir = root / "runtime_policy_bundles"
            policy_dir.mkdir(parents=True, exist_ok=True)
            (policy_dir / "ws_pref.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "workspace_policy_id": "ws_pref",
                        "workspace_scope": "ws_pref",
                        "user_preference_profile": {
                            "communication_style": ["formal"],
                            "response_language": "zh-CN",
                            "active_hours_local": [9, 10],
                            "preferred_topics": ["agent"],
                            "risk_tolerance": "low",
                        },
                        "execution_mode_policy": {
                            "default_mode": "quality_first",
                            "allow_user_override": False,
                        },
                        "data_sensitivity_policy": {
                            "default_level": "L0",
                            "storage_policy": {
                                "L0": "process_only",
                                "L1": "local_only",
                                "L2": "local_or_sync",
                            },
                            "external_transfer_requires_confirmation": True,
                        },
                        "proactivity_policy": {
                            "enabled": False,
                            "quiet_hours_local": [0, 1],
                            "notify_on_mentions_only": True,
                            "max_pushes_per_day": 0,
                        },
                        "external_evidence_policy": {
                            "search_rounds_max": 4,
                            "browse_candidates_per_search_max": 5,
                            "total_browse_steps_max": 6,
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            out = compile_query_for_assistant_loop(
                query_text="请总结今天的会议安排",
                req_trace=TraceContext(trace_id="tr_policy_query", turn_id="turn_policy_query", span_id="span_policy_query"),
                workspace_id="ws_pref",
                effective_runtime_capabilities=_caps("channel_send"),
                deadline_ms=60000,
                data_dir=str(root),
            )

        self.assertTrue(out.ok)
        self.assertEqual(out.query["response_language"], "zh-CN")
        self.assertEqual(out.query["active_style_pack"]["pack_id"], "formal")
        self.assertEqual(out.query["model_routing_policy"]["execution_mode"], "quality_first")
        self.assertFalse(out.query["model_routing_policy"]["user_override_allowed"])
        self.assertEqual(out.query["model_routing_policy"]["risk_tolerance"], "low")
        self.assertEqual(out.query["runtime_policy_bundle"]["data_sensitivity_policy"]["default_level"], "L0")
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["search_rounds_max"], 4)
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["browse_candidates_per_search_max"], 5)
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["total_browse_steps_max"], 6)
        evidence = [x for x in out.query["context_pack"]["evidence"] if isinstance(x, dict) and x.get("ref") == "agent_profile:v1"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["data"]["execution_mode"], "quality_first")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
