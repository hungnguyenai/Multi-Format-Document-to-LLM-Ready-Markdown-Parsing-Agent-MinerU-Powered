"""Unit tests for src/adapters/ — LLMAdapter, MinerUAdapter, build_parser.

The raw LLM and the MinerU engine are duck-typed, so these exercise the adapter logic with
fakes (no framework / no live model / no MinerU runtime needed). build_llm_adapter itself is
covered by the integration test (it needs InvocationContext + secrets).
"""

import pytest

from src.adapters.factory import build_parser
from src.adapters.llm_adapter import LLMAdapter
from src.adapters.mineru_adapter import MinerUAdapter


class FakeLLM:
    """Returns a canned completion; records the last prompt; can be made to raise."""

    def __init__(self, response="", raises=False):
        self.response = response
        self.raises = raises
        self.last_prompt = None

    def complete(self, prompt, api_key=None, temperature=0.0, max_tokens=512):
        self.last_prompt = prompt
        if self.raises:
            raise RuntimeError("llm down")
        return self.response


_DOC = {"doc_id": "a", "format": "pdf", "markdown": "# Title\n\nbody", "blocks": ["# Title", "body"]}


# ── LLMAdapter.classify_route ─────────────────────────────────────────────────


def test_classify_route_parses_valid_profile():
    llm = FakeLLM('{"parse_profile": "vlm_ocr_dual", "rationale": "scanned multi-column"}')
    out = LLMAdapter(llm).classify_route(_DOC)
    assert out == {"parse_profile": "vlm_ocr_dual", "rationale": "scanned multi-column"}


def test_classify_route_rejects_invalid_profile():
    llm = FakeLLM('{"parse_profile": "not_a_profile", "rationale": "x"}')
    assert LLMAdapter(llm).classify_route(_DOC) is None


def test_classify_route_none_on_llm_error():
    assert LLMAdapter(FakeLLM(raises=True)).classify_route(_DOC) is None


def test_classify_route_handles_code_fence():
    llm = FakeLLM('```json\n{"parse_profile": "ocr_only", "rationale": "image"}\n```')
    out = LLMAdapter(llm).classify_route(_DOC)
    assert out["parse_profile"] == "ocr_only"


# ── LLMAdapter.plan_chunks ────────────────────────────────────────────────────


def test_plan_chunks_parses_array():
    llm = FakeLLM('[{"start": 0, "end": 2, "label": "intro"}]')
    out = LLMAdapter(llm).plan_chunks(_DOC)
    assert out == [{"start": 0, "end": 2, "label": "intro"}]


def test_plan_chunks_none_on_garbage():
    assert LLMAdapter(FakeLLM("not json")).plan_chunks(_DOC) is None


# ── LLMAdapter.infer_metadata ─────────────────────────────────────────────────


def test_infer_metadata_parses_and_clamps_confidence():
    llm = FakeLLM('{"title": "Q3 Report", "doc_type": "financial", "confidence": 1.9}')
    out = LLMAdapter(llm).infer_metadata(_DOC)
    assert out["title"] == "Q3 Report" and out["doc_type"] == "financial"
    assert out["confidence"] == 1.0  # clamped to [0,1]


def test_infer_metadata_none_without_title():
    assert LLMAdapter(FakeLLM('{"doc_type": "x"}')).infer_metadata(_DOC) is None


# ── LLMAdapter.judge_quality ──────────────────────────────────────────────────


def test_judge_quality_parses_score():
    out = LLMAdapter(FakeLLM('{"score": 0.83}')).judge_quality(_DOC)
    assert out == {"score": 0.83}


def test_judge_quality_none_on_missing_score():
    assert LLMAdapter(FakeLLM('{"verdict": "ok"}')).judge_quality(_DOC) is None


# ── MinerUAdapter ─────────────────────────────────────────────────────────────


class FakeEngine:
    def to_markdown(self, source, mode="text"):
        return {"markdown": f"# parsed ({mode})\n\n{source[:20]}", "blocks": ["# parsed", source[:20]]}


def test_mineru_adapter_parses_with_injected_client():
    adapter = MinerUAdapter(client=FakeEngine())
    out = adapter.parse({"doc_id": "a", "content": "raw pdf bytes here"}, "vlm_ocr_dual")
    assert "parsed (vlm+ocr)" in out["markdown"]
    assert isinstance(out["blocks"], list) and out["blocks"]


def test_mineru_adapter_normalizes_plain_string_result():
    class StrEngine:
        def to_markdown(self, source, mode="text"):
            return "plain text out\n\nsecond block"

    out = MinerUAdapter(client=StrEngine()).parse({"content": "x"}, "passthrough")
    assert out["markdown"].startswith("plain text out")
    assert len(out["blocks"]) == 2


def test_mineru_adapter_raises_without_runtime():
    # MinerU is not installed in CI/dev → constructing without a client raises ImportError.
    with pytest.raises(ImportError):
        MinerUAdapter()


# ── build_parser ──────────────────────────────────────────────────────────────


def test_build_parser_returns_injected():
    sentinel = FakeEngine()
    assert build_parser({"parser": sentinel}) is sentinel


def test_build_parser_none_by_default():
    assert build_parser({}) is None
    assert build_parser(None) is None


def test_build_parser_none_when_mineru_unavailable():
    # enable_mineru set but MinerU not installed → factory declines (deterministic fallback).
    assert build_parser({"enable_mineru": True}) is None
