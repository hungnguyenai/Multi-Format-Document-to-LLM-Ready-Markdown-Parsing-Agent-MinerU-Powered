"""ParseQualityJudge + output render + S-3 output safety (post_process).

Runs the NON-SUPPRESSIBLE parse-quality judge, renders the structured Markdown/JSON payload,
then applies the S-3 content gate (relocated from the old agent-class `_security_gate_output`):
anti-suppression check (the quality judge must have run), secret-leakage redaction, and
prompt-injection / credential-marker blanking. Produces `formatted_output` (returned by the
graph as `output`). Node contract: execute(self, state) -> dict; status enum.
"""

from __future__ import annotations

from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.adapters.factory import build_llm_adapter
from src.schemas.state import CMN_C1_127_State
from src.services.output_render import render_output
from src.services.output_safety import apply_output_safety
from src.services.quality_judge import judge_quality
from src.services.llm_factory import resolve_llm


class PostProcessNode(FunctionNode):
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def execute(self, state: CMN_C1_127_State) -> dict:
        llm, _llm_provider = resolve_llm(self._llm, state)
        parsed_documents = state.get("parsed_documents", [])

        # ParseQualityJudge — NON-SUPPRESSIBLE (executed flag always set True).
        llm_adapter = build_llm_adapter(llm, state)
        quality_report, judge_executed = judge_quality(parsed_documents, llm=llm_adapter)

        final_output = render_output(
            parsed_documents=parsed_documents,
            chunk_plan=state.get("chunk_plan", {}),
            inferred_metadata=state.get("inferred_metadata", {}),
            quality_report=quality_report,
            rejected_documents=state.get("rejected_documents", []),
            output_format=state.get("output_format", "markdown"),
        )

        # S-3 output safety (anti-suppression + secret redaction + injection check).
        safety = apply_output_safety(final_output, quality_judge_executed=judge_executed)
        final_output = safety["final_output"]
        redaction_triggered = safety["redaction_triggered"]

        base = {
            "quality_report": quality_report,
            "quality_judge_executed": judge_executed,
            "final_output": final_output,
            "redaction_triggered": redaction_triggered,
            "formatted_output": {
                "report": final_output,
                "quality_report": quality_report,
                "redaction_triggered": redaction_triggered,
            },
        }

        if safety.get("error"):
            emit_trace_event(
                "s3_violation",
                {"reason": safety["error"], "redaction_triggered": redaction_triggered},
                state,
            )
            return {**base, "status": AgentStatus.ERROR.value, "error_log": [safety["error"]]}

        emit_trace_event(
            "documents_rendered",
            {
                "output_length": len(final_output),
                "redaction_triggered": redaction_triggered,
                "documents": len(parsed_documents),
            },
            state,
        )
        return {**base, "status": AgentStatus.SUCCESS.value}
