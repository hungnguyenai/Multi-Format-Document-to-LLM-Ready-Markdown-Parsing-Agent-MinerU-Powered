"""DocumentRoutingDecision (pre_process) — validate input + S-2 gate + route each document.

AgentCore node contract: override execute(self, state) -> dict; return a partial update; set
status (AgentStatus enum); never override __call__; no _invoke_impl. Documents are caller-supplied
enterprise content (S-1): require VERIFIED_EXTERNAL trust. The S-2 input gate (bound document
count + size, require structured descriptors) runs inline before routing. DocumentRoutingDecision
then selects a MinerU parse profile per document (LLM-assisted, deterministic fallback).
"""

from __future__ import annotations

from typing import Any

import json

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.adapters.factory import build_llm_adapter
from src.schemas.state import CMN_C1_127_State
from src.services.document_routing import plan_routing
from src.services.llm_factory import resolve_llm

_MAX_DOCUMENTS = 100
_DEFAULT_MAX_DOC_SIZE_KB = 5_000
_MAX_DOC_SIZE_KB_LIMIT = 50_000


class PreProcessNode(FunctionNode):
    """Validate the document set (S-2), then route each document to a MinerU parse profile."""

    # S-1: documents are caller-supplied external content.
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def _load_input(self, state: CMN_C1_127_State) -> tuple[list, str | None]:
        """Read `documents` (+ optional `output_format`) from state, or from a JSON envelope
        on user_input. Returns (documents, envelope_output_format-or-None)."""
        docs = state.get("documents")
        if docs:
            return docs, None
        raw = state.get("user_input", "")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                envelope = json.loads(raw)
                if isinstance(envelope, dict):
                    return envelope.get("documents", []), envelope.get("output_format")
            except json.JSONDecodeError:
                return [], None
        return [], None

    def execute(self, state: CMN_C1_127_State) -> dict:
        llm, _llm_provider = resolve_llm(self._llm, state)
        documents, envelope_format = self._load_input(state)
        max_kb = state.get("max_doc_size_kb", _DEFAULT_MAX_DOC_SIZE_KB)
        # State value wins; otherwise the envelope's output_format; otherwise default.
        output_format = state.get("output_format") or envelope_format or "markdown"

        # S-2: structured input required.
        if not isinstance(documents, list) or not documents:
            return {"status": AgentStatus.ERROR.value, "error_log": ["S-2 violation: no documents provided"]}
        if len(documents) > _MAX_DOCUMENTS:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"S-2 violation: too many documents (>{_MAX_DOCUMENTS})"],
            }
        if not all(isinstance(d, dict) for d in documents):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["S-2 violation: each document must be a structured descriptor (dict)"],
            }
        if not isinstance(max_kb, int) or max_kb <= 0 or max_kb > _MAX_DOC_SIZE_KB_LIMIT:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"S-2 violation: max_doc_size_kb out of range (1-{_MAX_DOC_SIZE_KB_LIMIT})"],
            }

        # Assign stable doc_ids and normalize.
        normalized: list[dict] = []
        for idx, doc in enumerate(documents):
            doc_id = doc.get("doc_id") or doc.get("name") or f"doc-{idx}"
            normalized.append({**doc, "doc_id": doc_id})

        llm_adapter = build_llm_adapter(llm, state)
        routing_plan, rejected = plan_routing(normalized, llm=llm_adapter)

        if not routing_plan:
            return {
                "documents": normalized,
                "routing_plan": [],
                "rejected_documents": rejected,
                "status": AgentStatus.ERROR.value,
                "error_log": ["all documents rejected at routing (unsupported formats)"],
            }

        emit_trace_event(
            "documents_routed",
            {"routed": len(routing_plan), "rejected": len(rejected)},
            state,
        )
        return {
            "documents": normalized,
            "validated_input": f"{len(routing_plan)} document(s) routed",
            "max_doc_size_kb": max_kb,
            "output_format": output_format,
            "routing_plan": routing_plan,
            "rejected_documents": rejected,
            "status": AgentStatus.SUCCESS.value,
        }
