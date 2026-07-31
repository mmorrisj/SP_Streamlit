# Evaluation Findings — 2026-07-29/30

> **2026-07-31 remediation update.** The two biggest gaps (F1/F2) are
> resolved. Root cause of F2 was a batch-path design gap: the batch loader
> skipped single-name clusters but nothing marked them processed or created
> their events — 88,785 clusters (the majority of real daily events) were
> absent from the event layer. A backfill created their canonical events
> (0 LLM cost, 0 errors); all 98,218 event vectors were re-embedded into the
> prefixed space (F8) with writers standardized via
> `model_cache.embed_for_storage`; then windowed Stage-2A consolidation
> (layered, cosine 0.90), batch LLM validation of all 8,680 groups
> (23 batch jobs, 0 failures, 157+ over-merges split), and the 2C merge ran
> to completion. Final state: **76,690 masters covering 100% of clustered
> signal** (was 9,484 covering 23%), ~10K multi-day events, deconfliction
> coverage 100%, traceability 100%, residual near-window dup rate ~4×
> lower — with the residue now dominated by *generic event names*
> ("Memorandum of Understanding"), i.e. the F4 extraction problem, plus the
> known monthly-window boundary limitation. Fixed along the way: batch_submit
> KeyError that created untracked real batches on retry (56 orphans
> cancelled), cross-boundary date/datetime crash in
> layered_consolidate_events, stale llm_validated flags on masters that
> gained new children. Note `llm_validated_rate` now reads ~20% by design:
> ungrouped singleton events have no grouping to validate.
>
> Also landed: HNSW expression indexes on both embedding columns
> (`(embedding_vector::vector(768)) vector_cosine_ops`, partial on masters)
> and an index-driven rewrite of the RAG semantic entity tier (order by raw
> distance + candidate LIMIT). Entity-matching eval identical post-change.
> A full column-type migration to `vector(768)` was deliberately deferred:
> it touches every reader/writer (psycopg2 returns unregistered vector
> columns as strings) and should ride a proper release. New repo finding:
> **alembic has three heads** (006_search_vector, 20260224_aiddata,
> 20260612_ingestion_jobs) — needs a merge revision before any new
> migration is added.

First full run of the evaluation harness (`evals/`). All metrics are internal
measures (methodological soundness, faithfulness to the corpus) — the media-lens
bias of the source data means nothing here claims ground-truth accuracy about
world events. Runs are seeded and stratified by initiating country.

Environment: live Postgres (779,075 docs; 2024-07-03 → 2026-07-27), embedding
components run inside the `sp_laptop_app` container (host Python has no torch),
LLM probes via the container proxy (gpt-4o-mini class).

## Scorecard

| Layer | Verdict | Headline numbers |
|---|---|---|
| Report validator | **Sound** | 7/7 rule cases correct (hallucination⇒FAIL, empty priority⇒FAIL, zero coverage⇒FAIL, low coverage⇒WARN-pass) |
| Report scope handling | **Sound** | 9/9 branches: tracked-initiator pass, recipient pivot, unknown/date/target rejections all correct |
| Agent tool contracts | **Sound** | 16/16 live-DB cases pass; mean latency 72 ms, max 344 ms |
| Report deterministic stages | **Sound** | 6/6 stages ok on China–Egypt H1-2025 (1,598 docs → 32 events → 8 prioritized; trajectory "cooling"/MED) |
| Entity matching (3-tier) | **Good** | exact hit@10 1.00, alias 0.98, typo 0.88, gibberish FP 0/3; all tiers live (semantic fired 1,170×) |
| Extraction reliability | **Good** | positive-salience stability 75/75; category F1 0.87 (P=1.0), initiator F1 0.83, recipient F1 0.78 |
| Event traceability | **Sound** | 1,320 sampled mention doc_ids → 100% resolve to documents (entities likewise 100%) |
| Daily event clustering | **Good** | intra-cluster cosine 0.906 vs 0.550 random baseline |
| Retrieval | **Mixed** | hybrid known-item MRR 0.52 (2× vector-only 0.28); event-evidence recall@50 only 0.15; rerank *hurts* known-item (MRR→0.20) but helps topical (event hit@5 0.52→0.73); entity boost +48% event recall@25 |
| Stage-2 event consolidation | **Behind** | 57.5% masters LLM-validated; 541 (Iran) + 186 (China) near-window duplicate master pairs ≥0.90 incl. literal same-name pairs ("Belt and Road Initiative" ×2) |
| Stage-1b deconfliction backlog | **Behind** | only 22.7% of 114,869 clusters LLM-deconflicted |
| Taxonomy governance | **Drifted** | 29.6% of subcategory rows (298,667) use values outside config.yaml ("International Negotiations" 144K, "Aid/Donation" 96K) |
| RAG answers | **Good, one weak spot** | citation validity 100%, out-of-corpus refusal 2/2, groundedness mean 0.69 (two answers 1.0, one 0.75, one 0.0) |
| Agent converse doctrine | **Strong** | 3/3 doctrine probes: provenance_stats for volume comparisons, activity_series for trends, entity_lookup for entities |
| Intent classifier | **Gap found** | 3/4; proposed a report run for an untracked initiator (Brazil) — only the downstream tool rejects it |
| Full report run (validator-scored) | **Guardrail works; quality gaps real** | validator correctly FAILED the live run: 2 hallucinated-citation attempts, claim citation coverage 40% (<60% threshold); entity citation coverage 100% |

## Findings in detail

### F1. Stage-2 consolidation debt is the biggest data-quality gap
9,484 master events, 42.5% never LLM-validated; residual-duplicate scan finds
hundreds of same-country pairs with cosine ≥ 0.90 within 30 days — including
pairs with *identical canonical names*. Duplicates fragment article counts,
materiality, and timelines, which feeds directly into event_prioritizer's
`materiality × ln(articles)` ranking (a split event is under-ranked).
Action: run Stage 2A→2C to completion; add the residual-dup metric as a
post-run regression gate.

### F2. Stage-1b backlog: 77% of daily clusters never deconflicted
114,869 clusters, 26,083 deconflicted. Canonical events only exist for
deconflicted clusters, so most clustered raw signal has not reached the event
layer. Root cause identified 2026-07-30: the June update re-clustered the
entire corpus (103,902 clusters created June 2026) and the deconfliction
batch jobs running since June 27 have covered ~23% so far — this is an
in-progress rebuild, not historical loss. (Correction: the initially reported
"107 fail-open clusters" was an eval regex false-positive — `%error%`
matched "counter-terrorism" in legitimate explanations; the true fail-open
count is 0. The fail-open *code path* was still real and has been fixed to
fail closed.)

### F3. Retrieval: hybrid is the right default; reranker is query-type-sensitive
- BM25+vector RRF doubles known-item MRR vs pure vector (0.52 vs 0.28) —
  hybrid search is earning its complexity.
- The cross-encoder reranker *helps* topical/event queries (hit@5 0.52→0.73,
  MRR 0.36→0.51) but *badly hurts* known-item/title queries (MRR 0.52→0.20).
  ms-marco-MiniLM ranks topically-related content above the exact source doc.
  **Fixed 2026-07-30**: `rerank_results` now fuses rerank and retrieval
  rankings via RRF (`rag.rerank_blend_alpha`, default 0.6) and pins the
  retrieval top-1 into the post-rerank top-3. Paired re-measurement:
  known-item hit@5 restored to no-rerank parity, event MRR improved to 0.55
  (from 0.51 under pure rerank). Score-blending alone was tried first and
  did NOT work — the cross-encoder buries exact matches too deep for any
  score normalization to recover; rank fusion + the pinned slot is the
  effective mechanism.
- Entity boost works as designed: event-evidence recall@25 0.118→0.175
  (+48%), hit@5 0.53→0.73 in the intelligent path.
- Known-item hit@50 plateaus at ~0.55 — and correcting for the corpus's 20.3%
  title-duplication changed nothing, so it's not a twin-document artifact.
  ~45% of docs are simply not surfaced by their own title within 50 results.
  Worth a follow-up: measure per-collection and per-language.
- Event-evidence recall@50 = 0.15: a bare event name only recovers a sliver
  of the evidence base the event layer links. Answer paths that need full
  evidence should traverse `daily_event_mentions.doc_ids` (as the report
  pipeline does) rather than re-searching.

### F4. Extraction is stable but the taxonomy has forked
Re-extraction on stored distilled text reproduces salience 75/75 and
categories at F1 0.87 with perfect precision — the pipeline's labels are
reproducible, and disagreements are mostly dropped secondary labels.
But the subcategory vocabulary in `shared/utils/prompts.py` and what's in
`shared/config/config.yaml` have diverged: 29.6% of rows use prompt-emitted
values absent from config ("International Negotiations", "Aid/Donation",
"Transportation", `Other-*`). Any dashboard/filter driven by config.yaml
silently excludes ~300K rows. Also: `salience_bool` has 37 rows of 'True'/
'False' casing (SQL `='true'` misses them) and 54 persisted docs are marked
non-salient — both contradict documented invariants.

### F5. Salience gate: negatives clean, recall unproven
5/5 non-salient controls rejected; but 1 of 2 clearly-salient controls
(a China–Egypt concessional-loan infrastructure item) was rejected, and gate
recall is structurally unmeasurable from the DB (only passing docs persist).
Recommend: retain per-CSV `results.json` and sample-audit rejected rows.

### F6. Entity layer is in good shape
100% of 10,999 masters have 768-dim embeddings; matcher passes all liveness
and perturbation probes; residual duplication is minimal (1 pair ≥0.88 in
Iran's 1,614 masters — "Ali Khamenei" vs "Ayatollah Seyed Ali Khamenei").
Two soft spots: exact-tier ranks by document count so the intended target is
rank-1 only 60–72% of the time when look-alikes exist, and description
coverage is 46% (semantic paraphrase matching can't work for the other half).

### F7. Guardrails at the agent layer verify correctly
The validator's whole rule table behaves as specified (hallucinated citations
are a hard FAIL), scope validation pivots/rejects exactly per design, and the
`validate_recipient` helper errors loudly on groups/unknowns — with one
ergonomic gap: `"the Gulf"` (leading article) misses the group table and
returns the generic unknown-recipient error.

### F8. Embedding-space inconsistency is real but bounded
Event-name rankings in raw vs `search_document:`-prefixed space agree at
Spearman 0.955. The 4.5% divergence isn't catastrophic, but entity vectors
now mix both spaces (re-embed wrote prefixed; new entities are written
unprefixed), so consolidation thresholds are applied inconsistently across
rows. Standardize on the prefixed wrapper everywhere.

### F9. Chat answers: citations are honest, but coverage is uneven
All emitted `[N]` citations resolved to real returned sources (100% validity)
and both out-of-corpus trap questions were refused rather than fabricated.
Sentence-level groundedness averaged 0.69: two answers fully supported, one
at 0.75, and one (Iran cultural outreach in Lebanon) that carried a single
citation and failed its judge check — the model wrote synthesis prose beyond
what the cited snippet supports. Pattern to watch: answers with *few*
citations are the risky ones; consider a minimum-citation-density check in
the chat path like the report pipeline already has.

### F10. Converse agent follows the bias doctrine; intent layer has a hole
All three doctrine probes passed — the agent called `provenance_stats`
(4×) before making a cross-actor volume claim, `activity_series` for the
trend question, and `entity_lookup` before profiling a person. This is the
media-lens mitigation working at the behavioral level, not just in prompt
text. However, the intent classifier proposed a report run for
**Brazil** (untracked initiator) — the trap case failed. Defense-in-depth
holds (propose_report and data_qa both catch it downstream), but the intent
prompt should carry the tracked-influencer list so users get the pivot/
refusal message immediately instead of a doomed proposal.

### F11. Full report run: the validator catches real hallucinations
End-to-end run (China–Egypt H1-2025): all 11 upstream stages succeeded —
8/8 events narrated, 25 claims extracted, 7 entities curated and 100%
entity-cited — and the validator then correctly **failed** the run: the
narrator attempted 2 doc_id citations outside its allow-list (stripped, but
flagged as errors by design), and claim-level citation coverage landed at
40%, under the 60% warning threshold with 15 of 25 claims unsourced. This is
the intended behavior (a report with hallucinated or thin sourcing is not
analyst-ready), and it localizes the quality work: the sourcing_claims stage
(confidence 0.4) is the bottleneck, not narration or entity curation.

## Measurement caveats (read before quoting numbers)
- Known-item and event-evidence gold are self-referential (system's own link
  structure); ablation deltas are more trustworthy than absolute levels.
- Re-extraction agreement measures stability, not accuracy; original ran on
  raw title+body which is not persisted.
- LLM-judged metrics use the same model family as the system under test.
- Salience-control sets are tiny (5 neg / 2 pos) — directional only.
- Single-scope report-stage run (China–Egypt H1-2025).
