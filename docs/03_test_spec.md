# docs/03_test_spec.md — CMN-C1-127 Test Specification

**Template ID:** CMN-C1-127
**Category:** Cat 1 | CMN
**Scope:** unit (nodes + services + adapters) · integration (compile + invoke) · proof-of-boundary.

All tests are deterministic — **no live LLM and no MinerU runtime**. The LLM and MinerU engine are
duck-typed and exercised with fakes/stubs; the production paths degrade to deterministic fallbacks
when neither is injected, which is the path CI verifies.

---

## 1. Test inventory

| File | Suite | Covers |
|---|---|---|
| `tests/unit/test_nodes.py` | unit | `PreProcessNode` / `MainNode` / `PostProcessNode` `.execute()` |
| `tests/unit/test_services.py` | unit | 7 services: routing, mineru_parse, semantic_chunk, metadata_infer, quality_judge, output_render, output_safety |
| `tests/unit/test_adapters.py` | unit | `LLMAdapter`, `MinerUAdapter`, `build_parser` |
| `tests/integration/test_graph.py` | integration | full `compile()` + `invoke()` |
| `tests/proof_of_boundary/test_pb_domain.py` | PB | domain security invariants (PB-D1..D9) |
| `tests/proof_of_boundary/test_import_isolation.py` | PB | PB-4 import isolation (AST) |
| `tests/proof_of_boundary/test_state_safety.py` | PB | PB-2 / PB-5 state safety (AST) |

## 2. Unit — nodes (`test_nodes.py`)

| Case | Expectation |
|---|---|
| pre_process success routes documents | SUCCESS; `routing_plan` per doc; pdf → `vlm_ocr_dual` |
| pre_process reads JSON envelope from user_input | SUCCESS; `output_format` taken from the envelope |
| pre_process empty documents | ERROR (S-2) |
| pre_process all rejected | ERROR; rejected docs listed |
| pre_process max_kb out of range | ERROR (S-2) |
| pre_process max-documents boundary | 100 → SUCCESS; 101 → ERROR |
| pre_process non-dict entries | ERROR (S-2) |
| main parses + plans | SUCCESS; parsed docs, chunk plan, inferred metadata |
| main no routing_plan | ERROR (propagated pre_process failure) |
| main partial parse failure | doc that raises in the MinerU adapter falls back (`parser="fallback"`); others keep `parser="mineru"`; overall SUCCESS |
| post_process renders + judges | SUCCESS; `quality_judge_executed=True`; report rendered |
| post_process json / both output | json starts with `{`; both contains the markdown header and a ```json block |
| post_process redacts secret in extracted text | `redaction_triggered=True`; `REDACTED` in output |

## 3. Unit — services (`test_services.py`)

Routing (deterministic profile + name-extension inference, unsupported → rejected; LLM override;
LLM-failure fallback), mineru_parse (inline fallback, oversize truncation, injected adapter),
semantic_chunk (block grouping, empty doc, heading-boundary split), metadata_infer (heading
fallback; LLM sets `source="llm"`), quality_judge (executed always True, deterministic scoring,
LLM score used), output_render (markdown / json), output_safety (anti-suppression, secret
redaction, injection blanking).

## 4. Unit — adapters (`test_adapters.py`)

`LLMAdapter`: classify_route valid/invalid profile, LLM error → None, code-fence JSON; plan_chunks
array / garbage; infer_metadata clamps confidence, None without title; judge_quality score / missing
score. `MinerUAdapter`: parse with injected engine, plain-string normalization, ImportError without
runtime. `build_parser`: injected parser returned, None by default, None when MinerU unavailable.

## 5. Integration (`test_graph.py`)

Full `agent.invoke(envelope, ctx=VERIFIED_EXTERNAL)`: (a) happy path → `status == "success"`,
`result["output"]["report"]` contains `# Parsed Document Set`, `MainNode` in `node_history`;
(b) JSON output → report starts with `{`; (c) empty documents → `status in ("error","cancelled")`.

## 6. Proof-of-Boundary (`test_pb_domain.py` + framework PBs)

| ID | Proof |
|---|---|
| PB-D1 | Quality judge is non-suppressible (`apply_output_safety` blocks when `quality_judge_executed=False`) |
| PB-D2 | Secret pattern redacted before output |
| PB-D3 | Injection marker blanks the output |
| PB-D4 | Credential-assignment regex redacts |
| PB-D5 | `IGNORE PREVIOUS INSTRUCTIONS` blanks output |
| PB-D6 | `Bearer <token>` redacted |
| PB-D7 | JWT (`eyJ…`) redacted |
| PB-D8 | All-rejected document set → no per-document content leak (empty routing plan → node ERROR) |
| PB-D9 | `quality_judge_executed` stays True even when a malicious LLM returns `executed:false` |
| PB-4 | No `agenticstar` / platform-L0 imports under `src/` (AST) |
| PB-2 / PB-5 | State has no credential-named fields and no `BaseModel` / `InvocationContext` annotations (AST) |

## 7. Edge cases

All-rejected documents, oversized documents (truncation), MinerU adapter failure → fallback, LLM
stub failure → deterministic fallback, mixed supported/unsupported sets, headingless scans.

## 8. Stage ⑤ STG checklist

- `docs/07_operation_guide.md` committed + `run-tests` green on `develop` (the integration
  `invoke()` is the first-invoke proof). No manual develop→main promote / STG deploy ritual.
