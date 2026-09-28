"""Unified adapter factory for CMN-C1-127.

Centralizes construction of the LLM and MinerU adapters so the nodes stay thin and the
secret/trust resolution lives in one place:

  - build_llm_adapter(raw_llm, state) — wrap a raw framework LLM in LLMAdapter.
    Returns None when no LLM is available, so every decision falls back deterministically.
    No key is resolved here: the client arrives with its credentials already bound
    (src/services/llm_factory.py builds it from the invocation secrets).
  - build_parser(config) — return the injected `parser`, or lazily build a MinerUAdapter when
    `enable_mineru` is set; returns None if MinerU is unavailable (CI) so the parse step falls
    back to the deterministic inline-content extractor.

The framework import is lazy (inside the function) so this module is importable — and
build_parser unit-testable — without the framework present.
"""

from __future__ import annotations

import logging

from src.adapters.llm_adapter import LLMAdapter
from src.adapters.mineru_adapter import MinerUAdapter

logger = logging.getLogger(__name__)


def build_llm_adapter(raw_llm, state) -> LLMAdapter | None:
    """Wrap a raw LLM in LLMAdapter. Returns None when there is no LLM to wrap.

    `state` is kept in the signature so the call sites are unchanged; it is no
    longer read, because the key is bound into the client at construction."""
    if raw_llm is None:
        return None
    # No key is resolved here any more: the client is built with its credentials
    # already bound (src/services/llm_factory.py). api_key stays in the adapter's
    # signature so its call sites are unchanged.
    return LLMAdapter(raw_llm, api_key=None)


def build_parser(config: dict):
    """Return a parser adapter for MainNode, or None to use the deterministic fallback."""
    config = config or {}
    injected = config.get("parser")
    if injected is not None:
        return injected
    if not config.get("enable_mineru"):
        return None
    try:
        return MinerUAdapter(options=config.get("mineru_options"))
    except ImportError:
        logger.warning("MinerU not installed — MainNode will use the deterministic fallback")
        return None
