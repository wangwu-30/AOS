from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.compiler.skillc import cmd_build
from agentos_next.kernel.agent_profile import build_default_agent_profile_v1
from agentos_next.kernel.effective_runtime_capabilities import (
    build_effective_runtime_capabilities_v1,
)
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.types import TraceContext
from agentos_next.llm.backend import (
    DoubaoArkLLMBackend,
    LLMCallError,
    LLMSafetyGate,
    MiniMaxLLMBackend,
    is_remote_llm_backend,
)
from agentos_next.runtime.builtin_creator import maybe_execute_builtin_creator
from agentos_next.runtime.builtin_research import maybe_execute_builtin_research
from agentos_next.runtime.builtin_time import maybe_execute_builtin_time
from agentos_next.runtime.builtin_web import (
    _reset_search_provider_probe_cache,
    maybe_execute_builtin_web,
    probe_web_runtime_capability,
)
from agentos_next.runtime.playwright_web_runtime import (
    PlaywrightProbeResult,
    SearchRuntimeError,
    _extract_title_from_html,
    duckduckgo_html_search,
    playwright_search,
)
from agentos_next.skills.jsonschema_subset import validate_instance
from agentos_next.skills.llm_execution import build_prompt, execute_skill_via_llm
from agentos_next.skills.package_loader import SkillPackageLoader
from tests.admission_helpers import make_minimal_skill_package


class _FakeHTTPResponse:
    def __init__(self, payload: dict | str) -> None:
        if isinstance(payload, str):
            self._raw = payload.encode("utf-8")
        else:
            self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._raw


class _FakePlaywrightInput:
    def __init__(self, page: "_FakePlaywrightPage") -> None:
        self._page = page

    def fill(self, value: str) -> None:
        self._page.last_query = str(value)

    def press(self, key: str) -> None:
        self._page.last_key = str(key)
        self._page.advance()


class _FakePlaywrightPage:
    def __init__(self, payloads: list[dict[str, str]]) -> None:
        self._payloads = list(payloads)
        self._index = 0
        self.last_query = ""
        self.last_key = ""

    def goto(self, url: str, wait_until: str, timeout: int) -> None:  # noqa: ARG002
        self._index = 0

    def wait_for_load_state(self, state: str, timeout: int) -> None:  # noqa: ARG002
        return None

    @property
    def url(self) -> str:
        return str(self._payloads[self._index]["final_url"])

    def title(self) -> str:
        return str(self._payloads[self._index]["title"])

    def content(self) -> str:
        return str(self._payloads[self._index]["html"])

    def query_selector(self, selector: str):  # noqa: ANN001
        if selector == 'input[name="q"]' and 'name="q"' in str(self._payloads[self._index]["html"]):
            return _FakePlaywrightInput(self)
        return None

    def advance(self) -> None:
        if self._index < len(self._payloads) - 1:
            self._index += 1


class _FakePlaywrightBrowserContext:
    def __init__(self, page: _FakePlaywrightPage) -> None:
        self._page = page

    def new_page(self) -> _FakePlaywrightPage:
        return self._page

    def close(self) -> None:
        return None


class _FakePlaywrightBrowser:
    def __init__(self, page: _FakePlaywrightPage) -> None:
        self._page = page

    def new_context(self, ignore_https_errors: bool = False) -> _FakePlaywrightBrowserContext:  # noqa: ARG002
        return _FakePlaywrightBrowserContext(self._page)

    def close(self) -> None:
        return None


class _FakePlaywrightManager:
    def __init__(self, page: _FakePlaywrightPage) -> None:
        self.chromium = self
        self._page = page

    def __enter__(self) -> "_FakePlaywrightManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def launch(self, headless: bool = True) -> _FakePlaywrightBrowser:  # noqa: ARG002
        return _FakePlaywrightBrowser(self._page)


class _FakeSyncPlaywrightAPI:
    def __init__(self, payloads: list[dict[str, str]]) -> None:
        self.page = _FakePlaywrightPage(payloads)

    def sync_playwright(self) -> _FakePlaywrightManager:
        return _FakePlaywrightManager(self.page)


class _CaptureLLMBackend:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_schema: dict | None = None

    def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
        self.last_schema = dict(json_schema)
        return dict(self.payload)


class _StrictSchemaLLMBackend:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_schema: dict | None = None

    def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
        del prompt, safety, model_id, stream_callback
        self.last_schema = dict(json_schema)
        validate_instance(dict(self.payload), json_schema)
        return dict(self.payload)


class _CaptureMediaLLMBackend:
    def __init__(self) -> None:
        self.last_media: list[dict[str, Any]] = []

    def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None, input_media=None):  # noqa: ANN001
        self.last_media = list(input_media or [])
        return {"status": "done", "reply": "ok"}


def _effective_caps(
    *names: str,
    search_enabled: bool = True,
    browse_enabled: bool = True,
    backends: tuple[str, ...] = ("playwright",),
) -> dict[str, Any]:
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
            "web_search_enabled": bool(search_enabled),
            "web_browse_enabled": bool(browse_enabled),
            "browse_unavailable_reason": None,
            "backends": {
                "available": list(backends),
                "unavailable": {},
                "default": backends[0] if backends else None,
            },
        },
        "multimodal": {
            "schema_version": "1.0.0",
            "type": "multimodal_runtime_capability_v1",
            "ingress_media_kinds": [],
            "artifact_pipeline": {
                "download_supported_kinds": [],
                "evidence_supported_kinds": [],
                "artifact_supported_kinds": [],
            },
            "phase_backend_support": {
                phase: {
                    "backend": "local_mock",
                    "model": None,
                    "supports_text": True,
                    "supports_image": False,
                    "supports_document": False,
                    "supports_audio": False,
                    "supports_video": False,
                    "supports_file_reference": False,
                }
                for phase in ("intent_router", "planner", "executor", "verifier_replanner", "communicator")
            },
        },
        "delivery": {
            "channel_message_enabled": "channel_send" in effective,
            "adapter_mode": "channel_adapter_available",
        },
        "summary_lines": [],
    }


class TestThread047RuntimeCapabilitiesAndWeb(unittest.TestCase):
    def test_effective_runtime_capabilities_exposes_multimodal_phase_support(self) -> None:
        snapshot = build_effective_runtime_capabilities_v1(
            requested_capabilities=["web_search"],
            allow_network_egress=True,
            bot_token="bot-token",
            submitter="telegram.polling",
            backend="codex_oauth",
            model="gpt-5.3-codex",
            intent_backend="doubao_ark",
            intent_model="ep-text",
            communicator_backend="minimax",
            communicator_model="MiniMax-M2.5",
        )
        multimodal = snapshot["multimodal"]
        self.assertEqual(multimodal["ingress_media_kinds"], ["image", "document", "audio", "video"])
        self.assertTrue(multimodal["phase_backend_support"]["executor"]["supports_image"])
        self.assertFalse(multimodal["phase_backend_support"]["intent_router"]["supports_image"])
        self.assertFalse(multimodal["phase_backend_support"]["communicator"]["supports_document"])

    def test_doubao_ark_backend_posts_openai_compatible_chat_completions(self) -> None:
        backend = DoubaoArkLLMBackend(api_key="ark-test-key")
        captured: dict[str, Any] = {}

        def _fake_urlopen(req, timeout=0):  # noqa: ANN001
            headers = {str(k): str(v) for k, v in req.header_items()}
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["auth"] = headers.get("Authorization")
            captured["content_type"] = headers.get("Content-type")
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"status":"done","reply":"ok"}',
                            }
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", new=_fake_urlopen):
            out = backend.complete_json(
                prompt="Return ONLY JSON.",
                json_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "reply"],
                    "properties": {
                        "status": {"type": "string"},
                        "reply": {"type": "string"},
                    },
                },
                safety=LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True),
                model_id="ep-20260309-test",
            )

        self.assertEqual(captured["url"], "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        self.assertEqual(captured["auth"], "Bearer ark-test-key")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(captured["body"]["model"], "ep-20260309-test")
        self.assertEqual(captured["body"]["messages"][0]["role"], "user")
        self.assertIn("Return ONLY JSON.", captured["body"]["messages"][0]["content"])
        self.assertEqual(out, {"status": "done", "reply": "ok"})

    def test_doubao_ark_backend_requires_endpoint_model_id(self) -> None:
        backend = DoubaoArkLLMBackend(api_key="ark-test-key")
        with self.assertRaises(LLMCallError) as cm:
            backend.complete_json(
                prompt="Return ONLY JSON.",
                json_schema={"type": "object", "additionalProperties": True},
                safety=LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True),
                model_id=None,
            )
        self.assertEqual(cm.exception.error_code, "E_MODEL_ID_REQUIRED")

    def test_minimax_backend_posts_openai_compatible_chat_completions(self) -> None:
        backend = MiniMaxLLMBackend(api_key="minimax-test-key")
        captured: dict[str, Any] = {}

        def _fake_urlopen(req, timeout=0):  # noqa: ANN001
            headers = {str(k): str(v) for k, v in req.header_items()}
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["auth"] = headers.get("Authorization")
            captured["content_type"] = headers.get("Content-type")
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"status":"done","reply":"ok"}',
                            }
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", new=_fake_urlopen):
            out = backend.complete_json(
                prompt="Return ONLY JSON.",
                json_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "reply"],
                    "properties": {
                        "status": {"type": "string"},
                        "reply": {"type": "string"},
                    },
                },
                safety=LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True),
                model_id="codex-MiniMax-M2.5",
            )

        self.assertEqual(captured["url"], "https://api.minimax.io/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer minimax-test-key")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(captured["body"]["model"], "codex-MiniMax-M2.5")
        self.assertEqual(captured["body"]["messages"][0]["role"], "user")
        self.assertIn("Return ONLY JSON.", captured["body"]["messages"][0]["content"])
        self.assertEqual(out, {"status": "done", "reply": "ok"})

    def test_minimax_backend_requires_api_key(self) -> None:
        backend = MiniMaxLLMBackend(api_key="")
        with self.assertRaises(LLMCallError) as cm:
            backend.complete_json(
                prompt="Return ONLY JSON.",
                json_schema={"type": "object", "additionalProperties": True},
                safety=LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True),
                model_id="codex-MiniMax-M2.5",
            )
        self.assertEqual(cm.exception.error_code, "E_PROVIDER_AUTH_MISSING")

    def test_minimax_is_treated_as_remote_backend(self) -> None:
        self.assertTrue(is_remote_llm_backend("minimax"))

    def test_build_prompt_exposes_runtime_granted_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "查一下股价"},
            policy_context={
                "effective_runtime_capabilities": _effective_caps(
                    "fs_read",
                    "shell_exec",
                    "web_browse",
                    "time_read",
                )
            },
        )

        self.assertIn("Granted Operators:", prompt)
        self.assertIn("Never silently hide capability gaps", prompt)
        self.assertIn("builtin://shell.exec(command, cwd)", prompt)
        self.assertIn("builtin://time.now()", prompt)
        self.assertIn("builtin://web.search(query, limit?)", prompt)
        self.assertNotIn("builtin://browseruse.search", prompt)
        self.assertIn("builtin://creator.plan(intent, registry_root?, max_steps?)", prompt)
        self.assertIn("interpret relative dates like today/tomorrow/yesterday against that anchor", prompt)

    def test_build_prompt_exposes_explicit_research_operator_when_granted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t047_research_prompt_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            pkg = SkillPackageLoader(verify_asvp=False).load(pkg_dir)

            prompt = build_prompt(
                pkg=pkg,
                input_obj={"request": "给我一份带引用的调研报告"},
                policy_context={
                    "effective_runtime_capabilities": _effective_caps(
                        "web_search",
                        "web_browse",
                        "research_run",
                    )
                },
            )

        self.assertIn("builtin://research.run(objective, depth?, report_format?, min_sources?)", prompt)

    def test_build_prompt_communicator_phase_only_exposes_channel_delivery(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "给用户一个正式回复"},
            policy_context={
                "active_prompt_profile": "communicator",
                "effective_runtime_capabilities": _effective_caps("web_search", "web_browse", "channel_send"),
            },
        )

        self.assertIn("Granted Operators:", prompt)
        self.assertIn("builtin://channel.send_message", prompt)
        self.assertNotIn("builtin://telegram.send_document", prompt)
        self.assertNotIn("builtin://telegram.send_message", prompt)
        self.assertNotIn("builtin://web.search", prompt)
        self.assertNotIn("builtin://web.browse", prompt)

    def test_build_prompt_renders_verified_failure_summary_boundaries(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "请给用户一个 blocker 解释"},
            policy_context={
                "active_prompt_profile": "communicator",
                "verified_failure_summary": {
                    "primary_error_code": "E_WEB_RUNTIME_UNAVAILABLE",
                    "failed_phase": "executor",
                    "reason_class": "external_evidence_unavailable",
                    "objective": "今天北京天气怎么样？",
                    "allowed_user_visible_facts": [
                        "The assistant could not retrieve external web evidence needed for this request.",
                        "Brave Search API is unavailable because BRAVE_SEARCH_API_KEY is not configured.",
                        "DuckDuckGo HTTP search failed before returning usable results.",
                    ],
                    "disallowed_inferences": [
                        "Do not describe any fallback or provider failure as a code bug unless the verified summary explicitly says implementation_bug.",
                    ],
                    "next_step_hint": "Ask the user to retry after the search runtime is repaired.",
                },
            },
        )

        self.assertIn("Verified Failure Summary:", prompt)
        self.assertIn("ALLOWED_USER_VISIBLE_FACTS:", prompt)
        self.assertIn("DISALLOWED_INFERENCES:", prompt)
        self.assertIn("DuckDuckGo HTTP search failed before returning usable results.", prompt)
        self.assertIn("only allowed source for user-visible root-cause labels", prompt)

    def test_build_prompt_uses_effective_runtime_capabilities_snapshot(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "告诉我今天上海天气"},
            policy_context={
                "active_prompt_profile": "planner",
                "effective_runtime_capabilities": _effective_caps("web_search", "web_browse"),
            },
        )

        self.assertIn("Worker Task Operator Refs:", prompt)
        self.assertIn("builtin://web.search", prompt)
        self.assertIn("builtin://web.browse", prompt)
        self.assertNotIn("Granted Operators:", prompt)
        self.assertNotIn("builtin://web.search(query, limit?)", prompt)
        self.assertNotIn("builtin://web.browse(url)", prompt)
        self.assertIn("MUST NOT emit top-level actions", prompt)
        self.assertNotIn("reply: string", prompt)
        self.assertNotIn("Worker-local tool actions to perform.", prompt)
        self.assertNotIn("provider='", prompt)
        self.assertNotIn("builtin://browseruse.search", prompt)

    def test_build_prompt_keeps_transport_rules_out_of_kernel_prompt(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "随便聊聊"},
            policy_context={
                "llm_stream_callback": lambda event: None,
            },
        )

        self.assertIn("Stable Kernel Prefix:", prompt)
        self.assertNotIn("Transport Contract:", prompt)
        self.assertNotIn("reply field as the first key", prompt)
        self.assertNotIn("Begin writing the `reply` text immediately.", prompt)

    def test_build_prompt_exposes_active_agent_axioms_and_constraints(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        profile = build_default_agent_profile_v1(agent_id="pa_ev1")
        context_planes = {
            "execution_plane": {"state_summary": "working", "evidence_refs": [], "message_received_at_utc": None},
            "communication_plane": {"role_hint": None, "style_constraints": []},
            "retrospective_plane": {
                "recent_failures": ["type=action; skill_ref=builtin://fs.read; input_fp=deadbeef"],
                "recent_success_patterns": ["accepted"],
            },
            "constraint_plane": {
                "active_axiom_ids": [x["id"] for x in profile["axioms"]],
                "active_constraint_ids": [x["id"] for x in profile["reality_constraints"]],
            },
        }

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "分析这个项目"},
            policy_context={
                "agent_profile": profile,
                "context_planes": context_planes,
                "execution_prefix": "PHASE=EXEC\nGOAL=分析这个项目\nAX=AX_TOOL_REALITY_FIRST|AX_BLOCKER_TO_MIN_CORRECTION\nRC=RC_RUNTIME_ACTIONS_ONLY|RC_USER_VISIBLE_TOOL_AUDIT",
            },
        )

        self.assertIn("Task Block:", prompt)
        self.assertIn("AX=AX_TOOL_REALITY_FIRST|AX_BLOCKER_TO_MIN_CORRECTION", prompt)
        self.assertIn("RC=RC_RUNTIME_ACTIONS_ONLY|RC_USER_VISIBLE_TOOL_AUDIT", prompt)
        self.assertNotIn("Active Agent Rules:", prompt)

    def test_build_prompt_includes_task_envelope_and_delivery_contract_sections(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "帮我总结今天的进展"},
            policy_context={
                "execution_prefix": "PHASE=EXEC\nGOAL=总结今天的进展\nDELIVERABLE=user_visible_answer\nDONE=给出可直接发送的总结并显式标注不确定项",
                "communication_prefix": "PHASE=COMM\nROLE=assistant\nSTYLE=clear|honest|concise",
                "memory_context": {
                    "schema_version": "2.0.0",
                    "l0_continuity": {"workspace_id": "local", "conversation_id": "turn_1"},
                    "l1_query": {"query": "帮我总结今天的进展", "intent": "delivery", "limit": 1},
                    "l2_hits": [
                        {
                            "record_id": "mr_mem_1",
                            "kind": "delivery_summary",
                            "summary": "昨天已完成初稿",
                            "evidence_ref": "ev_mem_1",
                            "freshness": "active",
                        }
                    ],
                    "conflicts": [],
                    "retrieval_ref": "ev_route_1",
                },
            },
        )

        self.assertIn("Task Block:", prompt)
        self.assertIn("Communication Prefix:", prompt)
        self.assertIn("PHASE=EXEC", prompt)
        self.assertIn("GOAL=总结今天的进展", prompt)
        self.assertIn("STYLE=clear|honest|concise", prompt)
        self.assertIn("Memory Pack:", prompt)
        self.assertIn("L0 CONTINUITY", prompt)
        self.assertIn("L1 QUERY", prompt)
        self.assertIn("L2 HITS", prompt)
        self.assertIn("昨天已完成初稿", prompt)
        self.assertIn("RETRIEVAL_REF=ev_route_1", prompt)
        self.assertIn("Input JSON:", prompt)
        self.assertIn("reply: string", prompt)
        self.assertIn("Optional communicator-only streaming mirror", prompt)
        self.assertNotIn('"additionalProperties"', prompt)
        self.assertNotIn('"properties"', prompt)

    def test_build_prompt_dedupes_execution_prefix_from_memory_inline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        execution_prefix = "PHASE=EXEC\nGOAL=总结今天的进展\nDONE=给出结论"

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "帮我总结今天的进展"},
            policy_context={
                "execution_prefix": execution_prefix,
                "memory_context": {
                    "schema_version": "2.0.0",
                    "l0_continuity": {"workspace_id": "local", "conversation_id": "turn_1"},
                    "l1_query": {"query": "帮我总结今天的进展", "intent": "delivery", "limit": 1},
                    "l2_hits": [
                        {
                            "record_id": "mr_mem_1",
                            "kind": "delivery_summary",
                            "summary": "昨天已完成初稿",
                            "evidence_ref": "ev_mem_1",
                            "freshness": "active",
                        }
                    ],
                    "conflicts": [],
                    "retrieval_ref": "ev_route_1",
                },
            },
        )

        self.assertEqual(prompt.count("PHASE=EXEC"), 1)
        self.assertIn("L2 HITS", prompt)

    def test_build_prompt_prefers_kernel_execution_contract_over_skill_persona(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)

        prompt = build_prompt(
            pkg=pkg,
            input_obj={"request": "分析这个项目"},
            policy_context={
                "execution_prefix": "PHASE=EXEC\nGOAL=分析这个项目\nDONE=基于证据给出结论\nREQ=workspace_observation|no_speculation_without_evidence",
                "execution_observation_capsule": "WORKSPACE ROOT\n- src/\n- docs/\n\nKEY FILE CANDIDATES\n- ./README.md\n- ./pyproject.toml",
            },
        )

        self.assertIn("Stable Kernel Prefix:", prompt)
        self.assertIn("Observation Capsule:", prompt)
        self.assertNotIn("You are Antigravity-PA", prompt)
        self.assertNotIn("Supported Actions:", prompt)

    def test_execute_skill_via_llm_uses_runtime_completion_schema_and_maps_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _CaptureLLMBackend(
            {
                "reply": "ok",
                "actions": [{"operator_ref": "builtin://fs.list", "arguments": {"path": "."}}],
            }
        )

        out = execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "列出目录"},
            backend=backend,
            safety=LLMSafetyGate(),
        )

        assert backend.last_schema is not None
        self.assertIn("output", backend.last_schema.get("properties", {}))
        self.assertNotEqual(backend.last_schema, dict(pkg.artifacts.outputs_schema))
        self.assertEqual(out.output["reply"], "ok")
        self.assertEqual(out.output["actions"][0]["operator_ref"], "builtin://fs.list")
        self.assertEqual(out.output["actions"][0]["arguments"], {"path": "."})

    def test_execute_skill_via_llm_keeps_outputs_schema_as_post_validation_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t047_llm_schema_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            pkg = SkillPackageLoader(verify_asvp=False).load(pkg_dir)
            backend = _CaptureLLMBackend({})

            out = execute_skill_via_llm(
                pkg=pkg,
                input_obj={"q": "hi"},
                backend=backend,
                safety=LLMSafetyGate(),
            )

            assert backend.last_schema is not None
            self.assertIn("actions", backend.last_schema.get("properties", {}))
            self.assertEqual(out.output, {"ok": True})

    def test_execute_skill_via_llm_uses_phase_scoped_schema_for_planner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _CaptureLLMBackend({"status": "continue", "worker_tasks": []})

        execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "告诉我今天北京天气"},
            backend=backend,
            safety=LLMSafetyGate(),
            policy_context={
                "active_prompt_profile": "planner",
                "effective_runtime_capabilities": _effective_caps("web_search", "web_browse"),
            },
        )

        assert backend.last_schema is not None
        self.assertIn("worker_tasks", backend.last_schema.get("properties", {}))
        self.assertNotIn("actions", backend.last_schema.get("properties", {}))
        self.assertNotIn("reply", backend.last_schema.get("properties", {}))

    def test_execute_skill_via_llm_planner_normalizes_legacy_actions_into_worker_tasks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _StrictSchemaLLMBackend(
            {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "search_weather",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "北京 今天天气"},
                    }
                ],
            }
        )

        out = execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "告诉我今天北京天气"},
            backend=backend,
            safety=LLMSafetyGate(),
            policy_context={"active_prompt_profile": "planner"},
        )

        worker_tasks = out.output.get("worker_tasks") or []
        self.assertEqual(len(worker_tasks), 1)
        self.assertEqual(worker_tasks[0]["allowed_operator_refs"], ["builtin://web.search"])
        self.assertEqual(worker_tasks[0]["tool_budget"]["max_calls"], 1)
        self.assertNotIn("actions", out.output)

    def test_execute_skill_via_llm_planner_tolerates_non_object_tool_budget_in_raw_output(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _StrictSchemaLLMBackend(
            {
                "status": "continue",
                "worker_tasks": [
                    {
                        "worker_task_id": "worker_weather",
                        "objective": "查询北京天气",
                        "depends_on": [],
                        "allowed_operator_refs": ["builtin://web.search"],
                        "scope_summary": "只读天气查询",
                        "completion_contract_ref": "worker_contract:weather",
                        "tool_budget": "default",
                        "time_budget_ms": 8000,
                    }
                ],
            }
        )

        out = execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "告诉我今天北京天气"},
            backend=backend,
            safety=LLMSafetyGate(),
            policy_context={"active_prompt_profile": "planner"},
        )

        worker_tasks = out.output.get("worker_tasks") or []
        self.assertEqual(len(worker_tasks), 1)
        self.assertEqual(
            worker_tasks[0]["tool_budget"],
            {"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False},
        )

    def test_execute_skill_via_llm_intent_router_drops_phase_invalid_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _StrictSchemaLLMBackend(
            {
                "status": "done",
                "reasoning": "用户意图明确，可进入后续规划。",
                "actions": [
                    {
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "北京 今天天气"},
                    }
                ],
            }
        )

        out = execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "告诉我今天北京天气"},
            backend=backend,
            safety=LLMSafetyGate(),
            policy_context={"active_prompt_profile": "intent_router"},
        )

        self.assertEqual(out.output.get("status"), "done")
        self.assertEqual(out.output.get("reasoning"), "用户意图明确，可进入后续规划。")
        self.assertNotIn("actions", out.output)

    def test_execute_skill_via_llm_executor_explicit_empty_actions_clear_synthesized_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _StrictSchemaLLMBackend({"status": "done", "actions": []})

        out = execute_skill_via_llm(
            pkg=pkg,
            input_obj={"request": "分析这个项目并给出建议"},
            backend=backend,
            safety=LLMSafetyGate(),
            policy_context={"active_prompt_profile": "executor"},
        )

        self.assertEqual(out.output.get("status"), "done")
        self.assertEqual(out.output.get("actions"), [])

    def test_execute_skill_via_llm_passes_selected_media_inputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        backend = _CaptureMediaLLMBackend()
        with tempfile.TemporaryDirectory(prefix="agentos_next_t047_media_") as td:
            media_path = Path(td) / "sample.jpg"
            media_path.write_bytes(b"\xff\xd8\xff\xd9")
            out = execute_skill_via_llm(
                pkg=pkg,
                input_obj={"request": "帮我看图"},
                backend=backend,
                policy_context={
                    "selected_attachments": [
                        {
                            "attachment_id": "att1",
                            "media_kind": "image",
                            "local_path": str(media_path),
                            "mime_type": "image/jpeg",
                            "filename": "sample.jpg",
                        }
                    ]
                },
            )
        self.assertEqual(out.output.get("reply"), "ok")
        self.assertEqual(len(backend.last_media), 1)
        self.assertEqual(backend.last_media[0]["media_kind"], "image")

    def test_execute_skill_via_llm_ignores_local_mock_placeholder_for_minimax(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        pkg = SkillPackageLoader(verify_asvp=False).load(skill_dir)
        captured: dict[str, Any] = {}

        def _fake_urlopen(req, timeout=0):  # noqa: ANN001
            del timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"reply":"ok","actions":[]}',
                            }
                        }
                    ]
                }
            )

        backend = MiniMaxLLMBackend(api_key="minimax-test-key")
        with patch("urllib.request.urlopen", new=_fake_urlopen):
            with patch.dict(os.environ, {"MINIMAX_MODEL_ID": "codex-MiniMax-M2.5"}, clear=False):
                out = execute_skill_via_llm(
                    pkg=pkg,
                    input_obj={"request": "今天北京天气怎么样"},
                    backend=backend,
                    safety=LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True),
                )

        self.assertEqual(captured["body"]["model"], "codex-MiniMax-M2.5")
        self.assertEqual(out.output["reply"], "ok")

    def test_default_telegram_profile_has_transparency_and_blocker_axioms(self) -> None:
        profile = build_default_agent_profile_v1(agent_id="telegram_assistant")

        axiom_ids = [x["id"] for x in profile["execution_axioms"]]
        communication_axiom_ids = [x["id"] for x in profile["communication_axioms"]]
        constraint_ids = [x["id"] for x in profile["reality_constraints"]]

        self.assertIn("AX_TOOL_REALITY_FIRST", axiom_ids)
        self.assertIn("AX_BLOCKER_TO_MIN_CORRECTION", axiom_ids)
        self.assertIn("AX_VERIFY_BEFORE_DONE", axiom_ids)
        self.assertIn("AX_NOT_USERS_VOICE", communication_axiom_ids)
        self.assertIn("RC_RUNTIME_ACTIONS_ONLY", constraint_ids)
        self.assertIn("RC_USER_VISIBLE_TOOL_AUDIT", constraint_ids)

    def test_builtin_creator_plan_returns_skill_first_plan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract = root / "examples" / "skills" / "personal_assistant_brief" / "contract.skill"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t047_creator_") as td:
            registry_root = Path(td) / "registry"
            cmd_build(str(contract), str(registry_root))
            req = ExecuteRequest(
                workspace_id="ws_t047",
                skill_ref="builtin://creator.plan",
                input={"intent": "做一个总结技能", "registry_root": str(registry_root)},
                idempotency_key="idem_t047_creator",
                deadline_ms=5000,
                trace=TraceContext(trace_id="tr_t047_creator", turn_id="turn_t047_creator", span_id="span_t047_creator"),
                policy_context={"model": "gpt-5.2-codex"},
                preferred_target="local",
            )
            out = maybe_execute_builtin_creator(req=req, data_dir=str(Path(td) / "data"))

            self.assertTrue(out.handled)
            self.assertEqual(out.result.status, "accepted")

            evidence = FileEvidenceStore(data_dir=str(Path(td) / "data"))
            blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
            assert blob is not None
            payload = json.loads(blob.content.decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["plan"]["mode"], "plan_only")
            self.assertGreaterEqual(len(payload["plan"]["steps"]), 1)

    def test_builtin_creator_write_local_skill_uses_local_unsigned_layer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t047_creator_local_skill_") as td:
            registry_root = Path(td) / "workspace"
            req = ExecuteRequest(
                workspace_id="ws_t047",
                skill_ref="builtin://creator.write_local_skill",
                input={
                    "name": "workspace_summarizer",
                    "description": "Summarize a local workspace file.",
                    "logic": "Read the requested file and return a concise summary.",
                    "registry_root": str(registry_root),
                },
                idempotency_key="idem_t047_creator_local_skill",
                deadline_ms=5000,
                trace=TraceContext(
                    trace_id="tr_t047_creator_local_skill",
                    turn_id="turn_t047_creator_local_skill",
                    span_id="span_t047_creator_local_skill",
                ),
                policy_context={"model": "gpt-5.2-codex"},
                preferred_target="local",
            )
            out = maybe_execute_builtin_creator(req=req, data_dir=str(Path(td) / "data"))

            self.assertTrue(out.handled)
            self.assertEqual(out.result.status, "accepted")

            evidence = FileEvidenceStore(data_dir=str(Path(td) / "data"))
            blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
            assert blob is not None
            payload = json.loads(blob.content.decode("utf-8"))
            expected_dir = (registry_root / ".agentos" / "local_skills" / "workspace_summarizer").resolve()
            self.assertEqual(Path(payload["skill_dir"]).resolve(), expected_dir)
            self.assertEqual(payload["skill_layer"], "local_unsigned")
            self.assertFalse(bool(payload["registry_eligible"]))
            self.assertTrue((expected_dir / "contract.skill").exists())
            contract = json.loads((expected_dir / "contract.skill").read_text(encoding="utf-8"))
            self.assertEqual(contract["type"], "local_unsigned_skill_v1")

    def test_builtin_time_now_returns_relative_date_anchor(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            skill_ref="builtin://time.now",
            input={"anchor_utc": "2026-03-09T01:02:03Z"},
            idempotency_key="idem_t047_time_now",
            deadline_ms=5000,
            trace=TraceContext(trace_id="tr_t047_time_now", turn_id="turn_t047_time_now", span_id="span_t047_time_now"),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_time_now_")
        out = maybe_execute_builtin_time(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["operator_ref"], "builtin://time.now")
        self.assertEqual(payload["anchor_time_utc"], "2026-03-09T01:02:03Z")
        self.assertIn("today", payload["relative_dates"])
        self.assertIn("tomorrow", payload["relative_dates"])
        self.assertIn("timezone_local", payload)

    def test_web_search_auto_prefers_brave(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "AAPL stock"},
            idempotency_key="idem_t047_brave",
            deadline_ms=5000,
            trace=TraceContext(trace_id="tr_t047_brave", turn_id="turn_t047_brave", span_id="span_t047_brave"),
            policy_context={},
            preferred_target="local",
        )
        response = _FakeHTTPResponse(
            {
                "web": {
                    "results": [
                        {"title": "Apple Inc.", "description": "Quote and chart", "url": "https://example.com/aapl"}
                    ]
                }
            }
        )
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}, clear=False):
            with patch("agentos_next.runtime.builtin_web.urllib.request.urlopen", return_value=response) as mocked:
                out = maybe_execute_builtin_web(req=req, data_dir=tempfile.mkdtemp(prefix="agentos_next_t047_brave_data_"))

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        called_url = str(mocked.call_args.args[0].full_url)
        self.assertIn("api.search.brave.com", called_url)

    def test_web_search_falls_back_to_duckduckgo_html(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "AAPL stock"},
            idempotency_key="idem_t047_duckduckgo_html",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_duckduckgo_html",
                turn_id="turn_t047_duckduckgo_html",
                span_id="span_t047_duckduckgo_html",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_duckduckgo_html_data_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "variant": "html",
                    "results": [{"title": "Apple Investor Relations", "snippet": "Latest", "url": "https://example.com"}],
                    "attempts": [{"provider": "duckduckgo_html", "variant": "html", "status": "ok"}],
                },
            ) as mocked:
                out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        mocked.assert_called_once_with(query="AAPL stock", limit=5, include_metadata=True)
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["provider_used"], "duckduckgo_html")
        self.assertTrue(payload["degraded"])

    def test_duckduckgo_html_search_rejects_portal_without_results(self) -> None:
        with patch(
            "agentos_next.runtime.playwright_web_runtime._open_html_search_page",
            side_effect=[
                {
                    "final_url": "https://html.duckduckgo.com/html/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="北京天气" /></form></body></html>',
                },
                {
                    "final_url": "https://lite.duckduckgo.com/lite/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="北京天气" /></form></body></html>',
                },
            ],
        ):
            with self.assertRaises(SearchRuntimeError) as cm:
                duckduckgo_html_search(query="北京 今日 天气", limit=5)

        self.assertEqual(cm.exception.error_code, "E_WEB_SEARCH_NO_RESULTS")
        attempts = cm.exception.payload.get("attempts")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["variant"], "html")
        self.assertEqual(attempts[1]["variant"], "lite")

    def test_duckduckgo_html_search_falls_back_from_html_to_lite(self) -> None:
        with patch(
            "agentos_next.runtime.playwright_web_runtime._open_html_search_page",
            side_effect=[
                {
                    "final_url": "https://html.duckduckgo.com/html/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="北京天气" /></form></body></html>',
                },
                {
                    "final_url": "https://lite.duckduckgo.com/lite/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94",
                    "title": "北京 今日 天气 at DuckDuckGo",
                    "html": '<html><body><a class="result-link" href="/l/?uddg=https%3A%2F%2Fweather.example.com%2Fbeijing">北京天气</a></body></html>',
                },
            ],
        ):
            payload = duckduckgo_html_search(query="北京 今日 天气", limit=5, include_metadata=True)

        self.assertEqual(payload["provider_used"], "duckduckgo_html")
        self.assertEqual(payload["variant"], "lite")
        self.assertEqual(payload["results"][0]["url"], "https://weather.example.com/beijing")
        self.assertEqual(payload["attempts"][0]["status"], "failed")
        self.assertEqual(payload["attempts"][1]["status"], "ok")

    def test_playwright_search_resubmits_query_once_after_portal_landing(self) -> None:
        fake_sync_api = _FakeSyncPlaywrightAPI(
            [
                {
                    "final_url": "https://duckduckgo.com/",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="" /></form></body></html>',
                },
                {
                    "final_url": "https://duckduckgo.com/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94&ia=web",
                    "title": "北京 今日 天气 at DuckDuckGo",
                    "html": '<html><body><a class="result__a" href="https://weather.example.com/beijing">北京天气</a><div class="result__snippet">今日天气</div></body></html>',
                },
            ]
        )
        with patch("agentos_next.runtime.playwright_web_runtime.importlib.import_module", return_value=fake_sync_api):
            payload = playwright_search(query="北京 今日 天气", limit=5, include_metadata=True)

        self.assertEqual(payload["provider_used"], "playwright_search")
        self.assertTrue(payload["resubmitted"])
        self.assertEqual(fake_sync_api.page.last_query, "北京 今日 天气")
        self.assertEqual(fake_sync_api.page.last_key, "Enter")
        self.assertEqual(payload["results"][0]["url"], "https://weather.example.com/beijing")

    def test_playwright_search_returns_no_results_after_single_resubmit(self) -> None:
        fake_sync_api = _FakeSyncPlaywrightAPI(
            [
                {
                    "final_url": "https://duckduckgo.com/",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="" /></form></body></html>',
                },
                {
                    "final_url": "https://duckduckgo.com/?q=%E5%8C%97%E4%BA%AC+%E4%BB%8A%E6%97%A5+%E5%A4%A9%E6%B0%94&ia=web",
                    "title": "DuckDuckGo",
                    "html": '<html><body><form class="search-form"><input name="q" value="北京天气" /></form></body></html>',
                },
            ]
        )
        with patch("agentos_next.runtime.playwright_web_runtime.importlib.import_module", return_value=fake_sync_api):
            with self.assertRaises(SearchRuntimeError) as cm:
                playwright_search(query="北京 今日 天气", limit=5, include_metadata=True)

        self.assertEqual(cm.exception.error_code, "E_WEB_SEARCH_NO_RESULTS")

    def test_extract_title_from_html_strips_markup(self) -> None:
        title = _extract_title_from_html("<html><head><title>北京 <b>天气</b> - DuckDuckGo</title></head></html>")
        self.assertEqual(title, "北京 天气 - DuckDuckGo")

    def test_web_search_failure_preserves_provider_attempts_in_error_evidence(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "北京 今日 天气"},
            idempotency_key="idem_t047_search_failure",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_search_failure",
                turn_id="turn_t047_search_failure",
                span_id="span_t047_search_failure",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_search_failure_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                side_effect=SearchRuntimeError(
                    "E_WEB_SEARCH_NO_RESULTS",
                    "DuckDuckGo HTTP search failed for query='北京 今日 天气'",
                    payload={
                        "attempts": [
                            {
                                "provider": "duckduckgo_html",
                                "variant": "html",
                                "status": "failed",
                                "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                "detail": "DuckDuckGo HTML search only returned the DuckDuckGo homepage/search portal without usable results for query='北京 今日 天气'",
                            },
                            {
                                "provider": "duckduckgo_html",
                                "variant": "lite",
                                "status": "failed",
                                "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                "detail": "DuckDuckGo Lite search returned no usable results for query='北京 今日 天气'",
                            },
                        ]
                    },
                ),
            ), patch(
                "agentos_next.runtime.builtin_web.playwright_search",
                side_effect=SearchRuntimeError(
                    "E_WEB_SEARCH_NO_RESULTS",
                    "Browser-assisted search returned no usable results for query='北京 今日 天气'",
                    payload={
                        "attempts": [
                            {
                                "provider": "playwright_search",
                                "status": "failed",
                                "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                "detail": "Browser-assisted search returned no usable results for query='北京 今日 天气'",
                            }
                        ]
                    },
                ),
            ):
                out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "failed")
        self.assertEqual(out.result.error_code, "E_WEB_SEARCH_NO_RESULTS")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["operator_ref"], "builtin://web.search")
        self.assertEqual(payload["query"], "北京 今日 天气")
        self.assertEqual(len(payload["provider_attempts"]), 4)
        self.assertEqual(payload["provider_attempts"][0]["provider"], "brave")
        self.assertEqual(payload["provider_attempts"][0]["status"], "failed")
        self.assertIn("BRAVE_SEARCH_API_KEY is not configured", payload["provider_attempts"][0]["detail"])
        self.assertEqual(payload["provider_attempts"][1]["variant"], "html")
        self.assertEqual(payload["provider_attempts"][2]["variant"], "lite")
        self.assertEqual(payload["provider_attempts"][3]["provider"], "playwright_search")
        self.assertIn("notices", payload)

    def test_web_search_fallback_does_not_invoke_playwright_browse(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "AAPL stock"},
            idempotency_key="idem_t047_no_browse",
            deadline_ms=5000,
            trace=TraceContext(trace_id="tr_t047_no_browse", turn_id="turn_t047_no_browse", span_id="span_t047_no_browse"),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_no_browse_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                side_effect=SearchRuntimeError(
                    "E_WEB_SEARCH_NO_RESULTS",
                    "DuckDuckGo HTTP search returned no usable results for query='AAPL stock'",
                ),
            ):
                with patch(
                    "agentos_next.runtime.builtin_web.playwright_search",
                    return_value={
                        "provider_used": "playwright_search",
                        "results": [{"title": "Apple", "snippet": "Result", "url": "https://example.com"}],
                        "attempts": [{"provider": "playwright_search", "status": "ok"}],
                    },
                ) as search_mock:
                    with patch(
                        "agentos_next.runtime.builtin_web.playwright_browse",
                        side_effect=AssertionError("public browse should not run"),
                    ):
                        out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertEqual(out.result.status, "accepted")
        search_mock.assert_called_once()

    def test_web_search_preserves_provider_candidate_order_without_topic_specific_reranking(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "今日北京天气"},
            idempotency_key="idem_t047_search_order",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_search_order",
                turn_id="turn_t047_search_order",
                span_id="span_t047_search_order",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_search_order_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "variant": "html",
                    "results": [
                        {
                            "title": "北京月天气",
                            "snippet": "北京 2026 年 03 月天气信息。",
                            "url": "https://ip.cn/tianqi/beijing/beijing/202603.html",
                        },
                        {
                            "title": "北京天气预报",
                            "snippet": "北京今日天气，实时更新。",
                            "url": "https://www.weather.com.cn/weather/101010100.shtml",
                        },
                    ],
                    "attempts": [{"provider": "duckduckgo_html", "variant": "html", "status": "ok"}],
                },
            ):
                out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["provider_used"], "duckduckgo_html")
        self.assertEqual(payload["results"][0]["url"], "https://ip.cn/tianqi/beijing/beijing/202603.html")
        self.assertEqual(payload["results"][1]["url"], "https://www.weather.com.cn/weather/101010100.shtml")

    def test_web_search_does_not_reject_provider_results_only_because_they_look_like_archives(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "今日北京天气"},
            idempotency_key="idem_t047_search_archive_passthrough",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_search_archive_passthrough",
                turn_id="turn_t047_search_archive_passthrough",
                span_id="span_t047_search_archive_passthrough",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_search_archive_passthrough_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "variant": "html",
                    "results": [
                        {
                            "title": "北京月天气",
                            "snippet": "北京 2026 年 03 月天气信息。",
                            "url": "https://ip.cn/tianqi/beijing/beijing/202603.html",
                        }
                    ],
                    "attempts": [{"provider": "duckduckgo_html", "variant": "html", "status": "ok"}],
                },
            ):
                out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["provider_used"], "duckduckgo_html")
        self.assertEqual(payload["results"][0]["url"], "https://ip.cn/tianqi/beijing/beijing/202603.html")
        ddg_attempts = [item for item in payload["provider_attempts"] if item.get("provider") == "duckduckgo_html"]
        self.assertEqual(len(ddg_attempts), 1)
        self.assertEqual(ddg_attempts[0]["status"], "ok")

    def test_effective_runtime_capabilities_disable_research_run_without_browse(self) -> None:
        with patch(
            "agentos_next.runtime.builtin_web.probe_web_runtime_capability",
            return_value={
                "schema_version": "1.0.0",
                "type": "web_runtime_capability_probe_v1",
                "web_search_enabled": True,
                "web_browse_enabled": False,
                "browse_unavailable_reason": "playwright unavailable",
                "backends": {
                    "available": ["duckduckgo_html"],
                    "unavailable": {"playwright": "playwright unavailable"},
                    "default": "duckduckgo_html",
                },
            },
        ):
            snapshot = build_effective_runtime_capabilities_v1(
                requested_capabilities=["research_run"],
                allow_network_egress=True,
                backend="local_mock",
                model=None,
            )

        self.assertNotIn("research_run", snapshot["effective_capabilities"])
        disabled = [item for item in snapshot["disabled_capabilities"] if item.get("name") == "research_run"]
        self.assertEqual(len(disabled), 1)
        self.assertIn("requires both web_search and web_browse", str(disabled[0]["reason"]))

    def test_builtin_research_run_produces_summary_report_and_citations(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://research.run",
            arguments={"objective": "深入调研北京今日天气，给我一个带引用的结论", "min_sources": 2},
            idempotency_key="idem_t047_research_run",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_research_run",
                turn_id="turn_t047_research_run",
                span_id="span_t047_research_run",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_research_run_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_research._run_search_provider",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "results": [
                        {
                            "title": "北京天气预报",
                            "snippet": "北京今天多云，气温 5 到 13 摄氏度。",
                            "url": "https://weather.example.com/beijing/today",
                        },
                        {
                            "title": "北京实时天气",
                            "snippet": "北京实时天气与空气质量。",
                            "url": "https://news.example.com/beijing/weather-live",
                        },
                    ],
                    "attempts": [{"provider": "duckduckgo_html", "status": "ok"}],
                },
            ), patch(
                "agentos_next.runtime.builtin_research.playwright_browse",
                side_effect=[
                    {
                        "provider_used": "playwright",
                        "url": "https://weather.example.com/beijing/today",
                        "final_url": "https://weather.example.com/beijing/today",
                        "title": "北京天气预报",
                        "text": "北京今天多云，最高气温 13 摄氏度，最低气温 5 摄氏度。",
                    },
                    {
                        "provider_used": "playwright",
                        "url": "https://news.example.com/beijing/weather-live",
                        "final_url": "https://news.example.com/beijing/weather-live",
                        "title": "北京实时天气",
                        "text": "来源指出北京白天多云，夜间转晴，可见度良好。",
                    },
                ],
            ):
                out = maybe_execute_builtin_research(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["depth"], "standard")
        self.assertEqual(payload["report_format"], "markdown")
        self.assertEqual(len(payload["citations"]), 2)
        self.assertEqual(len(payload["sources"]), 2)
        self.assertIn("调研报告", payload["report"])
        self.assertIn("北京天气预报", payload["summary"])

    def test_web_browse_uses_playwright_runtime(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.browse",
            arguments={"url": "https://example.com"},
            idempotency_key="idem_t047_browse",
            deadline_ms=5000,
            trace=TraceContext(
                trace_id="tr_t047_browse",
                turn_id="turn_t047_browse",
                span_id="span_t047_browse",
            ),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_browse_")
        with patch(
            "agentos_next.runtime.builtin_web.playwright_browse",
            return_value={
                "provider_used": "playwright",
                "url": "https://example.com",
                "final_url": "https://example.com/final",
                "title": "Example",
                "text": "Example body",
            },
        ):
            out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertEqual(payload["provider_used"], "playwright")
        self.assertEqual(payload["output"]["title"], "Example")

    def test_web_search_auto_degradation_is_explicit(self) -> None:
        req = ExecuteRequest(
            workspace_id="ws_t047",
            operator_ref="builtin://web.search",
            arguments={"query": "AAPL stock"},
            idempotency_key="idem_t047_auto_degrade",
            deadline_ms=5000,
            trace=TraceContext(trace_id="tr_t047_auto_degrade", turn_id="turn_t047_auto_degrade", span_id="span_t047_auto_degrade"),
            policy_context={},
            preferred_target="local",
        )
        data_dir = tempfile.mkdtemp(prefix="agentos_next_t047_auto_degrade_")
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "agentos_next.runtime.builtin_web.duckduckgo_html_search",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "variant": "lite",
                    "results": [{"title": "Apple Inc.", "snippet": "Quote and chart", "url": "https://example.com/aapl"}],
                    "attempts": [
                        {
                            "provider": "duckduckgo_html",
                            "variant": "html",
                            "status": "failed",
                            "error_code": "E_WEB_SEARCH_NO_RESULTS",
                            "detail": "DuckDuckGo HTML search only returned the DuckDuckGo homepage/search portal without usable results for query='AAPL stock'",
                        },
                        {"provider": "duckduckgo_html", "variant": "lite", "status": "ok"},
                    ],
                },
            ):
                out = maybe_execute_builtin_web(req=req, data_dir=data_dir)

        self.assertTrue(out.handled)
        self.assertEqual(out.result.status, "accepted")
        evidence = FileEvidenceStore(data_dir=data_dir)
        blob = evidence.get_blob(out.result.evidence_refs[-1].ref)
        assert blob is not None
        payload = json.loads(blob.content.decode("utf-8"))
        self.assertTrue(payload["degraded"])
        self.assertTrue(payload["expectation_mismatch"])
        self.assertEqual(payload["provider_used"], "duckduckgo_html")
        self.assertIn("notices", payload)
        self.assertEqual(payload["provider_attempts"][1]["variant"], "html")

    def test_probe_web_runtime_capability_disables_search_without_healthy_provider(self) -> None:
        _reset_search_provider_probe_cache()
        with patch(
            "agentos_next.runtime.builtin_web._probe_search_provider",
            side_effect=[
                {"available": False, "detail": "BRAVE_SEARCH_API_KEY is not configured"},
                {"available": False, "detail": "DuckDuckGo HTTP search returned no usable results"},
                {"available": False, "detail": "Browser-assisted search returned no usable results"},
            ],
        ), patch(
            "agentos_next.runtime.builtin_web.probe_playwright_runtime",
            return_value=PlaywrightProbeResult(available=True),
        ):
            probe = probe_web_runtime_capability(allow_network_egress=True)

        self.assertFalse(probe["web_search_enabled"])
        self.assertTrue(probe["web_browse_enabled"])
        self.assertEqual(probe["backends"]["available"], [])
        self.assertTrue(probe["strict_health_gate"])

    def test_probe_web_runtime_capability_allows_browser_fallback_provider(self) -> None:
        _reset_search_provider_probe_cache()
        with patch(
            "agentos_next.runtime.builtin_web._probe_search_provider",
            side_effect=[
                {"available": False, "detail": "BRAVE_SEARCH_API_KEY is not configured"},
                {"available": False, "detail": "DuckDuckGo HTTP search returned no usable results"},
                {"available": True, "detail": "available"},
            ],
        ), patch(
            "agentos_next.runtime.builtin_web.probe_playwright_runtime",
            return_value=PlaywrightProbeResult(available=True),
        ):
            probe = probe_web_runtime_capability(allow_network_egress=True)

        self.assertTrue(probe["web_search_enabled"])
        self.assertEqual(probe["backends"]["available"], ["playwright_search"])
        self.assertTrue(probe["web_browse_enabled"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
