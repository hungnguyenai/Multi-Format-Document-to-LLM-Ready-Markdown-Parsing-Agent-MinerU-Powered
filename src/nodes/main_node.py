"""Main node — MinerU parse → SemanticChunkPlanner → AmbiguousMetadataInference.

AgentBaseGraph runs a fixed pipeline (initialize → pre_process → main → post_process → finalize),
so the three middle business steps are orchestrated here via services in src/services/. MinerU
extraction is deterministic; the chunk planner and metadata inference are LLM-assisted with
deterministic fallbacks. An optional MinerU adapter (`parser`) and `llm` are injected via config.

Node contract: execute(self, state) -> dict; status is an AgentStatus enum; no __call__/_invoke_impl.
"""

from __future__ import annotations

from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.adapters.factory import build_llm_adapter
from src.schemas.state import CMN_C1_127_State
from src.services.mineru_parse import parse_documents
from src.services.metadata_infer import infer_metadata
from src.services.semantic_chunk import plan_chunks
from src.services.llm_factory import resolve_llm

_DEFAULT_MAX_DOC_SIZE_KB = 5_000


class MainNode(FunctionNode):
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None, parser: Any = None) -> None:
        # Immutable injected deps only (no mutable per-invocation state on self).
        self._llm = llm
        self._parser = parser

    def execute(self, state: CMN_C1_127_State) -> dict:
        llm, _llm_provider = resolve_llm(self._llm, state)
        routing_plan = state.get("routing_plan", [])
        # Propagate a pre_process failure: AgentBaseGraph always routes pre_process → main.
        if not routing_plan:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["main: no routing_plan (routing failed or produced no documents)"],
            }

        max_kb = state.get("max_doc_size_kb", _DEFAULT_MAX_DOC_SIZE_KB)
        doc_index = {d["doc_id"]: d for d in state.get("documents", [])}

        # MinerU extraction (deterministic; adapter when injected, fallback otherwise).
        parsed_documents = parse_documents(routing_plan, doc_index, parser=self._parser, max_doc_size_kb=max_kb)

        llm_adapter = build_llm_adapter(llm, state)

        # SemanticChunkPlanner (LLM-assisted, deterministic fallback).
        chunk_plan = plan_chunks(parsed_documents, llm=llm_adapter)

        # AmbiguousMetadataInference (LLM-assisted, deterministic fallback).
        inferred_metadata = infer_metadata(parsed_documents, llm=llm_adapter)

        emit_trace_event(
            "documents_parsed",
            {
                "parsed": len(parsed_documents),
                "chunked": sum(len(c) for c in chunk_plan.values()),
                "metadata_inferred": len(inferred_metadata),
            },
            state,
        )
        return {
            "parsed_documents": parsed_documents,
            "chunk_plan": chunk_plan,
            "inferred_metadata": inferred_metadata,
            "status": AgentStatus.SUCCESS.value,
        }
