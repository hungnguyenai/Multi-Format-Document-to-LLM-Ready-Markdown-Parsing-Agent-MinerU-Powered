"""CMN-C1-127 graph — AgentBaseGraph (L1 direct). The graph class IS the agent.

Cat 1 (single capability: parse multi-format enterprise documents into LLM-ready Markdown/JSON).
Fixed 5-node backbone initialize → pre_process → main → post_process → finalize. No separate
agent class, no double-graph, no _invoke_impl, no .run(). Public entry: Graph(config).compile()
then .invoke(user_input, ctx=...). The 5-layer security model is framework-enforced — there are
no developer `_security_gate_*` methods (S-2 input validation lives in pre_process, S-3 output
safety in post_process as ordinary node logic).

The four LLM decision points the architect specified map onto the three author slots:

  pre_process : DocumentRoutingDecision (LLM-assisted, deterministic fallback)
  main        : MinerU parse (deterministic) → SemanticChunkPlanner → AmbiguousMetadataInference
  post_process: ParseQualityJudge (non-suppressible) → output render → S-3 output safety
"""

from __future__ import annotations

from framework.graph.agent_base_graph import AgentBaseGraph

from src.adapters.factory import build_parser
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import CMN_C1_127_State


class MultiFormatDocumentParsingAgent(AgentBaseGraph):
    """CMN-C1-127 — Multi-Format Document to LLM-Ready Markdown Parsing Agent (Cat 1)."""

    @property
    def name(self) -> str:
        return "cmn-c1-127"

    @property
    def state_schema(self) -> type[CMN_C1_127_State]:
        return CMN_C1_127_State

    def register_nodes(self) -> None:
        super().register_nodes()  # preserve default initialize + finalize backbone
        cfg = self.config if hasattr(self, "config") else {}
        llm = cfg.get("llm")  # raw framework BaseLLM (or None in CI); wrapped per-invocation
        parser = build_parser(cfg)  # MinerU adapter when enabled, else deterministic fallback
        self._nodes["pre_process"] = PreProcessNode(llm=llm)
        self._nodes["main"] = MainNode(llm=llm, parser=parser)
        self._nodes["post_process"] = PostProcessNode(llm=llm)


# Alias for the AgentRegistry entry point (config/agent.yaml module: "src.graph").
Graph = MultiFormatDocumentParsingAgent


def build_agent(config: dict | None = None) -> MultiFormatDocumentParsingAgent:
    """Factory for AgentRegistry entry point."""
    return MultiFormatDocumentParsingAgent(config=config or {})
