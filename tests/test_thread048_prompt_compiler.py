from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from agentos_next.kernel.context_graph import build_context_graph_v1, build_task_context_views_v1
from agentos_next.kernel.prompt_compiler import compile_prompt_bundle_v1
from agentos_next.kernel.soul_profile import validate_soul_profile_v1


class TestThread048PromptCompiler(unittest.TestCase):
    def test_validate_legacy_soul_profile_upgrades_to_layered_runtime_packs(self) -> None:
        normalized, err = validate_soul_profile_v1(
            {
                "schema_version": "1.0.0",
                "soul_profile_id": "legacy",
                "name": "Legacy",
                "identity_summary": "legacy assistant",
                "principles": ["be helpful"],
                "communication_defaults": {
                    "tone": "direct",
                    "verbosity": "concise",
                    "style": ["clear", "honest", "concise"],
                },
                "boundary_rules": ["do not bluff"],
            }
        )
        self.assertIsNone(err)
        assert normalized is not None
        self.assertEqual(normalized["schema_version"], "2.0.0")
        self.assertEqual(normalized["global_soul"]["identity_summary"], "legacy assistant")
        self.assertIn("task_processing_axioms", normalized["role_axioms"])
        self.assertIn("concise", normalized["style_packs"])
        self.assertIn("scientific_hypothesis_mode", normalized["doctrine_packs"])
        self.assertIn("browser_research_mode", normalized["doctrine_packs"])
        self.assertIn("self_adversarial_mode", normalized["doctrine_packs"])

    def test_context_graph_and_prompt_bundle_cover_all_profiles(self) -> None:
        soul_profile, err = validate_soul_profile_v1(
            {
                "schema_version": "1.0.0",
                "soul_profile_id": "legacy",
                "name": "Legacy",
                "identity_summary": "legacy assistant",
                "principles": ["be helpful"],
                "communication_defaults": {
                    "tone": "direct",
                    "verbosity": "concise",
                    "style": ["clear", "honest", "concise"],
                },
                "boundary_rules": ["do not bluff"],
            }
        )
        self.assertIsNone(err)
        assert soul_profile is not None
        agent_profile = {
            "agent_id": "assistant_loop",
            "execution_axioms": [
                {"id": "AX1", "statement": "verify before done", "priority": 0},
            ],
            "communication_axioms": [
                {"id": "AX2", "statement": "keep style separate from facts", "priority": 0},
            ],
        }
        context_planes = {
            "execution_plane": {
                "state_summary": "workspace=ws turn=turn_1 query=分析项目",
                "evidence_refs": ["ev_a"],
                "message_received_at_utc": "2026-03-08T08:00:00Z",
                "project_capsule": {"project_id": "proj", "title": "Proj", "summary": "project summary", "evidence_refs": ["ev_proj"]},
            },
            "communication_plane": {
                "role_hint": "assistant",
                "style_constraints": ["formal"],
                "soul_profile_id": "legacy",
                "global_capsule": {"identity_summary": "legacy assistant", "communication_style": ["clear", "honest", "concise"]},
                "communication_style": ["clear", "honest", "concise"],
            },
            "retrospective_plane": {
                "recent_failures": ["mode=standard; objective=old hypothesis"],
                "recent_success_patterns": ["inspect workspace before concluding"],
            },
            "constraint_plane": {
                "execution_axiom_ids": ["AX1"],
                "communication_axiom_ids": ["AX2"],
                "active_axiom_ids": ["AX1"],
                "active_constraint_ids": ["RC1"],
            },
            "intent_recovery_plane": {
                "active_project_id": "proj",
                "last_pending_task": "分析项目",
                "expected_next_user_act": "followup_or_new_task",
                "last_clarification_question": None,
                "last_delivery_state": "done",
                "last_delivery_summary": "delivery verified successfully",
                "pending_contract": {"objective": "分析项目"},
                "blocker": None,
            },
        }
        task_envelope = {
            "task_id": "task_1",
            "objective": "分析项目",
            "deliverable": "workspace_analysis",
            "known_facts": ["need workspace evidence"],
            "open_questions": ["which modules changed recently"],
            "constraints": ["no speculation without evidence"],
            "acceptance_criteria": ["cite observations"],
        }
        delivery_contract = {
            "done_definition": "cite workspace observations and summarize risks",
            "verification_requirements": ["fresh workspace observations"],
        }
        task_requirements = {
            "requires_workspace_observation": True,
            "requires_external_evidence": False,
            "requires_multi_step_plan": True,
            "forbid_speculation_without_evidence": True,
        }
        solution_query = {
            "resolved_objective": "分析项目",
            "approach_strategy": "local_skill_first",
            "continuity_binding": "pending_contract",
            "retrieved_theorem_ids": ["thm.inspect_first"],
            "retrieved_theorem_summaries": ["inspect workspace before concluding"],
        }
        intent_recovery = {"intent_option": "FOLLOWUP_PENDING"}
        context_graph = build_context_graph_v1(
            query_text="分析项目",
            workspace_id="ws",
            trace_id="tr",
            turn_id="turn_1",
            task_envelope=task_envelope,
            context_planes=context_planes,
            task_requirements=task_requirements,
            solution_query=solution_query,
            intent_recovery=intent_recovery,
            interaction_mode="task",
            agent_profile=agent_profile,
            soul_profile=soul_profile,
        )
        self.assertEqual(context_graph["type"], "context_graph_v1")
        self.assertIn("project_work", context_graph["domain_tags"])
        views = build_task_context_views_v1(
            context_graph=context_graph,
            task_envelope=task_envelope,
            delivery_contract=delivery_contract,
            context_planes=context_planes,
            task_requirements=task_requirements,
            solution_query=solution_query,
            intent_recovery=intent_recovery,
            interaction_mode="task",
        )
        self.assertEqual(sorted(views["views"].keys()), [
            "communicator",
            "executor",
            "intent_router",
            "planner",
            "verifier_replanner",
        ])
        prompt_bundle = compile_prompt_bundle_v1(
            agent_profile=agent_profile,
            soul_profile=soul_profile,
            context_planes=context_planes,
            context_graph=context_graph,
            task_context_views=views,
            interaction_mode="task",
            mode="standard",
            task_requirements=task_requirements,
            solution_query=solution_query,
            response_language="zh-CN",
        )
        self.assertEqual(prompt_bundle["type"], "prompt_compilation_v1")
        self.assertEqual(prompt_bundle["active_style_pack"]["pack_id"], "formal")
        self.assertEqual(prompt_bundle["active_response_language"], "zh-CN")
        self.assertEqual(prompt_bundle["active_doctrine_pack"]["pack_id"], "scientific_hypothesis_mode")
        self.assertEqual(sorted(prompt_bundle["profiles"].keys()), [
            "communicator",
            "executor",
            "intent_router",
            "planner",
            "verifier_replanner",
        ])
        self.assertIn("PROMPT_PROFILE=executor", prompt_bundle["profiles"]["executor"]["reasoning_prompt"])
        self.assertIn("PROFILE_ID=communicator", prompt_bundle["profiles"]["communicator"]["reasoning_prompt"])
        self.assertIn("RESPONSE_LANGUAGE=zh-CN", prompt_bundle["profiles"]["communicator"]["reasoning_prompt"])

    def test_prompt_bundle_prefers_explicit_research_doctrine_pack(self) -> None:
        soul_profile, err = validate_soul_profile_v1(
            {
                "schema_version": "2.0.0",
                "soul_profile_id": "research",
                "name": "Research",
                "identity_summary": "research assistant",
                "principles": ["be helpful"],
                "communication_defaults": {
                    "tone": "direct",
                    "verbosity": "concise",
                    "style": ["clear", "honest", "concise"],
                },
                "boundary_rules": ["do not bluff"],
                "doctrine_packs": {
                    "browser_research_mode": {
                        "summary": "search then browse then cite",
                        "steps": ["search", "browse", "cite"],
                        "verification_required": True,
                    }
                },
            }
        )
        self.assertIsNone(err)
        assert soul_profile is not None
        agent_profile = {
            "agent_id": "assistant_loop",
            "execution_axioms": [{"id": "AX1", "statement": "verify first", "priority": 0}],
            "communication_axioms": [{"id": "AX2", "statement": "stay truthful", "priority": 0}],
        }
        context_planes = {
            "execution_plane": {"state_summary": "research", "evidence_refs": [], "message_received_at_utc": None},
            "communication_plane": {"role_hint": "assistant", "style_constraints": []},
            "retrospective_plane": {"recent_failures": [], "recent_success_patterns": []},
            "constraint_plane": {"execution_axiom_ids": ["AX1"], "communication_axiom_ids": ["AX2"], "active_axiom_ids": ["AX1"], "active_constraint_ids": []},
            "intent_recovery_plane": {},
        }
        task_envelope = {
            "task_id": "task_research",
            "objective": "比较多个来源",
            "deliverable": "user_visible_answer",
            "known_facts": [],
            "open_questions": [],
            "constraints": [],
            "acceptance_criteria": ["preserve citations"],
        }
        delivery_contract = {"done_definition": "answer with citations", "verification_requirements": ["citation set"]}
        task_requirements = {
            "requires_workspace_observation": False,
            "requires_external_evidence": True,
            "requires_multi_step_plan": True,
            "forbid_speculation_without_evidence": True,
            "research_required": True,
            "research_depth": "standard",
            "selected_doctrine_pack": "browser_research_mode",
            "evidence_expectation": "research_citation_set",
            "citation_required": True,
            "self_adversarial_required": False,
        }
        solution_query = {"resolved_objective": "比较多个来源", "approach_strategy": "evidence_first"}
        context_graph = build_context_graph_v1(
            query_text="比较多个来源",
            workspace_id="ws",
            trace_id="tr",
            turn_id="turn",
            task_envelope=task_envelope,
            context_planes=context_planes,
            task_requirements=task_requirements,
            solution_query=solution_query,
            intent_recovery={},
            interaction_mode="task",
            agent_profile=agent_profile,
            soul_profile=soul_profile,
        )
        views = build_task_context_views_v1(
            context_graph=context_graph,
            task_envelope=task_envelope,
            delivery_contract=delivery_contract,
            context_planes=context_planes,
            task_requirements=task_requirements,
            solution_query=solution_query,
            intent_recovery={},
            interaction_mode="task",
        )
        prompt_bundle = compile_prompt_bundle_v1(
            agent_profile=agent_profile,
            soul_profile=soul_profile,
            context_planes=context_planes,
            context_graph=context_graph,
            task_context_views=views,
            interaction_mode="task",
            mode="complex",
            task_requirements=task_requirements,
            solution_query=solution_query,
            response_language="zh-CN",
        )
        self.assertEqual(prompt_bundle["active_doctrine_pack"]["pack_id"], "browser_research_mode")
        communicator_prompt = prompt_bundle["profiles"]["communicator"]["reasoning_prompt"]
        self.assertIn("DOCTRINE_PACK=browser_research_mode", communicator_prompt)
        self.assertIn("citation_required=True", communicator_prompt)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
