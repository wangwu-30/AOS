"""LLM providers and clients.

This package is intentionally stdlib-only to keep the kernel skeleton lightweight.
"""

from .openai_codex_oauth import (  # noqa: F401
    OpenAICodexOAuthProvider,
    OpenAICodexOAuthTokenError,
    OpenAICodexOAuthTransportError,
    RemoteCallsDisabledError,
)

__all__ = [
    "OpenAICodexOAuthProvider",
    "OpenAICodexOAuthTokenError",
    "OpenAICodexOAuthTransportError",
    "RemoteCallsDisabledError",
    # backend exports (lazy to avoid import cycles)
    "CodexOAuthLLMBackend",
    "DoubaoArkLLMBackend",
    "MiniMaxLLMBackend",
    "LLMBackend",
    "LLMCallError",
    "LLMSafetyGate",
    "LocalMockLLMBackend",
    "RemoteLLMCallBudget",
    "is_remote_llm_backend",
]


def __getattr__(name: str):  # pragma: no cover
    # Lazily re-export backend symbols to avoid importing agentos_next.skills at package import time.
    if name in {
        "CodexOAuthLLMBackend",
        "DoubaoArkLLMBackend",
        "MiniMaxLLMBackend",
        "LLMBackend",
        "LLMCallError",
        "LLMSafetyGate",
        "LocalMockLLMBackend",
        "RemoteLLMCallBudget",
        "is_remote_llm_backend",
    }:
        from . import backend as _backend

        return getattr(_backend, name)
    raise AttributeError(name)
