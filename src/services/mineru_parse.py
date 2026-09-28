"""MinerU parse service — deterministic multi-format extraction to Markdown.

The architect's deterministic extraction step: MinerU 3.1.0 VLM+OCR dual engine converts each
routed document into Markdown (preserving headings, tables, lists). MinerU itself is a heavy
optional runtime dependency that is NOT installed in CI, so it is injected as an adapter
(`parser`) via graph config. When no adapter is injected, a deterministic fallback treats the
inline `content` field as already-extracted text/Markdown — this keeps the whole pipeline
exercisable without a live MinerU install. Pure functions, no state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_CHARS_DEFAULT = 200_000  # hard cap so a giant document can't blow up state


def _fallback_extract(doc: dict, max_chars: int) -> dict:
    """Deterministic extraction: use inline content (already text/markdown) bounded by max_chars."""
    content = doc.get("content", "") or ""
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + "\n...[truncated]...\n"
    # Count rough markdown block structure for downstream chunk planning.
    blocks = [b for b in content.split("\n\n") if b.strip()]
    return {"markdown": content, "blocks": blocks, "parser": "fallback", "truncated": truncated}


def parse_documents(
    routing_plan: list[dict],
    doc_index: dict,
    parser=None,
    max_doc_size_kb: int = 5_000,
) -> list[dict]:
    """Return parsed_documents: [{doc_id, markdown, blocks, parser, profile}].

    routing_plan : output of plan_routing (only routed/accepted docs).
    doc_index    : {doc_id -> raw document descriptor} for content lookup.
    parser       : optional MinerU adapter exposing parse(doc, profile) -> {"markdown", "blocks"}.
    """
    max_chars = max(1, max_doc_size_kb) * 1024
    parsed: list[dict] = []

    for route in routing_plan:
        doc_id = route["doc_id"]
        profile = route.get("parse_profile", "structured_text")
        doc = doc_index.get(doc_id, {})

        extracted: dict
        if parser is not None:
            try:
                result = parser.parse(doc, profile) or {}
                md = result.get("markdown", "")
                extracted = {
                    "markdown": md,
                    "blocks": result.get("blocks") or [b for b in md.split("\n\n") if b.strip()],
                    "parser": "mineru",
                    "truncated": False,
                }
            except Exception as exc:  # never silent — fall back deterministically
                logger.warning("MinerU parse failed for %s (profile=%s): %s — fallback", doc_id, profile, exc)
                extracted = _fallback_extract(doc, max_chars)
        else:
            extracted = _fallback_extract(doc, max_chars)

        parsed.append({"doc_id": doc_id, "profile": profile, **extracted})

    return parsed
