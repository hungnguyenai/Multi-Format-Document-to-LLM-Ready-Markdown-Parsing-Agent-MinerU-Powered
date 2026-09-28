"""State schema for CMN-C1-127 — MultiFormatDocumentParsingAgent.

Flat TypedDict extending the framework AgentState. Only agent-specific fields are declared
here; AgentState already provides the shared fields (user_input, status, node_history,
error_log, correlation_id, caller_trust_level, formatted_output, etc.). All fields are
flat / JSON-serializable — no Pydantic, dataclasses, credentials, or InvocationContext.
"""

from __future__ import annotations

from framework.schemas.agent_state import AgentState


class CMN_C1_127_State(AgentState):
    # --- Input config (provided on user_input JSON or direct state fields, with defaults) ---
    documents: list[dict]  # [{"doc_id", "name", "format", "content"/"path"}]
    output_format: str  # "markdown" | "json" | "both"
    max_doc_size_kb: int

    # --- DocumentRoutingDecision (pre_process) output ---
    routing_plan: list[dict]  # [{"doc_id", "format", "parse_profile", "rationale"}]
    rejected_documents: list[dict]  # [{"doc_id", "reason"}]

    # --- MinerU parse + SemanticChunkPlanner + AmbiguousMetadataInference (main) output ---
    parsed_documents: list[dict]  # [{"doc_id", "markdown", "blocks", "parser"}]
    chunk_plan: dict  # doc_id -> [{"start", "end", "label"}]
    inferred_metadata: dict  # doc_id -> {"title", "doc_type", "confidence"}

    # --- ParseQualityJudge + output render + S-3 (post_process) output ---
    quality_report: dict  # doc_id -> {"score", "verdict"}
    quality_judge_executed: bool  # anti-suppression: always True after the judge runs
    final_output: str  # rendered Markdown/JSON payload
    redaction_triggered: bool  # True if the S-3 secret-leakage redaction triggered
