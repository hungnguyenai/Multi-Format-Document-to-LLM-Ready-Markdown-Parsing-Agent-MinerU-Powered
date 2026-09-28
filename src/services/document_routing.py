"""DocumentRoutingDecision service — pick a MinerU parse profile per document.

The architect's DocumentRoutingDecisionNode: classify each input document by layout/format
characteristics and select the appropriate MinerU parse profile. An optional LLM resolves
ambiguous cases (e.g. a scanned PDF disguised as .docx) that a plain extension check cannot;
when no LLM is injected a deterministic format-map fallback is used so the pipeline is fully
testable without a live model. Pure functions, no state, no side effects.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Allowed input formats (anything else is rejected at routing).
SUPPORTED_FORMATS = {"pdf", "docx", "pptx", "xlsx", "image", "png", "jpg", "jpeg", "md", "txt"}

# Deterministic format → MinerU parse profile mapping.
_PROFILE_BY_FORMAT = {
    "pdf": "vlm_ocr_dual",  # multi-column / scanned — VLM layout + OCR
    "image": "ocr_only",
    "png": "ocr_only",
    "jpg": "ocr_only",
    "jpeg": "ocr_only",
    "pptx": "vlm_layout",  # embedded charts / slides
    "xlsx": "table_extract",  # merged-cell tables
    "docx": "structured_text",
    "md": "passthrough",
    "txt": "passthrough",
}


def _normalize_format(fmt: str, name: str) -> str:
    fmt = (fmt or "").lower().strip().lstrip(".")
    if fmt:
        return fmt
    # Fall back to the file extension when format is unset.
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    return ""


def plan_routing(documents: list[dict], llm=None) -> tuple[list[dict], list[dict]]:
    """Return (routing_plan, rejected_documents).

    routing_plan: [{doc_id, format, parse_profile, rationale}]
    rejected_documents: [{doc_id, reason}] for unsupported / unidentifiable formats.
    """
    routing_plan: list[dict] = []
    rejected: list[dict] = []

    for idx, doc in enumerate(documents):
        doc_id = doc.get("doc_id") or doc.get("name") or f"doc-{idx}"
        fmt = _normalize_format(doc.get("format", ""), doc.get("name", ""))

        if fmt not in SUPPORTED_FORMATS:
            rejected.append({"doc_id": doc_id, "reason": f"unsupported-format:{fmt or 'unknown'}"})
            continue

        profile = _PROFILE_BY_FORMAT.get(fmt, "structured_text")
        rationale = f"format={fmt} → profile={profile}"

        # Optional LLM refinement for ambiguous layouts (e.g. scanned content in a text container).
        if llm is not None:
            try:
                refined = llm.classify_route(doc)  # adapter returns {"parse_profile", "rationale"} or None
                if refined and refined.get("parse_profile"):
                    profile = refined["parse_profile"]
                    rationale = refined.get("rationale", rationale) + " (llm-refined)"
            except Exception as exc:  # best-effort; deterministic profile stands
                logger.warning("DocumentRouting LLM refine failed for %s: %s", doc_id, exc)

        routing_plan.append({"doc_id": doc_id, "format": fmt, "parse_profile": profile, "rationale": rationale})

    return routing_plan, rejected
