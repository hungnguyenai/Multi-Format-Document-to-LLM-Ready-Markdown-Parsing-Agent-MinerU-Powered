"""ParseQualityJudge service — NON-SUPPRESSIBLE extraction-quality scoring.

The architect's ParseQualityJudgeNode: score each parsed document for extraction quality (OCR
garble, layout collapse, empty output) so low-quality results can be flagged for reparse or
human review rather than silently degrading downstream RAG. An optional LLM grades nuanced
cases; the deterministic fallback uses cheap signals (non-empty, printable ratio, block count).
The judge is non-suppressible — the caller always records quality_judge_executed=True. Pure
functions, no state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.6
_REVIEW_THRESHOLD = 0.4


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(1 for c in text if c.isprintable() or c in "\n\t")
    return printable / len(text)


def _fallback_score(doc: dict) -> float:
    md = doc.get("markdown", "") or ""
    if not md.strip():
        return 0.0
    ratio = _printable_ratio(md)
    block_signal = min(len(doc.get("blocks", [])) / 3.0, 1.0)
    # Weighted: text legibility dominates, structure is a secondary signal.
    return round(0.7 * ratio + 0.3 * block_signal, 3)


def _verdict(score: float) -> str:
    if score >= _PASS_THRESHOLD:
        return "pass"
    if score >= _REVIEW_THRESHOLD:
        return "human_review"
    return "reparse"


def judge_quality(parsed_documents: list[dict], llm=None) -> tuple[dict, bool]:
    """Return ({doc_id -> {score, verdict}}, executed=True). executed is always True
    (anti-suppression invariant — the quality gate can never be configured away)."""
    quality_report: dict = {}
    for doc in parsed_documents:
        doc_id = doc["doc_id"]
        score: float | None = None
        if llm is not None:
            try:
                graded = llm.judge_quality(doc)  # adapter returns {"score": float} or None
                if graded and isinstance(graded.get("score"), (int, float)):
                    score = float(graded["score"])
            except Exception as exc:
                logger.warning("ParseQualityJudge LLM failed for %s: %s — fallback", doc_id, exc)
        if score is None:
            score = _fallback_score(doc)
        quality_report[doc_id] = {"score": score, "verdict": _verdict(score)}
    return quality_report, True
