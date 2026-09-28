"""SemanticChunkPlanner service — adaptive chunk boundaries for RAG ingestion.

The architect's SemanticChunkPlannerNode: instead of fixed-length splitting (which cuts tables
and lists mid-structure and degrades retrieval), plan chunk boundaries on semantic units. An
optional LLM proposes boundaries on ambiguous prose; the deterministic fallback groups the
Markdown blocks emitted by the parser, respecting a target chunk size. Pure functions, no state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TARGET_CHUNK_CHARS = 1_200
_MAX_BLOCKS_PER_CHUNK = 8


def _fallback_plan(blocks: list[str]) -> list[dict]:
    """Group consecutive Markdown blocks into chunks bounded by size + block count."""
    chunks: list[dict] = []
    start = 0
    cur_chars = 0
    cur_count = 0
    for i, block in enumerate(blocks):
        cur_chars += len(block)
        cur_count += 1
        is_heading = block.lstrip().startswith("#")
        boundary = (
            cur_chars >= _TARGET_CHUNK_CHARS or cur_count >= _MAX_BLOCKS_PER_CHUNK or (is_heading and cur_count > 1)
        )
        if boundary:
            end = i if is_heading and cur_count > 1 else i + 1
            if end > start:
                chunks.append({"start": start, "end": end, "label": f"chunk-{len(chunks)}"})
                start = end
                cur_chars = len(block) if (is_heading and cur_count > 1) else 0
                cur_count = 1 if (is_heading and cur_count > 1) else 0
    if start < len(blocks):
        chunks.append({"start": start, "end": len(blocks), "label": f"chunk-{len(chunks)}"})
    return chunks


def plan_chunks(parsed_documents: list[dict], llm=None) -> dict:
    """Return {doc_id -> [{start, end, label}]} chunk boundaries (block indices)."""
    chunk_plan: dict = {}
    for doc in parsed_documents:
        doc_id = doc["doc_id"]
        blocks = doc.get("blocks", [])
        if not blocks:
            chunk_plan[doc_id] = []
            continue

        plan: list[dict] | None = None
        if llm is not None:
            try:
                proposed = llm.plan_chunks(doc)  # adapter returns [{start,end,label}] or None
                if proposed:
                    plan = proposed
            except Exception as exc:
                logger.warning("SemanticChunkPlanner LLM failed for %s: %s — fallback", doc_id, exc)
        if plan is None:
            plan = _fallback_plan(blocks)
        chunk_plan[doc_id] = plan
    return chunk_plan
