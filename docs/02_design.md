# docs/02_design.md — CMN-C1-127 Design Specification

**Template ID:** CMN-C1-127
- **L1 Base**: AgentBaseGraph (L1 direct — the graph class IS the agent)
**Category:** Cat 1 (single capability: parse multi-format enterprise documents into LLM-ready Markdown/JSON)
**Pattern:** Fixed 3-slot backbone (pre_process / main / post_process)

---

## 1. Architecture

The graph class `MultiFormatDocumentParsingAgent(AgentBaseGraph)` IS the agent — no separate
agent class, no double-graph, no `_invoke_impl`, no `.run()`. The framework owns the fixed
backbone `initialize → pre_process → main → post_process → finalize` and the 5-layer security
model. Public entry: `Graph(config).compile()` then `.invoke(user_input, ctx=...)`.

The architect's deterministic-extraction + four LLM-decision nodes map onto the three author slots:

```
pre_process : DocumentRoutingDecision        (LLM-assisted profile selection, S-2 input gate)
main        : MinerU parse (deterministic) → SemanticChunkPlanner → AmbiguousMetadataInference
post_process: ParseQualityJudge (non-suppressible) → output render → S-3 output safety
```

```
                 ┌─────────────┐   ┌──────────────────────────────┐   ┌────────────────────────────┐
 documents  ───▶ │ pre_process │──▶│            main              │──▶│        post_process        │──▶ output
 (JSON env)      │ route + S-2 │   │ MinerU parse → chunk → meta  │   │ quality judge → render → S3 │   (markdown/json)
                 └─────────────┘   └──────────────────────────────┘   └────────────────────────────┘
```

Deterministic logic lives in `src/services/` (auditable, independently testable). MinerU is an
injected adapter (heavy optional runtime, absent in CI → deterministic fallback uses the inline
`content`). An optional LLM refines routing, chunk boundaries, metadata, and quality grading;
each LLM call has a deterministic fallback so the pipeline runs without a live model.

---

## 2. State Schema (`src/schemas/state.py`)

`class CMN_C1_127_State(AgentState)` — flat TypedDict extending `AgentState`. Agent-specific
fields: `documents`, `output_format`, `max_doc_size_kb`, `routing_plan`, `rejected_documents`,
`parsed_documents`, `chunk_plan`, `inferred_metadata`, `quality_report`,
`quality_judge_executed`, `final_output`, `redaction_triggered`. Output is surfaced via
`formatted_output` (returned by the graph as `output`). No Pydantic, no dataclass, no
credentials, no `InvocationContext` in state.

---

## 3. Node / service responsibilities

### 3-1. pre_process — `PreProcessNode` (DocumentRoutingDecision + S-2)
- S-1: `required_trust_level = VERIFIED_EXTERNAL` (documents are caller-supplied content).
- S-2 input gate (inline): require a non-empty list of structured descriptors, bound document
  count (≤100) and `max_doc_size_kb` (1–50000). Returns `status=ERROR` on violation.
- `src/services/document_routing.py::plan_routing` — pick a MinerU parse profile per document
  (`vlm_ocr_dual` / `ocr_only` / `vlm_layout` / `table_extract` / `structured_text` /
  `passthrough`); reject unsupported formats into `rejected_documents`. Optional LLM resolves
  ambiguous layouts.

### 3-2. main — `MainNode`
- `src/services/mineru_parse.py::parse_documents` — deterministic MinerU extraction per routed
  document → `parsed_documents` (`markdown`, `blocks`). Injected `parser` adapter (MinerU 3.1.0
  VLM+OCR) when available; inline-content fallback otherwise; size-bounded.
- `src/services/semantic_chunk.py::plan_chunks` — adaptive chunk boundaries on semantic units
  (LLM-assisted; deterministic block-grouping fallback) → `chunk_plan`.
- `src/services/metadata_infer.py::infer_metadata` — title / doc_type / confidence per document
  (LLM-assisted; first-heading + profile fallback) → `inferred_metadata`.
- Guards a pre_process failure (no `routing_plan`) → `status=ERROR`.

### 3-3. post_process — `PostProcessNode` (ParseQualityJudge + render + S-3)
- `src/services/quality_judge.py::judge_quality` — NON-SUPPRESSIBLE extraction-quality scoring
  → `quality_report` (`score`, `verdict` ∈ {pass, human_review, reparse});
  `quality_judge_executed=True` is always set (anti-suppression invariant).
- `src/services/output_render.py::render_output` — assemble the LLM-ready Markdown / JSON /
  both payload from parsed docs + chunk plan + metadata + quality verdict.
- `src/services/output_safety.py::apply_output_safety` — S-3 content gate (ordinary node logic,
  NOT a developer `_security_gate_*` method): anti-suppression assertion
  (`quality_judge_executed` must be True), secret-leakage redaction
  (`[REDACTED - potential secret]`), prompt-injection / credential-marker blanking. Sets
  `redaction_triggered`; returns `status=ERROR` + `error_log` on a hard violation.

---

## 4. Security (framework-enforced 5-layer)

| Layer | Handling |
|---|---|
| S-1 Trust gate | `required_trust_level = VERIFIED_EXTERNAL` on all three nodes; agent-level `required_trust_level: VERIFIED_EXTERNAL` in `config/agent.yaml`. Enforced in `BaseNode.__call__()`. |
| S-2 Input gate | Inline in `pre_process` (structured descriptors, count + size bounds, supported formats). |
| S-3 Output safety | `src/services/output_safety.py`, called by `post_process` (no `_security_gate_*` method). |
| S-4 Audit | `emit_trace_event(event_type, payload, state)` in each side-effecting node. |
| S-5 Credential scan | Import-time framework scan; `dependencies = []`; no credentials in source/state. |

There are no developer `__pre_invoke__` / `_security_gate_input` / `_security_gate_output`
methods and no separate agent class.

---

## 5. Config (`config/agent.yaml`)

Single manifest: `agent.{id: CMN-C1-127, name: MultiFormatDocumentParsingAgent, version,
category: "Cat 1", industry: CMN, base_type: VectorRAGAgent, module: "src.graph", class:
MultiFormatDocumentParsingAgent, config.{max_retry: 2, timeout_seconds: 60}, required_trust_level:
VERIFIED_EXTERNAL}`. The optional MinerU `parser` and `llm` adapters are injected via runtime
config (`cfg.get("parser")`, `cfg.get("llm")`), not declared here.

---

## 6. MinerU integration (v1)

MinerU 3.1.0 (Apache 2.0, April 2026) is a heavy optional runtime. It is injected as a `parser`
adapter exposing `parse(doc, profile) -> {"markdown", "blocks"}`; when absent (e.g. CI) a
deterministic fallback treats the inline `content` as already-extracted text so the full pipeline
remains exercisable. Phase 3 wires the real MinerU VLM+OCR dual engine behind that adapter
interface and replaces the LLM-assist stubs with real model calls.

---

## 7. Error handling

The backbone always routes `pre_process → main → post_process`, so each node guards its inputs
and returns `status = AgentStatus.ERROR` (with `error_log`) rather than raising.

| Failure | Where | Behaviour |
|---|---|---|
| No / empty `documents` | pre_process (S-2) | ERROR `"S-2 violation: no documents provided"` — no routing, no output |
| > 100 documents | pre_process (S-2) | ERROR `"too many documents (>100)"` |
| Non-dict document entry | pre_process (S-2) | ERROR `"each document must be a structured descriptor (dict)"` |
| `max_doc_size_kb` out of range | pre_process (S-2) | ERROR `"max_doc_size_kb out of range (1-50000)"` |
| All documents unsupported format | pre_process | ERROR; every doc in `rejected_documents`; empty `routing_plan` (no content emitted) |
| Some documents unsupported | pre_process | SUCCESS; rejected docs listed in `rejected_documents`, others routed |
| MinerU adapter raises on a document | main (`parse_documents`) | logged; that document falls back to deterministic inline-content extraction (`parser="fallback"`); other documents unaffected — partial-document results are preserved |
| Missing `routing_plan` reaching main | main | ERROR `"no routing_plan"` (propagates a pre_process failure) |
| LLM decision call fails / returns malformed JSON | routing / chunk / metadata / quality services | logged; the deterministic fallback for that step is used (never fatal) |
| Quality judge did not execute | post_process (S-3 anti-suppression) | ERROR — output blanked; the judge cannot be configured off |
| Secret / injection pattern in extracted text | post_process (S-3) | secret redacted in place (`redaction_triggered=True`); injection/credential markers blank the whole output and set ERROR |

## 8. Performance / limits

| Limit | Value | Enforced |
|---|---|---|
| Documents per invocation | ≤ 100 | pre_process S-2 |
| `max_doc_size_kb` | 1 – 50000 KB (default 5000) | pre_process S-2 |
| Per-document extracted text cap | `max_doc_size_kb × 1024` chars (truncated with marker) | `mineru_parse` |
| LLM content window per decision | first 4000 chars of the document | `LLMAdapter` |

Latency profile: the deterministic fallback path (no MinerU, no LLM) is in-process and ~O(total
text) — milliseconds per document. With the real MinerU VLM+OCR engine, per-document latency is
dominated by the engine (VLM inference on complex/scanned pages); with LLM-assisted routing /
chunking / metadata / quality, add one model round-trip per enabled decision per document. The
decisions are bounded (one call each) and each degrades to its deterministic fallback on failure,
so worst-case latency never blocks on a hung model.

## 9. Deployment notes

- **MinerU 3.1.0 (VLM+OCR dual engine)** — heavy optional runtime (Apache 2.0), **not installed
  in CI**. Provisioned at deploy time and injected via config (`enable_mineru: true` →
  `build_parser` constructs `MinerUAdapter`, or a pre-built engine passed as `parser`). Absent →
  the deterministic fallback runs (CI and degraded-prod stay green).
- **LLM adapter** — the raw framework `BaseLLM` is injected via runtime config (`config.llm`);
  `build_llm_adapter` wraps it and resolves the API key from the invocation context
  (`InvocationContext.from_state(state)` → `src/services/llm_factory.build_llm(ctx.secrets)`). Secrets
  come from the secrets factory, namespace **`agent1000/cmn-c1-127`** — never from process env.
- **Trust** — all three nodes require `VERIFIED_EXTERNAL`; the gateway must stamp the caller
  trust level. Config mirror: `required_trust_level: VERIFIED_EXTERNAL` in `config/agent.yaml`.

## 10. Known limitations

- **Scanned PDFs without embedded text** — extraction quality depends entirely on the MinerU
  OCR pass; the deterministic fallback (inline content) cannot recover text from raw image bytes,
  so such documents score low at the quality judge and are flagged `reparse` / `human_review`.
- **MinerU VLM language coverage** — non-Latin / mixed-script layouts (e.g. dense kanji + tables)
  are the hardest case; accuracy tracks the MinerU model's language support.
- **Chunk-plan accuracy without an LLM** — the deterministic chunk planner groups by block size
  and headings; it does not understand semantics, so boundaries are coarser than the LLM-assisted
  plan. Acceptable for ingestion; enable the LLM for best retrieval granularity.
- **Metadata inference without an LLM** — falls back to the first heading as title and the parse
  profile as doc_type (confidence 0.5); fine for well-structured docs, weaker for headingless scans.
