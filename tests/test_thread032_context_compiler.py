import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from agentos_next.kernel.context_compiler import (
    CompileContextKeys,
    CompileRefs,
    CompileRequest,
    ContextBudgets,
    MemoryQuery,
    RuntimeSnapshot,
    TaskIntent,
    compile_step_context,
)
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.memory_store import FileMemoryStore


class TestThread032ContextCompiler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="agentos_next_test_ctx_")
        self.data_dir = Path(self.test_dir)
        self.ev_store = FileEvidenceStore(self.data_dir)
        self.mem_store = FileMemoryStore(self.data_dir)

        # Setup Meta.Identity
        self.c0_ref = self.ev_store.add_text("IDENTITY: You are AgentOS Assistant", kind="policy")
        # Setup Meta.Operator Catalog
        self.c1_ref = self.ev_store.add_text("SKILLS: browse, python", kind="policy")
        
        # Setup C2 (Memory)
        self.m1_ref = self.ev_store.add_text("MEM1: User likes Python", kind="snapshot")
        self.mem_store.upsert_l1(evidence_ref=self.m1_ref.ref, tags=("ws_test_ws", "user_pref"))
        
        self.m2_ref = self.ev_store.add_text("MEM2: Project uses Rust", kind="snapshot")
        self.mem_store.upsert_l1(evidence_ref=self.m2_ref.ref, tags=("ws_test_ws", "project"))
        
        # Setup foreign workspace memory
        self.m_foreign = self.ev_store.add_text("FOREIGN: Secret data", kind="snapshot")
        self.mem_store.upsert_l1(evidence_ref=self.m_foreign.ref, tags=("ws_other_ws", "secret"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_base_req(self) -> CompileRequest:
        return CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_1", turn_id="tu_1", workspace_id="test_ws"),
            refs=CompileRefs(
                meta_identity_ref=self.c0_ref.ref,
                meta_operator_catalog_ref=self.c1_ref.ref,
                c0_identity_ref=self.c0_ref.ref,
                c1_capability_index_ref=self.c1_ref.ref,
            ),
            c2_memory_query=MemoryQuery(tags=("ws_test_ws",), limit=5),
            c3_runtime_snapshot=RuntimeSnapshot(budget_remaining=100),
            task_intent=TaskIntent(user_message="Do the task", actions_hint=("read",)),
            budgets=ContextBudgets(max_bytes_total=10000)
        )

    def test_01_deterministic(self):
        req = self._make_base_req()
        res1 = compile_step_context(req=req, data_dir=self.data_dir)
        res2 = compile_step_context(req=req, data_dir=self.data_dir)
        
        self.assertTrue(res1.ok)
        self.assertTrue(res2.ok)
        self.assertEqual(res1.compiled.c4_text, res2.compiled.c4_text)
        self.assertEqual(res1.selection_trace.decision_log, res2.selection_trace.decision_log)
        self.assertEqual(res1.selection_trace.violations, res2.selection_trace.violations)

    def test_02_replay_mode_zero_write(self):
        req = self._make_base_req()
        # normal mode
        res1 = compile_step_context(req=req, data_dir=self.data_dir)
        self.assertEqual(len(res1.evidence_refs), 1)
        
        # count files
        num_files_before = len(list(self.data_dir.rglob("*")))
        
        # replay mode
        req_replay = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_1", turn_id="tu_1", workspace_id="test_ws", replay_mode=True),
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=req.budgets
        )
        res2 = compile_step_context(req=req_replay, data_dir=self.data_dir)
        
        self.assertTrue(res2.ok)
        self.assertEqual(len(res2.evidence_refs), 0)
        
        num_files_after = len(list(self.data_dir.rglob("*")))
        self.assertEqual(num_files_before, num_files_after)

    def test_03_cross_workspace_leakage(self):
        req = self._make_base_req()
        # Querying a tag that matches the foreign workspace memory
        req_leak = CompileRequest(
            ctx=req.ctx,
            refs=req.refs,
            c2_memory_query=MemoryQuery(tags=("ws_other_ws",), limit=5),
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=req.budgets
        )
        
        res = compile_step_context(req=req_leak, data_dir=self.data_dir)
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_CTX_POLICY_VIOLATION")

    def test_04_c0_pinned(self):
        # We test that even if the budget is super small (e.g. 1 / not enough for C0)
        # the system will fail closed with BUDGET EXCEEDED, but never trim C0.
        req = self._make_base_req()
        req_tiny_budget = CompileRequest(
            ctx=req.ctx,
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=ContextBudgets(max_bytes_total=10) # very small
        )
        
        res = compile_step_context(req=req_tiny_budget, data_dir=self.data_dir)
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_CTX_BUDGET_EXCEEDED")

    def test_05_budget_trim_order(self):
        # We set budget just big enough for C0+C1+C3+intent, but not enough for C2
        req = self._make_base_req()
        res_normal = compile_step_context(req=req, data_dir=self.data_dir)
        total_normal = res_normal.compiled.usage_bytes.total
        c2_size = res_normal.compiled.usage_bytes.c2
        
        # This budget is enough for everything EXCEPT C2
        req_trim = CompileRequest(
            ctx=req.ctx,
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=ContextBudgets(max_bytes_total=total_normal - (c2_size // 2))
        )
        
        res = compile_step_context(req=req_trim, data_dir=self.data_dir)
        self.assertTrue(res.ok)
        self.assertEqual(res.compiled.usage_bytes.c2, 0) # C2 trimmed
        self.assertTrue(any("Trimming L1" in x for x in res.selection_trace.decision_log))

    def test_06_goldilocks_output(self):
        req = self._make_base_req()
        res = compile_step_context(req=req, data_dir=self.data_dir)
        
        self.assertTrue(res.ok)
        gl = res.compiled.goldilocks
        self.assertTrue(0.0 <= gl.usage_ratio <= 1.0)
        self.assertIn(gl.status, ("under", "optimal", "over"))

    def test_07_append_only_violation_evidence(self):
        req = self._make_base_req()
        req_squash = CompileRequest(
            ctx=req.ctx,
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=req.budgets,
            policy_context_passthrough={"squash_history": True}
        )
        
        # execution in normal mode
        res1 = compile_step_context(req=req_squash, data_dir=self.data_dir)
        self.assertTrue(res1.ok)
        self.assertTrue(any(v.code == "append_only_violation" for v in res1.selection_trace.violations))
        self.assertEqual(len(res1.evidence_refs), 1)
        
        # execution in replay mode
        req_squash_replay = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_1", turn_id="tu_1", workspace_id="test_ws", replay_mode=True),
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=req.budgets,
            policy_context_passthrough={"squash_history": True}
        )
        res2 = compile_step_context(req=req_squash_replay, data_dir=self.data_dir)
        self.assertTrue(res2.ok)
        self.assertTrue(any(v.code == "append_only_violation" for v in res2.selection_trace.violations))
        self.assertEqual(len(res2.evidence_refs), 0)

    def test_08_selection_trace_consistency(self):
        req = self._make_base_req()
        res = compile_step_context(req=req, data_dir=self.data_dir)
        
        self.assertTrue(res.ok)
        # Check that the selected refs are in the trace and the JSON is stable
        self.assertIn("c0", res.compiled.selected_refs)
        self.assertIn("c1", res.compiled.selected_refs)
        self.assertIn("meta_identity", res.compiled.selected_refs)
        self.assertIn("meta_operator_catalog", res.compiled.selected_refs)
        self.assertEqual(res.compiled.selected_refs["c0"], self.c0_ref.ref)

    def test_09_replay_mode_strict_no_mkdir(self):
        from unittest.mock import patch
        
        req = self._make_base_req()
        req_replay = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_1", turn_id="tu_1", workspace_id="test_ws", replay_mode=True),
            refs=req.refs,
            c2_memory_query=req.c2_memory_query,
            c3_runtime_snapshot=req.c3_runtime_snapshot,
            task_intent=req.task_intent,
            budgets=req.budgets
        )
        
        # Patch Path.mkdir to raise an exception unconditionally
        with patch("pathlib.Path.mkdir", side_effect=RuntimeError("mkdir is strictly prohibited in replay mode")):
            # 1. Test when directories exist (should succeed without mkdir)
            res1 = compile_step_context(req=req_replay, data_dir=self.data_dir)
            self.assertTrue(res1.ok)
            
            # 2. Test when directories are completely missing (should fail closed with E_CTX_REPLAY_DENY)
            empty_dir = Path(tempfile.mkdtemp(prefix="agentos_next_empty_"))
            try:
                res2 = compile_step_context(req=req_replay, data_dir=empty_dir)
                self.assertFalse(res2.ok)
                self.assertEqual(res2.error_code, "E_CTX_REPLAY_DENY")
            finally:
                shutil.rmtree(empty_dir, ignore_errors=True)

    def test_10_c2_query_relevance_ranking_prefers_match(self):
        older = self.ev_store.add_text("MEM3: remind water after 10 minutes", kind="snapshot")
        newer = self.ev_store.add_text("MEM4: user likes dark theme", kind="snapshot")
        self.mem_store.upsert_l1(
            evidence_ref=older.ref,
            tags=("ws_test_ws", "misc"),
            created_at="2026-03-04T08:00:00Z",
        )
        self.mem_store.upsert_l1(
            evidence_ref=newer.ref,
            tags=("ws_test_ws", "misc"),
            created_at="2026-03-05T08:00:00Z",
        )

        req = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_rel", turn_id="tu_rel", workspace_id="test_ws"),
            refs=CompileRefs(
                meta_identity_ref=self.c0_ref.ref,
                meta_operator_catalog_ref=self.c1_ref.ref,
                c0_identity_ref=self.c0_ref.ref,
                c1_capability_index_ref=self.c1_ref.ref,
            ),
            c2_memory_query=MemoryQuery(tags=("ws_test_ws",), query="remind water", limit=1),
            c3_runtime_snapshot=RuntimeSnapshot(budget_remaining=100),
            task_intent=TaskIntent(user_message="Do reminder task"),
            budgets=ContextBudgets(max_bytes_total=10000),
        )
        res = compile_step_context(req=req, data_dir=self.data_dir)
        self.assertTrue(res.ok)
        self.assertEqual(res.compiled.selected_refs.get("c2_0"), older.ref)

    def test_11_c2_prefers_fresh_records_before_stale_fallback(self):
        fresh = self.ev_store.add_text("MEM5: deploy checklist current sprint", kind="snapshot")
        stale = self.ev_store.add_text("MEM6: deploy checklist from last year", kind="snapshot")
        self.mem_store.upsert_l1(
            evidence_ref=fresh.ref,
            tags=("ws_test_ws", "deploy"),
            created_at="2026-03-07T08:00:00Z",
        )
        self.mem_store.upsert_l1(
            evidence_ref=stale.ref,
            tags=("ws_test_ws", "deploy"),
            created_at="2025-01-01T08:00:00Z",
        )

        req = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_fresh", turn_id="tu_fresh", workspace_id="test_ws"),
            refs=CompileRefs(
                meta_identity_ref=self.c0_ref.ref,
                meta_operator_catalog_ref=self.c1_ref.ref,
                c0_identity_ref=self.c0_ref.ref,
                c1_capability_index_ref=self.c1_ref.ref,
            ),
            c2_memory_query=MemoryQuery(
                tags=("ws_test_ws", "deploy"),
                query="deploy checklist",
                limit=1,
                freshness_window_seconds=86400 * 14,
            ),
            c3_runtime_snapshot=RuntimeSnapshot(),
            task_intent=TaskIntent(user_message="deploy checklist"),
            budgets=ContextBudgets(max_bytes_total=10000),
        )
        res = compile_step_context(req=req, data_dir=self.data_dir)
        self.assertTrue(res.ok)
        self.assertEqual(res.compiled.selected_refs.get("c2_0"), fresh.ref)
        self.assertFalse(any("tier=stale" in x for x in res.selection_trace.decision_log))

    def test_12_c2_uses_stale_fallback_when_active_context_insufficient(self):
        stale = self.ev_store.add_text("MEM7: meituan project notes from last quarter", kind="snapshot")
        self.mem_store.upsert_l1(
            evidence_ref=stale.ref,
            tags=("ws_test_ws", "meituan"),
            created_at="2025-01-01T08:00:00Z",
        )

        req = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_stale", turn_id="tu_stale", workspace_id="test_ws"),
            refs=CompileRefs(
                meta_identity_ref=self.c0_ref.ref,
                meta_operator_catalog_ref=self.c1_ref.ref,
                c0_identity_ref=self.c0_ref.ref,
                c1_capability_index_ref=self.c1_ref.ref,
            ),
            c2_memory_query=MemoryQuery(
                tags=("ws_test_ws", "meituan"),
                query="meituan project",
                limit=1,
                freshness_window_seconds=86400 * 14,
                include_stale_fallback=True,
            ),
            c3_runtime_snapshot=RuntimeSnapshot(),
            task_intent=TaskIntent(user_message="meituan project"),
            budgets=ContextBudgets(max_bytes_total=10000),
        )
        res = compile_step_context(req=req, data_dir=self.data_dir)
        self.assertTrue(res.ok)
        self.assertEqual(res.compiled.selected_refs.get("c2_0"), stale.ref)
        self.assertIn("[stale memory - verify freshness]", res.compiled.c4_text)
        self.assertTrue(any("tier=stale" in x for x in res.selection_trace.decision_log))

    def test_13_c2_uses_tombstoned_fallback_last(self):
        tomb = self.ev_store.add_text("MEM8: accidentally deleted roadmap summary", kind="snapshot")
        self.mem_store.upsert_l1(
            evidence_ref=tomb.ref,
            tags=("ws_test_ws", "roadmap"),
            created_at="2026-03-05T08:00:00Z",
        )
        self.mem_store.tombstone_l1(evidence_ref=tomb.ref)

        req = CompileRequest(
            ctx=CompileContextKeys(trace_id="tr_tomb", turn_id="tu_tomb", workspace_id="test_ws"),
            refs=CompileRefs(
                meta_identity_ref=self.c0_ref.ref,
                meta_operator_catalog_ref=self.c1_ref.ref,
                c0_identity_ref=self.c0_ref.ref,
                c1_capability_index_ref=self.c1_ref.ref,
            ),
            c2_memory_query=MemoryQuery(
                tags=("ws_test_ws", "roadmap"),
                query="roadmap summary",
                limit=1,
                include_tombstoned_fallback=True,
            ),
            c3_runtime_snapshot=RuntimeSnapshot(),
            task_intent=TaskIntent(user_message="roadmap summary"),
            budgets=ContextBudgets(max_bytes_total=10000),
        )
        res = compile_step_context(req=req, data_dir=self.data_dir)
        self.assertTrue(res.ok)
        self.assertEqual(res.compiled.selected_refs.get("c2_0"), tomb.ref)
        self.assertIn("[soft-deleted memory fallback - verify before use]", res.compiled.c4_text)
        self.assertTrue(any("tier=tombstoned" in x for x in res.selection_trace.decision_log))
