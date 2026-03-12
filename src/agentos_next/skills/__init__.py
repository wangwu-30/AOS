"""Skill package loading and execution.

This package is stdlib-only. YAML parsing is supported via `agentos_next.compiler.skill_contract`,
which can fall back to JSON-only `.skill` files when PyYAML isn't installed.
"""

# Intentionally avoid re-exporting submodules here.
#
# Reason: `agentos_next.llm.backend` imports `agentos_next.skills.jsonschema_subset`.
# Importing a submodule requires importing this package, so any eager imports here can
# create circular import chains (e.g. skills -> llm_execution -> llm.backend -> skills).
