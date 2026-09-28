"""MinerU 3.1.0 adapter — real VLM+OCR dual-engine extraction behind the parser interface.

The MainNode parse service expects a `parser` object exposing
`parse(doc, profile) -> {"markdown", "blocks"}`. This adapter wraps the MinerU runtime (a heavy
optional dependency, Apache 2.0, NOT installed in CI). To keep the adapter unit-testable and the
pipeline CI-green without MinerU, the low-level engine is injected as `client`:

  - `client` provided  → tests / explicit wiring pass a fake or a pre-built MinerU engine.
  - `client` is None   → the adapter lazily imports + builds the real MinerU engine; if MinerU
                          is not installed it raises ImportError at construction, so the factory
                          declines to wire it and the service uses its deterministic fallback.

This module imports no framework symbols — `client` is duck-typed.
"""

from __future__ import annotations

from typing import Any

import logging

logger = logging.getLogger(__name__)

# MinerU parse profile → engine mode hint.
_PROFILE_MODE = {
    "vlm_ocr_dual": "vlm+ocr",
    "ocr_only": "ocr",
    "vlm_layout": "vlm",
    "table_extract": "table",
    "structured_text": "text",
    "passthrough": "text",
}


def _build_real_engine(options: dict):
    """Lazily construct the real MinerU engine. Raises ImportError if MinerU is unavailable."""
    import mineru  # noqa: F401 — presence check; not installed in CI

    # The concrete engine entry point is resolved at deploy time; kept thin on purpose.
    return mineru.build_engine(**options)  # type: ignore[attr-defined]


class MinerUAdapter:
    """Adapter over the MinerU VLM+OCR engine, exposing `parse(doc, profile)`."""

    def __init__(self, client: Any = None, options: dict | None = None) -> None:
        self._options = options or {}
        # Build the real engine only when no client is injected; raises if MinerU is absent.
        self._client = client if client is not None else _build_real_engine(self._options)

    def parse(self, doc: dict, profile: str) -> dict:
        """Return {"markdown", "blocks"} from MinerU for one document under the given profile."""
        mode = _PROFILE_MODE.get(profile, "text")
        source = doc.get("path") or doc.get("content") or ""
        result = self._client.to_markdown(source, mode=mode)

        # Normalize the engine result into the parser contract.
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
            blocks = result.get("blocks") or [b for b in markdown.split("\n\n") if b.strip()]
        else:
            markdown = str(result)
            blocks = [b for b in markdown.split("\n\n") if b.strip()]
        return {"markdown": markdown, "blocks": blocks}
