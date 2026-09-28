"""Unit tests for the three pipeline nodes (pre_process / main / post_process).

Each node is tested in isolation via node.execute(state) and asserts the AgentStatus enum.
The core is deterministic (no live LLM / no MinerU adapter). Trust enforcement happens in
BaseNode.__call__ (integration test) — execute() is the pure business step.
"""

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode


def _base_state(**over):
    state = {
        "user_input": "",
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "",
        "caller_trust_level": "verified_external",
        "caller_id": "",
        "hitl_allowed": True,
    }
    state.update(over)
    return state


_DOCS = [
    {"doc_id": "pdf1", "format": "pdf", "content": "# Q3 Report\n\nRevenue grew.\n\n| a | b |\n|---|---|"},
    {"doc_id": "img1", "format": "image", "content": "scanned board resolution text"},
]


def _run_pipeline(documents, output_format="markdown"):
    state = _base_state(documents=documents, output_format=output_format)
    pre = PreProcessNode().execute(state)
    main = MainNode().execute(_base_state(**{**state, **pre}))
    post = PostProcessNode().execute(_base_state(**{**state, **pre, **main}))
    return {**pre, **main, **post}


# --- PreProcessNode (routing + S-2) ---


def test_pre_process_success_routes_documents():
    result = PreProcessNode().execute(_base_state(documents=_DOCS))
    assert result["status"] == AgentStatus.SUCCESS
    assert len(result["routing_plan"]) == 2
    assert result["routing_plan"][0]["parse_profile"] == "vlm_ocr_dual"


def test_pre_process_reads_json_envelope_from_user_input():
    envelope = json.dumps({"documents": _DOCS, "output_format": "json"})
    result = PreProcessNode().execute(_base_state(user_input=envelope))
    assert result["status"] == AgentStatus.SUCCESS
    assert result["output_format"] == "json"


def test_pre_process_empty_documents_error():
    result = PreProcessNode().execute(_base_state(documents=[]))
    assert result["status"] == AgentStatus.ERROR
    assert result["error_log"]


def test_pre_process_all_rejected_error():
    result = PreProcessNode().execute(_base_state(documents=[{"doc_id": "x", "format": "exe"}]))
    assert result["status"] == AgentStatus.ERROR
    assert result["rejected_documents"][0]["doc_id"] == "x"


def test_pre_process_max_kb_out_of_range():
    result = PreProcessNode().execute(_base_state(documents=_DOCS, max_doc_size_kb=0))
    assert result["status"] == AgentStatus.ERROR


# --- MainNode (parse + chunk + metadata) ---


def test_main_parses_and_plans():
    out = _run_pipeline(_DOCS)
    assert out["status"] == AgentStatus.SUCCESS
    assert len(out["parsed_documents"]) == 2
    assert "pdf1" in out["chunk_plan"]
    assert out["inferred_metadata"]["pdf1"]["title"] == "Q3 Report"


def test_main_errors_without_routing_plan():
    out = MainNode().execute(_base_state(routing_plan=[]))
    assert out["status"] == AgentStatus.ERROR


# --- PostProcessNode (quality judge + render + S-3) ---


def test_post_process_renders_and_judges():
    out = _run_pipeline(_DOCS)
    assert out["status"] == AgentStatus.SUCCESS
    assert out["quality_judge_executed"] is True
    assert "# Parsed Document Set" in out["final_output"]
    assert out["formatted_output"]["report"]


def test_post_process_redacts_secret_in_extracted_text():
    docs = [{"doc_id": "leak", "format": "txt", "content": 'config api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"'}]
    out = _run_pipeline(docs)
    assert out["redaction_triggered"] is True
    assert "REDACTED" in out["final_output"]


# --- Wave-2 coverage ---


def test_pre_process_max_documents_boundary():
    docs100 = [{"doc_id": f"d{i}", "format": "txt", "content": "x"} for i in range(100)]
    ok = PreProcessNode().execute(_base_state(documents=docs100))
    assert ok["status"] == AgentStatus.SUCCESS
    docs101 = [{"doc_id": f"d{i}", "format": "txt", "content": "x"} for i in range(101)]
    bad = PreProcessNode().execute(_base_state(documents=docs101))
    assert bad["status"] == AgentStatus.ERROR


def test_pre_process_non_dict_documents_error():
    res = PreProcessNode().execute(_base_state(documents=["notadict", {"doc_id": "a", "format": "txt"}]))
    assert res["status"] == AgentStatus.ERROR


def test_main_partial_parse_failure():
    class FlakyParser:
        def parse(self, doc, profile):
            if doc.get("doc_id") == "d2":
                raise RuntimeError("mineru boom on d2")
            return {"markdown": "# ok\n\nbody", "blocks": ["# ok", "body"]}

    docs = [{"doc_id": "d1", "format": "pdf", "content": "a"}, {"doc_id": "d2", "format": "pdf", "content": "b"}]
    state = _base_state(documents=docs)
    pre = PreProcessNode().execute(state)
    main = MainNode(parser=FlakyParser()).execute(_base_state(**{**state, **pre}))
    parsed = {p["doc_id"]: p for p in main["parsed_documents"]}
    assert main["status"] == AgentStatus.SUCCESS
    assert parsed["d1"]["parser"] == "mineru"
    assert parsed["d2"]["parser"] == "fallback"  # doc-2 fell back after the adapter raised


def test_post_process_json_output_format():
    out = _run_pipeline(_DOCS, output_format="json")
    assert out["final_output"].strip().startswith("{")


def test_post_process_both_output_format():
    out = _run_pipeline(_DOCS, output_format="both")
    assert "# Parsed Document Set" in out["final_output"]
    assert "```json" in out["final_output"]
