"""Personal Assistant (PA) application layer primitives.

These modules are *not* kernel governance primitives. They build on top of:
- Orchestrator/Executor API
- Kernel PEP/PDP (policy_engine)
- Evidence/Trace stores

Non-negotiables are inherited from the kernel:
- top_level_api_stable
- fail_closed
- replay_mode_no_side_effects
"""

