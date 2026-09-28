"""Output render service — assemble the LLM-ready Markdown / JSON payload.

Combines per-document Markdown, the semantic chunk plan, inferred metadata, and the quality
verdict into the agent's structured output. `output_format` selects "markdown", "json", or
"both". Pure function, no state, no LLM.
"""

from __future__ import annotations

import json

_DISCLAIMER = (
    "⚠️ **AI-Assisted Parse** — extracted by an automated multi-format parsing agent. "
    "Documents flagged `human_review` / `reparse` below should be checked before downstream use."
)


def _doc_markdown(doc: dict, meta: dict, quality: dict, chunks: list[dict]) -> str:
    title = meta.get("title", doc["doc_id"])
    parts = [
        f"### {title}",
        f"- **doc_id**: `{doc['doc_id']}`",
        f"- **doc_type**: {meta.get('doc_type', 'unknown')} "
        f"(confidence {meta.get('confidence', 0.0)}, via {meta.get('source', 'n/a')})",
        f"- **parse_profile**: {doc.get('profile', 'n/a')} (parser: {doc.get('parser', 'n/a')})",
        f"- **quality**: score {quality.get('score', 0.0)} → **{quality.get('verdict', 'n/a')}**",
        f"- **chunks**: {len(chunks)}",
        "",
        doc.get("markdown", "").strip() or "_(no content extracted)_",
        "",
    ]
    return "\n".join(parts)


def render_output(
    parsed_documents: list[dict],
    chunk_plan: dict,
    inferred_metadata: dict,
    quality_report: dict,
    rejected_documents: list[dict],
    output_format: str = "markdown",
) -> str:
    """Return the rendered payload as a string (Markdown, JSON, or both concatenated)."""
    fmt = (output_format or "markdown").lower()

    json_payload = {
        "documents": [
            {
                "doc_id": d["doc_id"],
                "metadata": inferred_metadata.get(d["doc_id"], {}),
                "quality": quality_report.get(d["doc_id"], {}),
                "chunks": chunk_plan.get(d["doc_id"], []),
                "markdown": d.get("markdown", ""),
            }
            for d in parsed_documents
        ],
        "rejected": rejected_documents,
    }

    md_parts = [f"> {_DISCLAIMER}\n", "# Parsed Document Set\n"]
    for d in parsed_documents:
        did = d["doc_id"]
        md_parts.append(
            _doc_markdown(d, inferred_metadata.get(did, {}), quality_report.get(did, {}), chunk_plan.get(did, []))
        )
    if rejected_documents:
        md_parts.append("## Rejected Documents\n")
        for r in rejected_documents:
            md_parts.append(f"- `{r['doc_id']}` — {r['reason']}")
    markdown = "\n".join(md_parts)

    if fmt == "json":
        return json.dumps(json_payload, ensure_ascii=False, indent=2)
    if fmt == "both":
        return markdown + "\n\n```json\n" + json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n```\n"
    return markdown
