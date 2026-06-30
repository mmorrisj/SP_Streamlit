# Derived Artifacts Manifest

All objects live in the **`analytics`** schema (created for this run). `public` was treated as
read-only throughout — no app table was altered. Build scripts in this directory are
reproducible: `build_analytics.py`, then `build_entities.py`. Charts/stats:
`analyze_initiator.py <Initiator>` (engine: `rpt.py`).

Each entry below: grain · purpose · thread served · DDL sketch · refresh · **persistence
recommendation**. DDL is migration-ready — lift into `alembic/versions/` to promote into
`public` (rename to a neutral schema or prefix if promoted).

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

## 8. `analytics.subcat_clean`  — 3,865 labels
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
