# Evaluation Harness — Soft Power Analytics

A technical/methodological evaluation of every functional layer of the
platform: extraction, event and entity pipelines, retrieval, the RAG chat
path, the agent tool layer, and the report workflow.

```
python -m evals.run_eval --list                 # enumerate components
python -m evals.run_eval                        # all non-LLM components
python -m evals.run_eval --no-embed             # skip embedding-model probes
python -m evals.run_eval --llm                  # include LLM-gated probes ($)
python -m evals.run_eval --components retrieval entity_matching
```

Results land in `evals/results/` as a timestamped `.json` (full per-case
records) and `.md` (summary tables). Sampling is seeded (`20260729`) and
stratified by initiating country, so runs are reproducible and no single
media ecosystem dominates the metrics.

## Framing: what this eval does and does not claim

The corpus carries a **media-lens bias** — most prominently a heavy
over-representation of Iranian state media. No internal metric can correct
for what the collection pipeline never saw. Consequently every component is
evaluated on **methodological soundness and faithfulness to the corpus**,
never on ground-truth accuracy about the world:

* Extraction is scored on *validity and stability* (does the same input get
  the same labels; do labels conform to the declared taxonomy), not on
  whether the labels are "true".
* Retrieval is scored on *self-consistency gold* (known-item and
  event-mention sets derived from the system's own link structure).
* Answers are scored on *groundedness* — does every claim trace to a
  retrieved document — which is exactly the property that keeps the media
  lens visible instead of laundering it into confident prose.
* The agent layer is additionally scored on *bias-handling behavior*: the
  converse doctrine mandates `provenance_stats` before cross-actor volume
  claims; `converse_behavior` checks the agent actually does that.

## Components

| Component | Layer | Needs | What it measures |
|---|---|---|---|
| `extraction_integrity` | ingestion | DB | salience-field hygiene, taxonomy conformance (categories/subcategories vs config), denormalized-vs-normalized consistency, generic event-name rate |
| `extraction_reliability` | ingestion | DB+LLM | salience gate positive/negative controls; re-extraction label stability (category/country/salience agreement vs stored) |
| `events_pipeline` | events | DB(+embed) | deconfliction coverage, LLM fail-open rate, DBSCAN cluster cohesion vs cross-pair baseline, residual duplicate masters (sim≥0.90 within 30d), mention→document traceability, raw-vs-prefixed embedding rank divergence |
| `entities_structural` | entities | DB | master/dim/alias/description coverage, residual duplicate masters at the pipeline's own 0.88 threshold, mention traceability |
| `entity_matching` | RAG | DB+embed | three-tier matcher behavior: exact-name, alias, typo, description-paraphrase probes (hit@10, rank-1), gibberish false-positive controls, per-tier liveness (silent pg_trgm/pgvector degradation detection) |
| `retrieval` | RAG | DB+embed | known-item + event-mention recall/MRR with ablations: hybrid vs vector-only, rerank on/off, entity boost on/off, HyDE (LLM-gated) |
| `rag_answers` | chat | DB+LLM+API | citation validity (deterministic), sentence-level groundedness (LLM judge), out-of-corpus refusal correctness |
| `agent_tools_contract` | agent | DB | every DB-backed tool's contract on live data: ok-semantics, shape, edge behavior (empty≠error, missing arg=error, unknown recipient=loud error), latency |
| `report_scope_matrix` | agent | — | propose_report branch coverage: tracked initiator, recipient pivot, unknown rejection, date rejection; validate_recipient alias/group/unknown |
| `report_deterministic_stages` | report | DB | stages 1–6 live: scope resolution, data QA counts/sufficiency, prioritization, anomaly, comparison, trajectory coherence |
| `report_validator_rules` | report | — | the analyst-readiness guardrail: synthetic contexts prove hallucinated citations / empty priority / zero coverage FAIL and sub-threshold coverage WARNs |
| `report_full_run` | report | DB+LLM | one end-to-end pipeline run scored by the validator's own metrics (~31 LLM calls) |
| `converse_behavior` | agent | DB+LLM | intent-classification accuracy; doctrine adherence (volume→provenance_stats, trend→activity_series, entity→entity_lookup); sources emission |

## Gold-data strategy

There are no human labels, so gold is constructed three ways, each with its
bias declared in the component's `caveats`:

1. **Structural self-consistency** — the system's own link structure
   (event↔mention↔document, entity↔mention↔document) is treated as gold for
   traceability and retrieval. Inherits upstream errors; declared.
2. **Perturbation/controls** — synthetic negatives (gibberish entities,
   non-salient texts, out-of-corpus questions) and perturbed positives
   (typos, aliases, paraphrases) with known expected behavior.
3. **LLM re-judgment** — stability under re-extraction and judge-scored
   groundedness. Measures reliability, not accuracy; judge and generator are
   the same model family, so leniency bias is possible.

Disagreement cases are dumped into the results JSON specifically to serve as
a **seed set for human annotation** — the cheapest path to real gold is to
adjudicate the cases where the system disagrees with itself.

## Known measurement limits

* **Salience recall is unmeasurable from the DB** — only gate-passing docs
  are persisted. Measuring missed-salient rate requires the ingestion
  `results.json` files or a re-run over a raw CSV with the gate disabled.
* **Event identity has no gold** — cohesion/duplication metrics live in the
  system's own embedding space and detect inconsistency, not correctness.
* **`intelligent_search` ignores `k` when reranking is on** — ablation
  sweeps toggle module flags instead.
* **Caches** — `analytics_table_exists`, insight-report sections, and config
  loaders are `lru_cache`d per process; a harness that mutates state must
  `.cache_clear()`.
* **Import-time env** — set `AGENT_MAX_TURNS` / `AGENT_DOCUMENT_SEARCH_USE_MCP`
  before importing agent modules (`agent_tools_contract` sets MCP=false to
  test in-process behavior deterministically).
