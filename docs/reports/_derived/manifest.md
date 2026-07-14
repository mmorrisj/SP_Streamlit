# Derived Artifacts Manifest

All objects live in the **`analytics`** schema (created for this run). `public` was treated as
read-only throughout — no app table was altered. Build scripts in this directory are
reproducible: `build_analytics.py`, then `build_entities.py`. Charts/stats:
`analyze_initiator.py <Initiator>` (engine: `rpt.py`).

Each entry below: grain · purpose · thread served · DDL sketch · refresh · **persistence
recommendation**. DDL is migration-ready — lift into `alembic/versions/` to promote into
`public` (rename to a neutral schema or prefix if promoted).

> **2026-07 theater run:** all date-scoped objects rebuilt with an explicit window end
> (`date < 2026-07-01`, last full month June 2026) on the refreshed corpus (765K docs;
> report_base now 304,846 rows, provenance_intensity 5,392). Objects 9–15 below were added
> for the cross-actor MENA Theater Assessment (`docs/reports/mena_theater/`);
> builder: `build_theater.py`, charts: `analyze_theater.py`.

---

## 1. `analytics.report_base`  — 299,027 rows
- **Grain:** one row per (doc_id, initiating_country, recipient_country, category).
- **Purpose:** the scoped, flattened fact table all metrics derive from. Pre-applies the
  mandatory filters (4 initiators; MENA recipients; initiator≠recipient; date ≥ 2024-08-01) and
  computes per-row provenance flags (`self_reported`, `recipient_focused`) from `source_geofocus`.
- **Threads:** all.
- **DDL:** see `build_analytics.py::build()` — `CREATE TABLE analytics.report_base AS SELECT … FROM
  documents JOIN initiating_countries JOIN recipient_countries JOIN categories …`, plus indexes
  `(initiating_country, recipient_country, category)` and `(month)`.
- **Refresh:** rebuild on new ingestion (full rebuild; cheap, ~seconds).
- **Persistence recommendation:** **Promote as a materialized view** in `public` (or `analytics`).
  This is the single most reusable object — it correctly encodes scope + provenance and would
  save every future query from re-deriving them. **Strong promotion candidate.**

## 2. `analytics.provenance_intensity`  — 5,361 rows
- **Grain:** (initiating_country, recipient_country, category, month).
- **Purpose:** the **bias-corrected backbone metric** — raw_docs, self_reported_docs,
  third_party_docs, recipient_focused_docs, distinct_sources, self_report_share,
  normalized_intensity (= third_party_docs). Replaces the app's raw, provenance-blind counts.
- **Threads:** all (esp. 1 & 2).
- **DDL:** `build_analytics.py` — `CREATE TABLE … AS SELECT … count(DISTINCT doc_id) FILTER (WHERE
  self_reported) … GROUP BY 1,2,3,4`.
- **Refresh:** rebuild after `report_base`.
- **Persistence recommendation:** **Promote as a materialized view.** This is the metric the
  dashboard *should* be showing instead of raw volume — it is the difference between "Iran
  dominates MENA" (artifact) and the corroborated ranking. **Strong promotion candidate.**

## 3. `analytics.actor_recipient_category_month`  — 5,361 rows
- **Grain:** same as #2, rolled to the cross-actor tensor (all four initiators in one long table).
- **Purpose:** competitive-collision, substitution, and co-movement analysis the app's
  one-pair-at-a-time summary tables cannot express.
- **Thread:** 2 (competition/blocs).
- **DDL:** `build_analytics.py` — rollup of `provenance_intensity`.
- **Refresh:** with #2.
- **Persistence recommendation:** Keep as a matview; useful for any cross-actor view. Medium
  promotion value (largely derivable from #2).

## 4. `analytics.event_entities`  — 41,846 rows (10,871 distinct events)
- **Grain:** (event_summary_id, canonical_entity_id) with entity name/type/role/country.
- **Purpose:** **fills a real schema gap** — `event_summaries.entities_mentioned` is empty.
  Reconstructs event→entity links via shared `doc_ids`
  (`daily_entity_mentions.doc_ids` ↔ `event_source_links.doc_id`).
- **Threads:** 3 (network) + citations.
- **DDL:** `build_entities.py::build_event_entities()` — `CREATE TABLE … FROM daily_entity_mentions
  CROSS JOIN LATERAL unnest(doc_ids) JOIN event_source_links JOIN canonical_entities`.
- **Refresh:** rebuild when entity/event pipelines run.
- **Persistence recommendation:** **Promote into `public`** — this is a genuine missing link the
  app itself would benefit from (it would populate `entities_mentioned` properly). **Strong
  promotion candidate.**

## 5. `analytics.entity_graph_metrics`  — 5,580 rows
- **Grain:** one row per canonical_entity that appears in `entity_relationships`.
- **Purpose:** precomputed network metrics — degree, weighted_degree, component_id,
  cross_recipient_reach. (Betweenness is computed on small per-actor subgraphs at chart time via
  Brandes in `rpt.py`.)
- **Thread:** 3 (network structure, brokers, communities).
- **DDL:** `build_entities.py::build_graph_metrics()` — table
  `(entity_id uuid PK, degree int, weighted_degree double precision, component_id int,
  cross_recipient_reach int)`, populated from `entity_relationships` + `primary_recipients`.
- **Refresh:** rebuild when `entity_relationships` changes.
- **Persistence recommendation:** Keep as an `analytics` table; promote if the app adds network
  visualizations. Medium value. (Consider adding betweenness as a stored column.)

## 6. `analytics.source_provenance_map`  — 590 rows
- **Grain:** one row per `source_name`.
- **Purpose:** dominant geofocus + doc count per outlet — the raw material for a curated
  initiator-aligned / recipient-aligned / third-party classification that would make provenance
  normalization exact rather than inferred per query.
- **Threads:** all (provenance).
- **DDL:** `build_entities.py::build_source_map()` — `CREATE TABLE … SELECT source_name,
  mode() WITHIN GROUP (ORDER BY source_geofocus) AS dominant_geofocus, count(*) … GROUP BY 1`.
- **Refresh:** cheap; rebuild on ingestion.
- **Persistence recommendation:** Promote *after* a one-time human curation pass adding an
  explicit `provenance_class` column (only ~590 sources). High value, low cost. **Promotion
  candidate (with curation).**

---

## Summary — promotion candidates for the app
| Object | Why the app wants it |
|--------|----------------------|
| `report_base` (matview) | Correct, reusable scope+provenance base |
| `provenance_intensity` (matview) | The bias-corrected metric the dashboard should display |
| `event_entities` (table) | Fills the empty `event_summaries.entities_mentioned` |
| `source_provenance_map` (+curation) | Makes provenance normalization a first-class, exact feature |

**Method note baked into the data:** `self_report_share` is a valid narrative-projection signal
**only for Iran** (82 Iran-geofocus outlets) and weakly China (2). Russia and Turkey have **zero**
domestic-geofocus outlets in the corpus, so their ~0 self-report share reflects corpus
composition, not independent validation — for them, `third_party_docs` is simply the intensity
measure. Any promoted object should carry this caveat in its documentation.

---

## 7. `analytics.us_report_base`  — 103,603 rows (61,238 distinct U.S. docs)
- **Grain:** one row per (doc_id, recipient_country, category) for U.S.-as-initiator, MENA-scoped.
- **Purpose:** the U.S. relational base. Because the corpus has **zero U.S.-geofocus outlets**,
  it replaces `self_reported` with a **`framing`** classification of each row's source:
  `adversary` (Iran-geofocus media), `partner` (Gulf/Israel/Egypt/Jordan media), or
  `neutral/other`. This powers the "adversarial-framing exposure" lens that substitutes for the
  (non-existent) U.S. self-projection signal.
- **Threads:** all of the U.S. report (esp. Thread 4, "Whose lens?").
- **DDL:** see `build_us.py::build()` — `CREATE TABLE analytics.us_report_base AS SELECT … ,
  CASE WHEN source_geofocus ILIKE '%Iran%' THEN 'adversary' WHEN <partner geofoci> THEN 'partner'
  ELSE 'neutral/other' END AS framing FROM documents JOIN … WHERE initiating_country='United States' …`.
- **Refresh:** rebuild on new ingestion.
- **Persistence recommendation:** Keep in `analytics`. The **`framing` classification is the
  reusable idea** — generalize it (per-document source alignment relative to any chosen actor) and
  it becomes a first-class provenance feature for the whole app. Medium-high promotion value.

---

## 8. `analytics.subcat_clean`  — 3,932 labels
- **Grain:** one row per distinct raw `subcategories.subcategory` value.
- **Purpose:** normalizes dirty subcategory labels for clean instrument analysis. The extraction
  leaked the prompt's A./B./C. enumeration prefixes ("I. Infrastructure", "A. Trade") and "Other-"
  wrappers; this maps each raw label to a clean canonical instrument name.
- **Threads:** category instrument-mix analysis (Economic report and the per-category series).
- **DDL:** see `build_subcat_clean.py` — `CREATE TABLE … SELECT raw_label,
  btrim(regexp_replace(subcategory, '^[A-Z]\.\s*', '')) … `, with `'Other-'` stripping; indexed on
  `raw_label` for join.
- **Refresh:** rebuild on new ingestion (cheap).
- **Persistence recommendation:** **Promote into `public`** (or fix upstream in extraction). This is
  a genuine data-quality fix the whole app benefits from — any subcategory aggregation is currently
  fragmented across "Trade"/"A. Trade"/"I. Trade". **Strong promotion candidate (or fix at source).**

---

# Theater-run additions (2026-07-09, window re-based to 2024-08-01 → 2026-06-30)

All base tables (#1–#8) were **rebuilt on the fresh corpus** (docs through 2026-07-08; the
analysis window now ends 2026-06-30 exclusive so June 2026 is the last *full* month —
`build_analytics.py` / `build_us.py` gained an `END` cutoff). New objects below are built by
`build_theater.py`; charts by `analyze_theater.py` → `docs/reports/mena_theater/assets/`.

## 9. `analytics.recipient_alias`  — 24 rows
- **Grain:** one row per raw recipient label (alias → canonical MENA name).
- **Purpose:** unifies UAE/'United Arab Emirates' and Palestine variants ('Palestinian
  Territories', 'Gaza', 'Gaza Strip', 'West Bank', 'Palestinian Authority') so no aggregate
  splits a recipient across spellings. Also the MENA scope whitelist for jsonb-key matching.
- **DDL:** `build_theater.py::build_alias()` — trivial 2-column table.
- **Persistence recommendation:** **Promote into `public`** (or fix at extraction). Every query
  that touches recipients needs this; it is 24 rows of pure correctness. **Strong candidate.**

## 10. `analytics.initiative_ledger`  — 8,555 rows
- **Grain:** one row per canonical event (named initiative), MENA-scoped, 4 initiators.
- **Purpose:** shifts the unit of analysis from documents to INITIATIVES. Per event: span,
  material_score, linked_docs (via `daily_event_mentions.doc_ids`), distinct_sources,
  self_docs/third_docs and `corroboration_share` — the per-initiative provenance gate.
  3,601 events pass the report's gate (share ≥0.5 AND sources ≥3).
- **DDL:** `build_theater.py::build_initiative_ledger()` — canonical_events × unnested
  daily_event_mentions × documents, plus jsonb-key MENA recipient extraction via recipient_alias.
- **Persistence recommendation:** **Promote as a matview.** This is the evidentiary spine of the
  theater report and the correct default ranking basis for any event UI. **Strong candidate.**

## 11. `analytics.recipient_blocs`  — 18 rows
- **Grain:** one row per canonical MENA recipient.
- **Purpose:** empirical bloc structure — ward clustering on each recipient's share-of-profile
  vector over (initiator × category) third-party volume; k=3 chosen by silhouette (0.385).
- **DDL:** `build_theater.py::build_recipient_blocs()` (sklearn AgglomerativeClustering).
- **Persistence recommendation:** Keep in `analytics`; rebuild with the window. Analytic value
  is the *labels*, which the report interprets; medium promotion value.

## 12. `analytics.relationship_changepoints`  — 100 rows
- **Grain:** (initiator, recipient, metric ∈ {third_party_docs, raw_docs}, cp_month).
- **Purpose:** formal changepoint detection (binary segmentation, pooled-variance z ≥ 2.5,
  min segment 3 months, ≤3 cps/series) replacing eyeballed trend claims; powers the
  trigger-alignment analysis (Assad falls, Jun-2025 war, Oct-2025 ceasefire).
- **DDL:** `build_theater.py::build_changepoints()` (pure numpy binseg).
- **Persistence recommendation:** Keep as `analytics` table; promote if the dashboard adds
  trend-alert features (it is exactly an alerting primitive). Medium-high value.

## 13. `analytics.narrative_themes` (8,266 rows) + `analytics.narrative_theme_summary` (342 rows)
- **Grain:** event → theme assignment; theme-level rollup.
- **Purpose:** latent-campaign discovery the 4-category taxonomy can't see: PCA(50) + KMeans
  (k = n/25 ≈ 342) over `canonical_events.embedding_vector` (768-dim), with per-theme
  `coherence` (mean cosine to centroid), TF-IDF top terms, actor/recipient distributions.
  High-coherence multi-recipient themes = coordinated campaigns (e.g. Arbaeen logistics,
  Russia-mediated nuclear talks, Hejaz railway revival, Huawei ICT competitions).
  NOTE: plain HDBSCAN collapses this corpus into one mega-cluster — that failure and the
  PCA+KMeans fix are documented in `build_theater.py::build_narrative_themes()`.
- **Persistence recommendation:** Keep in `analytics`; regenerate per run (k tracks corpus
  size). The *coherence* column is the reusable idea. Medium value.

## 14. `analytics.geo_intensity`  — 3,372 cells
- **Grain:** (initiator, lat, lon) at 0.25° grid over parsed `documents.lat_long` (97.7% populated).
- **Purpose:** first sub-national view — where influence activity physically lands (docs +
  third_party_docs per cell, modal location label). Powers the geo bubble map.
- **Persistence recommendation:** Promote as matview if the app adds any map view; the parse
  regex + gridding is the reusable part. Medium value.

## 15. Chart engine — `analyze_theater.py`
11 figures + sibling CSVs in `docs/reports/mena_theater/assets/`; all plot corroborated
metrics (raw only as contrast), fixed actor palette (validated for CVD safety), deterministic.

---

# Theater-run additions (2026-07, `build_theater.py`)

## 9. `analytics.recipient_alias`  — 24 rows
- **Grain:** one row per recipient-name alias → canonical MENA recipient.
- **Purpose:** unifies UAE/United Arab Emirates and Palestine variants (Palestinian
  Territories/Authority, Gaza, Gaza Strip, West Bank) so no aggregation splits a recipient.
- **DDL:** `build_theater.py::build_alias()` — `(alias text PK, canonical text)`.
- **Refresh:** static; extend when new variants appear.
- **Persistence recommendation:** **Promote into `public`** (tiny, universally useful) — or fix
  at extraction. Every recipient GROUP BY in the app currently splits UAE across two labels.

## 10. `analytics.initiative_ledger`  — 8,555 rows
- **Grain:** one row per canonical event (named initiative), MENA-scoped, 4 initiators.
- **Purpose:** **the honest unit of analysis** — initiatives, not articles. Carries per-event
  provenance (linked_docs, distinct_sources, self_docs, third_docs, corroboration_share) built
  by unnesting `daily_event_mentions.doc_ids` → `documents`, plus material_score, span, and
  alias-canonicalized `mena_recipients`. The corroboration gate (share≥0.5 AND sources≥3)
  passes 3,601 events and is the report's citation spine.
- **DDL:** `build_theater.py::build_initiative_ledger()`.
- **Refresh:** rebuild when event pipelines run.
- **Persistence recommendation:** **Strong promotion candidate.** The app has no
  initiative-grain provenance anywhere; this is the single most decision-relevant derived
  object of the run (it is what inverts the Iran-dominance illusion).

## 11. `analytics.recipient_blocs`  — 18 rows
- **Grain:** one row per canonical MENA recipient.
- **Purpose:** empirical blocs — ward clustering on each recipient's share-of-profile vector
  over (initiator × category) third-party volume; k=3 chosen by silhouette (0.385). Stores
  bloc_id + full profile JSON.
- **DDL:** `build_theater.py::build_recipient_blocs()`.
- **Refresh:** re-run after provenance_intensity; deterministic.
- **Persistence recommendation:** Keep in `analytics`; refresh per report cycle. Labels are
  analytic artifacts, not app facts.

## 12. `analytics.relationship_changepoints`  — 100 rows (third-party metric) + raw-metric rows
- **Grain:** one row per detected changepoint per (initiator, recipient, metric).
- **Purpose:** formal temporal inflections — binary segmentation (min segment 3 months,
  |z|≥2.5, max 3 cps) over monthly series; replaces eyeballed trend claims. Top signal:
  Iran→Yemen Dec-2024 decline z=11.4.
- **DDL:** `build_theater.py::build_changepoints()` (algorithm: `binseg_changepoints()`).
- **Refresh:** monthly, after provenance_intensity.
- **Persistence recommendation:** Keep as `analytics` table; promote if the dashboard adds
  trend-alerting (it directly powers an "inflection detected" feature).

## 13. `analytics.narrative_themes`  — 8,529 rows · `analytics.narrative_theme_summary` — 342 rows
- **Grain:** event → theme assignment; per-theme rollup.
- **Purpose:** latent campaign discovery — PCA(50) + KMeans(k=n/25, seed 42) over
  `canonical_events.embedding_vector` (768-dim), with per-theme cosine coherence, TF-IDF top
  terms, actor/recipient distributions. High-coherence multi-recipient themes = coordinated
  campaigns (e.g. Arbaeen logistics, Oman-channel nuclear talks, Hejaz railway revival).
  (HDBSCAN collapses this corpus into one mega-cluster; KMeans at fine k is the right tool.)
- **DDL:** `build_theater.py::build_narrative_themes()`.
- **Refresh:** rebuild when canonical_events grows; deterministic given fixed seed.
- **Persistence recommendation:** Keep in `analytics`. Theme IDs are not stable across
  rebuilds — never foreign-key them from `public`.

## 14. `analytics.geo_intensity`  — 3,372 cells
- **Grain:** (initiating_country, lat, lon) at 0.25° grid.
- **Purpose:** first sub-national view — exploits the 97.7%-populated `lat_long`, with
  raw/third-party split and modal location label per cell. Powers the geo bubble map.
- **DDL:** `build_theater.py::build_geo_intensity()` (regex-guarded lat_long parse).
- **Refresh:** rebuild on ingestion.
- **Persistence recommendation:** Promote as matview if the app adds any map view; otherwise
  keep in `analytics`.

## 15. (report assets) `docs/reports/mena_theater/assets/*.png|csv`
Eleven charts, each with its underlying numbers persisted as a sibling CSV for audit
(01 provenance quadrant · 02 corroborated leaderboard · 03 initiative gate · 04 category
signature · 05 competitive heatmap by bloc · 06 Syria substitution · 07 tempo+changepoints ·
08 geo bubble · 09 Lorenz/HHI · 10 initiative ledger top · 11 narrative themes).

**Updated promotion shortlist (theater run):** `initiative_ledger` and `recipient_alias` join
`report_base`, `provenance_intensity`, `event_entities`, `subcat_clean` as strong candidates.
