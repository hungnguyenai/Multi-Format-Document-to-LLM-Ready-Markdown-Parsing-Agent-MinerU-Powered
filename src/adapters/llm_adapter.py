"""Unified LLM adapter for the CMN-C1-127 decision nodes.

Wraps a raw framework LLM (`BaseLLM`, exposing `complete(prompt, api_key=..., temperature=...,
max_tokens=...) -> str`) and exposes the four domain-decision methods the services call:

  - classify_route(doc)   -> {"parse_profile", "rationale"} | None   (DocumentRoutingDecision)
  - plan_chunks(doc)      -> [{"start","end","label"}, ...] | None    (SemanticChunkPlanner)
  - infer_metadata(doc)   -> {"title","doc_type","confidence"} | None (AmbiguousMetadataInference)
  - judge_quality(doc)    -> {"score": float} | None                  (ParseQualityJudge)

Each method builds a strict-JSON prompt, calls the LLM, and parses the response. Any failure
(call error, malformed JSON, missing field) returns None so the caller falls back to its
deterministic path — the LLM is an enhancement, never a hard dependency. This module imports no
framework symbols: the LLM is duck-typed, so the adapter is unit-testable with a fake.
"""

from __future__ import annotations


import json
import logging
import re

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 4_000  # cap document text sent to the model
_VALID_PROFILES = {
    "vlm_ocr_dual",
    "ocr_only",
    "vlm_layout",
    "table_extract",
    "structured_text",
    "passthrough",
}
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARR_RE = re.compile(r"\[.*\]", re.DOTALL)


class LLMAdapter:
    """Adapter exposing CMN-C1-127 decision methods over a raw framework LLM."""

    def __init__(self, llm, api_key: str | None = None) -> None:
        # Immutable injected deps only.
        self._llm = llm
        self._api_key = api_key

    # ── low-level ───────────────────────────────────────────────────────────
    def _complete(self, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        return self._llm.complete(prompt, api_key=self._api_key, temperature=temperature, max_tokens=max_tokens)

    @staticmethod
    def _extract_json(text: str, array: bool = False):
        """Pull the first JSON object/array out of a model response (tolerates ``` fences)."""
        if not text:
            return None
        pat = _JSON_ARR_RE if array else _JSON_OBJ_RE
        m = pat.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None

    def _ask(self, prompt: str, array: bool = False, max_tokens: int = 512):
        try:
            raw = self._complete(prompt, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 — LLM is best-effort
            logger.warning("LLMAdapter call failed: %s", exc)
            return None
        return self._extract_json(raw, array=array)

    @staticmethod
    def _content(doc: dict) -> str:
        return (doc.get("markdown") or doc.get("content") or "")[:_MAX_CONTENT_CHARS]

    # ── decision methods ──────────────────────────────────────────────────────
    def classify_route(self, doc: dict) -> dict | None:
        prompt = (
            "You select a MinerU parse profile for a document. Reply with ONLY a JSON object: "
            '{"parse_profile": "<one of vlm_ocr_dual|ocr_only|vlm_layout|table_extract|'
            'structured_text|passthrough>", "rationale": "<short reason>"}.\n'
            f"format hint: {doc.get('format', 'unknown')}\n"
            f"name: {doc.get('name', doc.get('doc_id', ''))}\n"
            f"content sample:\n{self._content(doc)[:800]}"
        )
        out = self._ask(prompt, max_tokens=200)
        if not isinstance(out, dict):
            return None
        profile = out.get("parse_profile")
        if profile not in _VALID_PROFILES:
            return None
        return {"parse_profile": profile, "rationale": out.get("rationale", "llm-classified")}

    def plan_chunks(self, doc: dict) -> list | None:
        blocks = doc.get("blocks", [])
        prompt = (
            "Plan semantic chunk boundaries (by block index) for RAG ingestion. There are "
            f"{len(blocks)} markdown blocks. Reply with ONLY a JSON array of "
            '{"start": <int>, "end": <int>, "label": "<str>"} covering [0, n) contiguously.\n'
            f"blocks (truncated):\n{json.dumps([b[:160] for b in blocks[:40]], ensure_ascii=False)}"
        )
        out = self._ask(prompt, array=True, max_tokens=600)
        if not isinstance(out, list) or not out:
            return None
        norm: list[dict] = []
        for i, c in enumerate(out):
            if not isinstance(c, dict) or "start" not in c or "end" not in c:
                return None
            norm.append(
                {
                    "start": int(c["start"]),
                    "end": int(c["end"]),
                    "label": str(c.get("label", f"chunk-{i}")),
                }
            )
        return norm

    def infer_metadata(self, doc: dict) -> dict | None:
        prompt = (
            "Infer document metadata. Reply with ONLY a JSON object: "
            '{"title": "<str>", "doc_type": "<str>", "confidence": <0..1 float>}.\n'
            f"parse_profile: {doc.get('profile', 'unknown')}\n"
            f"content sample:\n{self._content(doc)[:1200]}"
        )
        out = self._ask(prompt, max_tokens=200)
        if not isinstance(out, dict) or not out.get("title"):
            return None
        try:
            conf = float(out.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        return {
            "title": str(out["title"]),
            "doc_type": str(out.get("doc_type", "unknown")),
            "confidence": max(0.0, min(1.0, conf)),
        }

    def judge_quality(self, doc: dict) -> dict | None:
        prompt = (
            "Score the extraction quality of this parsed document from 0.0 (garbled/empty) to "
            '1.0 (clean). Reply with ONLY a JSON object: {"score": <0..1 float>}.\n'
            f"content sample:\n{self._content(doc)[:1600]}"
        )
        out = self._ask(prompt, max_tokens=80)
        if not isinstance(out, dict) or not isinstance(out.get("score"), (int, float)):
            return None
        return {"score": max(0.0, min(1.0, float(out["score"])))}
