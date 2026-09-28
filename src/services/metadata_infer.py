"""AmbiguousMetadataInference service — infer title / doc_type for borderline documents.

The architect's AmbiguousMetadataInferenceNode: many enterprise documents carry no reliable
embedded metadata (scanned board resolutions, exported slides). An optional LLM infers a title
and document type with a confidence score; the deterministic fallback derives a title from the
first Markdown heading and a doc_type from the parse profile. Pure functions, no state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PROFILE_TO_DOCTYPE = {
    "vlm_ocr_dual": "scanned_or_complex_pdf",
    "ocr_only": "image_document",
    "vlm_layout": "presentation",
    "table_extract": "spreadsheet",
    "structured_text": "office_document",
    "passthrough": "plain_text",
}


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
        if s:
            return s[:80]
    return ""


def _fallback_infer(doc: dict) -> dict:
    title = _first_heading(doc.get("markdown", "")) or doc["doc_id"]
    doc_type = _PROFILE_TO_DOCTYPE.get(doc.get("profile", ""), "unknown")
    return {"title": title, "doc_type": doc_type, "confidence": 0.5, "source": "heuristic"}


def infer_metadata(parsed_documents: list[dict], llm=None) -> dict:
    """Return {doc_id -> {title, doc_type, confidence, source}}."""
    inferred: dict = {}
    for doc in parsed_documents:
        doc_id = doc["doc_id"]
        meta: dict | None = None
        if llm is not None:
            try:
                proposed = llm.infer_metadata(doc)  # adapter returns {title, doc_type, confidence} or None
                if proposed and proposed.get("title"):
                    meta = {**proposed, "source": "llm"}
            except Exception as exc:
                logger.warning("MetadataInference LLM failed for %s: %s — fallback", doc_id, exc)
        if meta is None:
            meta = _fallback_infer(doc)
        inferred[doc_id] = meta
    return inferred
