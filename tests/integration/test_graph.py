"""Integration test — full graph compile() + invoke() (Cat 1 backbone).

Drives the whole pipeline (initialize → pre_process → main → post_process → finalize) with
VERIFIED_EXTERNAL trust (the nodes require it). Deterministic core — no live LLM, no MinerU
adapter. The document envelope is passed as the agent's user_input (a JSON string).
"""

import json

import pytest

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider

from src.graph.graph import MultiFormatDocumentParsingAgent


def _ext_ctx():
    return InvocationContext(
        correlation_id="it-corr",
        session_id="it-session",
        thread_id="it-thread",
        parent_trace_id="",
        caller_id="dx-team",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        secrets=InMemoryProvider({}),
        hitl_allowed=True,
    )


def _envelope(output_format="markdown"):
    return json.dumps(
        {
            "documents": [
                {
                    "doc_id": "pdf1",
                    "format": "pdf",
                    "content": "# Q3 Financial Report\n\nRevenue grew 12%.\n\n| Metric | Value |\n|---|---|",
                },
                {"doc_id": "img1", "format": "image", "content": "scanned 稟議書 approval text"},
            ],
            "output_format": output_format,
        }
    )


@pytest.fixture
def agent():
    a = MultiFormatDocumentParsingAgent(config={"max_retry": 1})
    a.compile()
    return a


def test_full_pipeline_success(agent):
    with bound_secrets(InMemoryProvider({})):
        result = agent.invoke(_envelope(), ctx=_ext_ctx())
    assert result["status"] == "success"
    assert result["output"] is not None
    assert "# Parsed Document Set" in result["output"]["report"]
    assert "MainNode" in result["node_history"]


def test_full_pipeline_json_output(agent):
    with bound_secrets(InMemoryProvider({})):
        result = agent.invoke(_envelope(output_format="json"), ctx=_ext_ctx())
    assert result["status"] == "success"
    assert result["output"]["report"].strip().startswith("{")


def test_full_pipeline_error_on_empty_documents(agent):
    with bound_secrets(InMemoryProvider({})):
        result = agent.invoke(json.dumps({"documents": []}), ctx=_ext_ctx())
    assert result["status"] in ("error", "cancelled")
