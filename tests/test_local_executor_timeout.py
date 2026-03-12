import asyncio
import unittest
from unittest.mock import MagicMock, patch
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.runtime.package_runner import PackageRunner, PackageRunResult, PackageRunRequest
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.types import TraceContext

class TestLocalExecutorTimeout(unittest.IsolatedAsyncioTestCase):
    async def test_execute_enforces_deadline(self):
        # Mock PackageRunner to simulate a slow execution
        mock_runner = MagicMock(spec=PackageRunner)
        
        def slow_run(*args, **kwargs):
            import time
            time.sleep(0.5) # Sleep 500ms
            res = MagicMock(spec=PackageRunResult)
            res.ok = True # needed for conversion
            res.error_code = None
            res.evidence_refs = ()
            return res

        mock_runner.run.side_effect = slow_run
        
        executor = LocalExecutor(runner=mock_runner)
        
        # Create a request with a short deadline (100ms)
        req = ExecuteRequest(
            skill_ref="dummy",
            input={},
            workspace_id="ws_test",
            trace=TraceContext(trace_id="t", turn_id="tu", span_id="s"),
            deadline_ms=100, # 100ms deadline
            idempotency_key="k1",
            policy_context={}
        )

        # Expect execution to fail with E_TIMEOUT
        result = await executor.execute(req)
        
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error_code, "E_TIMEOUT")
        self.assertEqual(result.target, "local")

    async def test_execute_completes_within_deadline(self):
        # Mock PackageRunner to be fast
        mock_runner = MagicMock(spec=PackageRunner)
        
        # Create a proper PackageRunResult to return
        mock_pkg_result = MagicMock(spec=PackageRunResult)
        mock_pkg_result.ok = True
        mock_pkg_result.output = {"ok": True}
        mock_pkg_result.error_code = None
        mock_pkg_result.evidence_refs = ()
        mock_pkg_result.trace = MagicMock()

        mock_runner.run.return_value = mock_pkg_result
        
        executor = LocalExecutor(runner=mock_runner)
        
        # Request with ample deadline
        req = ExecuteRequest(
            skill_ref="dummy",
            input={},
            workspace_id="ws_test",
            trace=TraceContext(trace_id="t", turn_id="tu", span_id="s"),
            deadline_ms=1000,
            idempotency_key="k2",
            policy_context={}
        )

        result = await executor.execute(req)
        
        self.assertEqual(result.status, "accepted")
        # ExecuteResult does not have 'output' field, it is in evidence.

    async def test_execute_runner_exception_is_fail_closed(self):
        mock_runner = MagicMock(spec=PackageRunner)
        mock_runner.run.side_effect = RuntimeError("boom")

        executor = LocalExecutor(runner=mock_runner)
        req = ExecuteRequest(
            skill_ref="dummy",
            input={},
            workspace_id="ws_test",
            trace=TraceContext(trace_id="t", turn_id="tu", span_id="s"),
            deadline_ms=1000,
            idempotency_key="k3",
            policy_context={}
        )

        result = await executor.execute(req)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "E_EXECUTION_FAILED")
        self.assertEqual(result.target, "local")

if __name__ == "__main__":
    unittest.main()
