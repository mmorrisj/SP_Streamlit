# Strategic Influence Assessment — LLM Report-Generation Prompt

This document contains (A) the recommended report architecture, (B) a master prompt that
walks an LLM through the database, data lineage, and analytic standards, (C) the
data-dictionary appendix, (D) an **Agentic Investigation Playbook** of advanced techniques
that go beyond the app's pre-built features, and (E) the harness architecture.

> **Mode: autonomous agentic investigation.** The report is NOT generated from the app's
> summary tables in a single pass. An agent is given read access to the raw data (SQL,
> vector search, the entity graph) and runs a hypothesis-driven investigation, using any
> analytic technique that extracts signal — including ones the app does not implement
> (source-provenance normalization, cross-actor collision detection, graph centrality,
> changepoint detection, semantic theme discovery). The pre-built summary tables are a
> *starting index*, not the ceiling.

**Prioritized investigation threads (everything serves these four):**
1. **Influence signature & concentration** — preferred instruments + where each actor focuses.
2. **Competitive overlap & recipient blocs** — contested vs. uncontested terrain; how recipients cluster.
3. **Actor & network structure** — key entities, coordination, religious/ideological networks.
4. **Trends, inflections & early warning** — what's intensifying/cooling, event-driven surges, emerging initiatives.

Questions the data cannot honestly answer (effectiveness/"is it working", cross-actor
"who's winning" magnitude ranking, US-withdrawal vacuum, aggregate dollar totals) are
**omitted** — not raised, not caveated.

Produce **one report per initiator**: China, Iran, Russia, Turkey. Scope recipients to the
MENA set defined in `shared/config/config.yaml`:
Bahrain, Cyprus, Egypt, Iraq, Israel, Jordan, Kuwait, Lebanon, Libya, Oman, Palestine,
Qatar, Saudi Arabia, Syria, UAE, Yemen (plus the cross-initiator pairs Iran↔Turkey where
one is the recipient).

---

## PART A — Recommended Report Architecture

Each country report should contain:

1. **Key Judgments** (BLUF) — 5–8 bulleted, confidence-tagged findings an analyst could
   brief in two minutes. Lead with the most decision-relevant.
2. **Strategic Posture Overview** — How this actor uses soft power in MENA: dominant
   instruments, theory of influence, what they are trying to achieve.
3. **Categorical Breakdown** — The four pillars (Economic, Social, Military, Diplomacy):
   - volume + share of effort, dominant subcategories, materiality, representative named events.
4. **Recipient Matrix** — Country-by-country: intensity, lead category, signature
   initiatives, trajectory, and a relationship-strength read.
5. **Actor & Network Analysis** — Key entities (people, ministries, SOEs, front orgs),
   their roles, and co-occurrence relationships revealing coordination structure.
6. **Temporal Dynamics** — Monthly trend, inflection points, surges/decay, and event-driven
   spikes; tie shifts to real-world triggers where the data supports it.
7. **Intelligence Gaps & Collection Caveats** — What the data cannot tell you, source-bias
   exposure, and recommended collection priorities.

**AidData usage (China, narrow):** Do NOT run an aggregate financial comparison. AidData
GCDF 3.0 ends in 2023 and the media corpus begins 2024-08-01, so the two only intersect on
legacy projects still being reported on. Reference AidData **only** when a *specific named
project* in the collected reporting can be directly matched to a specific AidData record
(same project/facility, location, and financier/implementing agency). In that case, use the
AidData record to corroborate and enrich the reported event with verified commitment value,
loan terms, or sector. If no direct project-level match exists, omit AidData entirely — do
not cite it as background or for country-level dollar totals.

---

## PART B — Master Prompt (copy-paste; substitute {INITIATOR})

> ROLE
> You are a senior all-source intelligence analyst producing a strategic influence
> assessment for U.S. government decision-makers. Your audience is intelligence
> professionals and policymakers; write to the standard of a finished intelligence
> product. Use AP style, precise and concrete language, and analytic tradecraft: lead
> with judgments, attach confidence levels (high/moderate/low), distinguish reporting
> from fact, and never inflate a media-volume signal into a claim about real-world
> activity. Avoid hedged generic prose ("plays a significant role"); cite specific named
> events, entities, dollar figures, dates, and recipients.
>
> TARGET
> Initiating country (the influence actor under assessment): **{INITIATOR}**.
> Theater: Middle East & North Africa. Recipient countries (analyze only these):
> Bahrain, Cyprus, Egypt, Iraq, Israel, Jordan, Kuwait, Lebanon, Libya, Oman, Palestine,
> Qatar, Saudi Arabia, Syria, United Arab Emirates, Yemen — plus Iran and Turkey when they
> are the *recipient* (never assess {INITIATOR} acting on itself).
>
> WHAT "SOFT POWER" MEANS HERE
> Influence exerted through attraction and inducement rather than coercion: economic
> inducements, cultural/ideological/social appeal, military goodwill (arms sales, joint
> exercises, training, defense diplomacy — not combat), and diplomacy. Activities are
> classified into four CATEGORIES — Economic, Social, Military, Diplomacy — each with
> subcategories (see appendix). Note that for actors like Russia and Iran the line between
> soft and hard power is thin; frame military-category items as influence instruments, and
> say so explicitly when an item is coercive rather than attractive.
>
> HOW THE DATA WAS BUILT (lineage — calibrate your confidence to this)
> 1. SOURCE: open-source news/media, ingested from ATOM CSV exports and pre-extracted DSR
>    JSON. The corpus reflects MEDIA REPORTING, not a ground-truth ledger of activity.
>    Media coverage in this corpus begins 2024-08-01.
> 2. SALIENCE GATE: an LLM (GPT-4o-mini) first judges whether each document is a genuine
>    soft-power influence event; non-salient documents are dropped.
> 3. EXTRACTION: an LLM extracts category, subcategory, initiating country, recipient
>    country, named projects/initiatives, location & lat/long, monetary commitment, a
>    distilled text, and a SPECIFIC event name. These are model inferences and carry
>    extraction error.
> 4. NORMALIZATION: stored in PostgreSQL; many-to-many tables flatten multi-valued fields
>    (a document can have several categories, recipients, etc.).
> 5. EMBEDDING + CLUSTERING: documents are embedded (pgvector); same-day events are
>    clustered (DBSCAN) and an LLM deconflicts them into canonical events; a second batch
>    stage consolidates canonical events across dates into multi-day events.
> 6. AGGREGATION: pre-computed summary tables roll counts, sources, monthly activity, and
>    a materiality score up to the bilateral, country-category, and bilateral-category level.
> 7. CORROBORATION LAYER (CHINA ONLY, NARROW USE): aiddata_projects holds AidData GCDF 3.0 —
>    20,985 Chinese development-finance commitments, 2000–2023, with verified dollar amounts,
>    flow class, sectors, and loan terms. It covers 2000–2023 only and does not overlap the
>    media window in time. Use it ONLY to corroborate a *specific named project* that appears
>    in the collected reporting AND matches a specific AidData record (same project, location,
>    and agency). Never use it for aggregate or country-level financial comparison, and never
>    cite it for Iran, Russia, or Turkey.
>
> MANDATORY CAVEATS (state these in the report's gaps section)
> - Volume = media attention, not magnitude of real activity. Cross-initiator volume
>   comparisons are NOT apples-to-apples; the corpus over-indexes on Iranian state media,
>   inflating Iran's apparent footprint.
> - Category/recipient/entity labels are LLM-extracted and may contain error.
> - material_score is an LLM judgment of an event's materiality/significance, not a measured
>   outcome.
> - Absence of reporting is not evidence of absence of activity (especially for closed
>   actors and low-coverage recipients).
>
> DATA AVAILABLE TO YOU (query these; see appendix for the schema)
> - documents: per-event analysis incl. monetary_commitment, location, source_name,
>   source_geofocus, date, distilled_text, event_name.
> - bilateral_relationship_summaries: {INITIATOR}→recipient rollups (count_by_category,
>   count_by_subcategory, count_by_source, activity_by_month, material_score avg/median/
>   histogram, and an AI relationship_summary JSON).
> - country_category_summaries: {INITIATOR} per category, with count_by_recipient.
> - bilateral_category_summaries: {INITIATOR}→recipient per category.
> - event_summaries: canonical events (material_score, key_facts, entities_mentioned,
>   outcomes_summary) traceable to source documents.
> - canonical_entities / daily_entity_mentions / entity_relationships: the actor network —
>   people, organizations, SOEs, ministries; their roles, activity, and co-occurrence graph.
> - aiddata_projects (CHINA ONLY): verified development-finance commitments — for
>   project-level corroboration only when a named reported project directly matches a record.
>
> REPORT STRUCTURE (produce exactly these sections)
> 1. KEY JUDGMENTS — 5–8 confidence-tagged bullets, most decision-relevant first.
> 2. STRATEGIC POSTURE — {INITIATOR}'s theory of influence in MENA; dominant instruments
>    and objectives.
> 3. CATEGORICAL BREAKDOWN — for each of Economic, Social, Military, Diplomacy: share of
>    effort, leading subcategories, materiality, and 3–5 specific named events with dates,
>    dollar figures, and recipients.
> 4. RECIPIENT MATRIX — for each MENA recipient with material activity: intensity, lead
>    category, signature initiatives (named), trajectory, relationship-strength read. Call
>    out the top 3 and any notably under-engaged states.
> 5. ACTOR & NETWORK ANALYSIS — top entities by activity, their roles, and the relationship
>    structure (who coordinates with whom); note SOEs, ministries, cultural orgs, proxies.
> 6. TEMPORAL DYNAMICS — monthly trajectory, surges/declines, and event-driven inflection
>    points tied to real-world triggers where supportable.
> 7. INTELLIGENCE GAPS & COLLECTION PRIORITIES — what the data cannot answer, source-bias
>    exposure for this specific actor, and recommended collection.
> [CHINA ONLY, only if matches exist] When a reported economic project matches a specific
>    AidData GCDF 3.0 record (same project, location, agency), corroborate it inline within
>    the Economic categorical breakdown — citing the verified commitment value, loan terms,
>    or sector. Do NOT create a standalone financial section or compare aggregate dollar flows.
>
> RULES OF EVIDENCE
> - Every claim ties to specific data: name the event, entity, recipient, dollar amount,
>   date, or source. No unsupported generalities.
> - Quantify (counts, %, $, month-over-month deltas) before characterizing.
> - When reporting is thin or single-sourced, say so and lower confidence.
> - Separate "what {INITIATOR} did" from "what media reported {INITIATOR} did."
> - Be decision-relevant: what should a U.S. policymaker do or watch because of this?

---

## PART C — Data Dictionary Appendix (give this to the model alongside Part B)

### Taxonomy
- **Categories:** Economic, Social, Military, Diplomacy.
- **Subcategories:** Trade, Infrastructure, Food, Technology, Tourism, Industrial, Raw
  Materials, Finance, Energy (Economic); Culture/Cultural, Education, Healthcare, Housing,
  Media, Politics, Religious, Diaspora Engagement, Aid/Donation (Social); Bilateral/
  Multilateral Commitments, International Negotiations, Conflict Resolution, Global
  Governance Participation (Diplomacy); Sales, Joint Exercises, Training, Conferences
  (Military).

### Key tables & fields
- **documents** — `doc_id`, `date`, `source_name`, `source_geofocus`, `salience_bool`,
  `category`, `subcategory`, `initiating_country`, `recipient_country`, `monetary_commitment`,
  `location`, `lat_long`, `distilled_text`, `event_name`. M2M flatteners: `categories`,
  `subcategories`, `initiating_countries`, `recipient_countries`.
- **bilateral_relationship_summaries** — one row per (initiating_country, recipient_country):
  `total_documents`, `count_by_category/subcategory/source` (JSONB), `activity_by_month`
  (JSONB), `material_score_avg/median`, `material_score_histogram`, `relationship_summary`
  (JSONB: overview, key_themes, major_initiatives, trend_analysis, current_status,
  notable_developments, material_assessment).
- **country_category_summaries** — one row per (initiating_country, category):
  `count_by_recipient`, `count_by_subcategory`, material scores, `category_summary` JSONB
  (overview, key_strategies, top_recipients, major_initiatives, effectiveness_assessment).
- **bilateral_category_summaries** — (initiating, recipient, category) triplet, finest grain.
- **event_summaries** — canonical events: `period_type` (daily/weekly/monthly/yearly),
  `event_name`, `material_score`, `count_by_*` JSONB, `key_facts`, `entities_mentioned`,
  `outcomes_summary`, `overall_summary`, `doc_ids`.
- **canonical_entities** — `canonical_name`, `entity_type`, `primary_role`,
  `country_affiliations`, `total_documents`, `primary_categories`, `primary_recipients`,
  `entity_description`.
- **daily_entity_mentions** — entity activity per day (`activities_this_day`, `doc_ids`).
- **entity_relationships** — directed edges (`relationship_type`, `co_occurrence_count`,
  `relationship_description`) for network analysis.
- **aiddata_projects** (CHINA ONLY) — `recipient`, `recipient_iso3`, `commitment_year`,
  `flow_class` (ODA-like vs OOF-like), `flow_type_simplified`, `amount_nominal_usd`,
  `adjusted_amount_usd_2021`, `sector_name`, `infrastructure`, `interest_rate`, `maturity`,
  `collateralized`, `financial_distress`, `funding_agencies`, `status`.

### material_score
`event_summaries.material_score` is an LLM-assigned assessment on an **~1–10 scale**
(verified live range 2–9, mean 4.69; higher = more substantive/consequential) — NOT 0–1.
Scale any materiality chart 0–10, not 0–1. Use avg/median and the histogram to characterize
whether a relationship is dominated by high-substance events or low-substance noise. It is a
model judgment, not a measured outcome.

Do NOT confuse this with the `material_assessment.score` field *inside* the
`relationship_summary` / `category_summary` JSON of the summary tables — that one is a
separate 0.0–1.0 LLM score. Two different conventions: event-level = ~1–10, summary-JSON = 0–1.

### Scope filters to apply
- Initiating country = the report's {INITIATOR}.
- Recipient country ∈ the MENA recipient set above.
- Date ≥ 2024-08-01 for the media corpus.
- AidData (China only) is referenced ONLY when a named reported project directly matches a
  specific AidData record; it is otherwise out of scope (its 2000–2023 window does not
  overlap the media corpus).

---

## PART D — Agentic Investigation Playbook (techniques beyond the app)

The agent should treat these as its toolkit. Each is something the dashboard does NOT do,
and each is mapped to the investigation thread(s) it serves. The agent runs raw SQL / vector
search / graph traversal to execute them, forms findings, then verifies each finding against
the bias controls below before it enters the report.

### The bias control that changes everything — Source Provenance Normalization (all threads)
The corpus over-counts Iranian state media, so raw event volume lies. Turn that liability
into a *measured signal*:
- For every initiator→recipient relationship, compute the ratio of **self-reported** coverage
  (source_name / source_geofocus tied to the initiator's own outlets) vs. **third-party /
  recipient-country** coverage. A relationship dominated by the initiator's own media is a
  *narrative-projection* signal (propaganda); one carried by recipient or neutral outlets is
  a *genuine-traction* signal.
- Replace raw document counts with **distinct-canonical-event counts** and **source-diversity
  counts** (number of unique outlets) as the primary intensity metric. Report both raw and
  normalized; explain divergence.
- This single normalization is the difference between "Iran dominates MENA" (artifact) and
  "Iran dominates MENA *media narrative* while its third-party-corroborated footprint is X."

### Cross-actor Competitive Collision Detection (thread 2)
- Build the initiator × recipient × category × month tensor across ALL four actors (not the
  app's one-pair-at-a-time summaries). Flag cells where ≥2 actors are simultaneously active
  on the same recipient+category in the same window = contested terrain.
- Detect **substitution**: when actor A's activity toward a recipient decays and actor B's
  rises in the same category — a within-data influence handoff.
- Cluster recipients by their *vector of who-engages-them-on-what* to reveal blocs
  (e.g., resistance axis vs. Gulf) empirically rather than assuming them.

### Entity Network Graph Analytics (threads 3, 2)
- From entity_relationships, compute **degree/betweenness centrality** to find the actual
  hubs and, more importantly, the **brokers** — entities bridging otherwise separate clusters
  (likely intermediaries, fixers, dual-hatted officials).
- **Community detection** (Louvain/label-prop) to surface coordination cells the app's flat
  edge list hides.
- **Cross-recipient operators**: entities whose primary_recipients span multiple MENA states
  = transnational influence agents worth naming.
- **Entity bridges between two initiators' networks** = potential shared proxies or contested
  intermediaries.

### Temporal Changepoint & Co-movement Analysis (thread 4)
- Run changepoint/anomaly detection on each relationship's monthly series (not eyeballing the
  app's bar chart) to date surges precisely, then align them to real-world triggers (Gaza,
  Syria regime change Dec 2024, Red Sea/Houthi tempo).
- **Cross-actor co-movement**: test whether actors move *together* toward a recipient (e.g.,
  Russia + Iran toward Syria) — synchronized influence is a coordination signal.
- **Lead-lag sequencing**: within a relationship, does diplomacy precede economic, or military
  precede diplomacy? Mine event order to characterize each actor's playbook.

### Semantic Theme Discovery & Narrative Propagation (threads 1, 4)
- Cluster event/document embeddings to discover **latent themes** the 4-category taxonomy
  misses (e.g., "post-quake reconstruction diplomacy", "port-for-debt", "drone-tech transfer").
- Detect **narrative propagation**: near-duplicate influence framings the same actor pushes
  across multiple recipients = a coordinated campaign, not isolated events.
- **Novelty/outlier detection**: events semantically distant from a relationship's historical
  norm = early-warning candidates for thread 4.

### Materiality-weighted ranking (all threads)
- Rank relationships and events by aggregate/peak material_score, not volume, to separate
  substance from chatter. Use the histogram shape (top-heavy vs. flat) to characterize whether
  a relationship is built on a few big moves or constant low-grade activity.

### Verification gate (every finding must pass before it enters the report)
1. **Source-diversity check** — is it carried by >1 independent outlet, or a single-source
   artifact? Tag confidence accordingly.
2. **Self-report check** — is the initiator's own media the only source? If so, label it
   narrative-projection, not confirmed activity.
3. **Re-query confirmation** — re-pull the underlying events; confirm the named projects,
   entities, dates, and figures actually exist in the data and aren't model confabulation.
4. **Bias-artifact check** — could the Iran over-indexing (or any single dominant source)
   explain this finding by itself? If yes, reframe or drop.

---

## PART E — Harness Architecture (how to run it)

Per initiator (China, Iran, Russia, Turkey), the agent runs this loop:

1. **Index & baseline** — pull scope (counts, recipients, categories, date span) AND
   immediately compute Source Provenance Normalization. Establish the normalized intensity
   metric used for the rest of the run.
2. **Fan out the four threads** — each thread is an independent sub-investigation with raw
   data access, running the relevant Part-D techniques and emitting candidate findings with
   the evidence (event IDs, entity IDs, queries used).
3. **Verify** — every candidate finding passes the four-point verification gate; survivors
   carry a confidence tag and a provenance note.
4. **Synthesize** — assemble the 7-section report (Part A) from verified findings, leading
   with Key Judgments.
5. **Completeness critic** — a final pass asks "what did we not investigate, which thread is
   thin, which claim is unverified?" and spawns follow-up queries before finalizing.

### Tools the agent needs
- `run_sql(query)` — SQL over the Postgres DB. **Read-only on `public`** (documents +
  normalized M2M tables, summary tables, entity tables, aiddata_projects). **Read/write on
  the `analytics` schema** for derived artifacts (see Part J) — never mutate `public`.
- `vector_search(text, k, scope)` — pgvector similarity over documents / event summaries /
  canonical entities (langchain_pg_embedding + the ARRAY(Float) embedding columns).
- `entity_graph(seed, depth)` — traverse entity_relationships for network analytics.
- `python(code)` — for stats the DB doesn't do cheaply: centrality, community detection,
  changepoint, clustering.

### Execution options
- **Single-agent loop** — one Opus agent with the tools above, iterating per initiator.
  Simplest; good first cut.
- **Multi-agent workflow** — fan the four threads out as parallel sub-agents, an adversarial
  verifier pass, then a synthesizer. Most thorough; higher token cost. (Requires explicit
  opt-in to run.)

---

## PART F — Verified Ground Truth & /goal Execution Brief

*Probed against the live DB (corpus spans 2024-07-03 → 2026-06-15, ~23 months). Use these
numbers to sanity-check the autonomous run; if a query returns wildly different magnitudes,
something is mis-scoped.*

### Verified inventory
- documents: **738,530**; source_name 100% populated (590 distinct), source_geofocus ~92%.
- Docs by initiator (normalized table): **Iran 258,707 · China 65,036 · Turkey 53,932 ·
  Russia 43,814** — Iran is ~3.4× the next actor. The top 8 sources are ALL Iranian state
  media (IRIB, Fars, Mehr, IRNA, Tasnim, ISNA…). This is the bias, quantified.
- canonical_entities **13,534** (Iran 4,693 · China 2,806 · Turkey 2,687 · Russia 1,624);
  entity_relationships **8,320**; daily_entity_mentions **33,524**.
- Summary tables: bilateral_relationship_summaries 91 · country_category_summaries 20 ·
  bilateral_category_summaries 308 · event_summaries 13,559 · aiddata_projects 20,985.

### MANDATORY scope filters (non-negotiable — the run is wrong without them)
1. `initiating_country IN ('China','Iran','Russia','Turkey')`.
2. `recipient_country IN` the MENA set (Bahrain, Cyprus, Egypt, Iraq, Israel, Jordan, Kuwait,
   Lebanon, Libya, Oman, Palestine, Qatar, Saudi Arabia, Syria, UAE/United Arab Emirates,
   Yemen; plus Iran/Turkey only when they are the recipient). The raw data also contains
   non-MENA recipients (United States, Pakistan, etc.) — **exclude them**.
3. `initiating_country != recipient_country`. The corpus contains **79,864 Iran→Iran**
   self-referential rows (extraction noise); these MUST be dropped or they dominate Iran's
   profile.
4. `date >= '2024-08-01'` per config start.

### Source-Provenance Normalization — concrete method (uses source_geofocus)
`source_geofocus` is an array of country foci (e.g. `{Iran}`, `{"Saudi Arabia"}`). Verified
distribution: `{Iran}` 325,654 vs. recipient-focused outlets (Saudi 50,954, Egypt 47,376,
Jordan 43,760, UAE 27,585, Qatar 25,992…). For each INIT→RECIP relationship classify every
document:
- **Self-reported** if `source_geofocus` contains INIT (initiator's own media ecosystem).
- **Recipient/third-party** if it contains RECIP or any non-INIT focus.
Report `self_reported_share = self / (self + third_party)`. High share = narrative projection;
low share = independently corroborated traction. Use third-party-corroborated and
distinct-canonical-event counts as the PRIMARY intensity metric; show raw counts alongside.

### How the autonomous agent should work (it has Bash + Python + the repo)
- Connect via the repo's own pattern — no new infra needed:
  ```python
  from shared.database.database import get_session
  from sqlalchemy import text
  with get_session() as s:
      rows = s.execute(text("SELECT ... ")).fetchall()
  ```
- Use raw SQL for tensors/pivots/joins; drop to pandas/networkx/numpy in the same script for
  centrality, community detection, changepoint, and embedding clustering.
- Embeddings: document/chunk semantic search via `langchain_pg_embedding` (collection
  `chunk_embeddings`, 721,368 rows, ~97.7% of docs). Entity semantic search via
  `canonical_entities.embedding_vector` — 100% populated at 768-dim (re-embedded 2026-06-29
  with nomic `search_document:` prefix). Both vector paths are available; combine with
  pg_trgm fuzzy name match and the `entity_relationships` graph as needed.
- Work one initiator at a time; persist intermediate findings (JSON) to the scratchpad so a
  long /goal run can resume. Apply the Part-D verification gate before any finding is written.

### Verified starter query (correctly scoped top pairs — copy/adapt)
```sql
SELECT ic.initiating_country, rc.recipient_country, COUNT(DISTINCT d.doc_id) AS docs
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
JOIN recipient_countries  rc ON d.doc_id = rc.doc_id
WHERE ic.initiating_country IN ('China','Iran','Russia','Turkey')
  AND rc.recipient_country IN ('Bahrain','Cyprus','Egypt','Iraq','Israel','Jordan','Kuwait',
      'Lebanon','Libya','Oman','Palestine','Qatar','Saudi Arabia','Syria',
      'United Arab Emirates','UAE','Yemen','Iran','Turkey')
  AND ic.initiating_country <> rc.recipient_country
  AND d.date >= '2024-08-01'
GROUP BY 1,2 ORDER BY 3 DESC;
```

---

## PART G — Visualization Specification

**Principle:** every finding that cites a metric gets a supporting visual unless the number
is a single trivial figure stated in one line. Visuals show the **normalized / third-party-
corroborated** metric (or raw + normalized side by side) — NEVER raw, Iran-inflated counts
alone, which would reintroduce the bias the analysis controls for.

### Global style (apply to every chart)
- **Fixed actor palette** across all charts: China `#C8102E`, Iran `#1B7A3D`,
  Russia `#1F4E9C`, Turkey `#E08A1E`.
- **Title states the finding** ("Iran's MENA footprint is 78% self-reported"), not the axis.
  Subtitle = metric definition + n + date range + data basis ("media-reporting volume,
  third-party-corroborated").
- Consistent recipient ordering across charts; label n and the metric on every figure.
- No chart junk. Intel products prize signal density over decoration.

### Core visual set (~8 per report — do not exceed ~10)
1. **Influence-signature radar** — 4-category share, this actor vs. all-actor average. *(Thread 1)*
2. **Subcategory Pareto** — top-10 subcategories, horizontal bar. *(Thread 1)*
3. **Recipient concentration** — Lorenz curve + HHI (Herfindahl) value. *(Thread 1)*
4. **MENA intensity choropleth** — recipients shaded by normalized intensity. *(Threads 1/2)*
5. **Provenance quadrant scatter** — x = raw volume, y = third-party-corroborated share;
   quadrants labeled narrative-projection vs. genuine-traction. THE bias visual. *(cross-cutting)*
6. **Competitive heatmap** — recipient × all-4-actors normalized intensity matrix. *(Thread 2)*
7. **Entity network graph** — top ~40 entities by centrality; node size = centrality,
   color = community, brokers highlighted. *(Thread 3)*
8. **Activity timeline** — monthly series with marked changepoints + real-world trigger
   annotations (Gaza, Syria regime change Dec 2024, Red Sea/Houthi tempo). *(Thread 4)*

Conditional (only when the finding warrants): substitution dual-line (handoff detected),
materiality histogram/box plot, cross-actor co-movement correlation heatmap.

Each figure carries a 1–2 sentence caption: the finding, its confidence tag, and data basis.

### Implementation (for the autonomous /goal run)
- Generate charts with matplotlib/plotly in the SAME Python that queries the DB. Save PNG
  (≥150 dpi) to `docs/reports/<initiator>/assets/` and embed via markdown
  `![caption](assets/<name>.png)`.
- **Determinism:** sort everything; seed any layout (network spring layout `seed=`); no
  unseeded randomness — a /goal re-run should reproduce the same figure.
- **Traceability:** persist each chart's underlying numbers as a sibling `.csv`/`.json` so the
  Part-D verification gate (and a human reviewer) can audit the figure against the data.
- **Network graph:** filter to top ~40 nodes by centrality per actor for readability;
  networkx + seeded layout (or pyvis if an interactive artifact is wanted).
- **Choropleth:** map recipient names → ISO3, render with plotly or a geopandas Natural-Earth
  MENA subset.
- Compute the metric once in SQL/pandas; the chart and the prose cite the same numbers.

### Output format
- **Default:** Markdown report with embedded PNGs — portable, diff-able, version-controllable.
- A Word/docx deliverable is available via `server/report_exporter.py` if a briefing-format
  document is required; point it at the same assets.

---

## PART H — Using the Pre-Built Summaries (scaffold, not evidence)

The summary tables accelerate the run but inherit the raw-volume bias. Use them for
narratives and named events; recompute all magnitude/ranking metrics from raw.

### What to use, and how
- **event_summaries (13,559) — PRIMARY.** Fresh (2024-08→2026-06-15, updated 2026-06-28),
  `material_score` 100%, `narrative_summary` 100%. This is the **citation spine**: the named,
  materiality-scored events the report cites. Rank by material_score + recency per
  relationship. ⚠️ `entities_mentioned` and `outcomes_summary` are EMPTY here — get entity
  links from `canonical_entities` / `daily_entity_mentions` instead.
- **bilateral_relationship_summaries (18 recipients × 4 actors) — SCAFFOLD + CROSS-CHECK.**
  Through ~May–Jun 2026. One AI narrative per pair plus category/source breakdowns,
  `activity_by_month`, and material histograms. Use the narrative as a hypothesis source and
  as a contradiction check: if it disagrees with the agent's raw-query finding, investigate
  (extraction drift or a real change) — don't just defer to it.
- **bilateral_category_summaries (~60/actor)** — thematic background at finest grain.
- **country_category_summaries (4/actor) — STALE** (last_interaction_date 2025-10-14, ~8
  months behind). Background only; re-derive current category numbers from raw.

### Hard rule
Every summary's counts and rankings are computed on RAW document volume — Iran-inflated and
provenance-blind. **Never quote a summary's volume/intensity/material ranking as a finding.**
Use summaries for their prose and their named events; recompute every magnitude, ranking, and
materiality metric from raw using the Source-Provenance-Normalized method (Part D). Summaries
are the index and the draft; the raw data is the evidence.

---

## PART I — Live Schema Scan (verified 2026-06-29)

39 tables. The analytically relevant ones, with what the scan revealed:

### Volumes (raw vs. clean)
- `documents` 738,530 · `event_summaries` 13,559 · `canonical_events` 17,933 (all masters —
  no consolidation hierarchy populated) · `canonical_entities` 13,534 · `entity_relationships`
  8,320 · `daily_entity_mentions` 33,524 · `daily_event_mentions` 22,317 ·
  `event_source_links` 136,326 (every event linked → full event→document traceability).
- Raw flatteners are huge: `raw_events` 1.41M, `recipient_countries` 1.21M, `raw_entities`
  970K, `initiating_countries` 885K, `categories` 948K, `subcategories` 960K.
- `aiddata_projects` 20,985 + `aiddata_locations` 26,686.
- Empty/near-empty (ignore): `canonical_propositions`, `document_propositions`,
  `period_summaries`, `ingestion_jobs`, `alert_*`, `agent_*` (app's own agent logs).

### CLEAN category splits — use the M2M tables, not the string column
`documents.category` is semicolon-joined ("Social;Diplomacy", "Economic;Diplomacy") — do NOT
GROUP BY it. Join the M2M `categories` / `subcategories` / `initiating_countries` /
`recipient_countries` tables for clean per-pillar counts. Verified example (Iran, clean):
Social 148,309 · Diplomacy 135,561 · Economic 38,970 · Military 4,791 — note Social edges out
Diplomacy here, which the raw string column obscures.

### Document field population (verified)
`location` 97.7% · `lat_long` 97.7% · `event_name` 96.7% → **geographic point/sub-national
mapping is viable** (not spotty). `monetary_commitment` only 24.8% and messy free-text
("Billions of dollars", "178 million euros; 28.7 hemts") → unusable for aggregation; anecdotal
named-deal use only.

### Event summary content (cite-ready)
`event_summaries.narrative_summary` JSON keys = `overview`, `outcomes`, `progression`.
`material_score` ~1–10 (see Part C). `entities_mentioned` / `outcomes_summary` are EMPTY —
get entities from `canonical_entities` / `daily_entity_mentions`. Highest-material example
found: "St. Petersburg International Economic Forum" (Russia, score 9).

### Entity & network vocabulary (for thread 3)
- `entity_type`: PERSON 5,892 · ORGANIZATION 4,585 · LOCATION 2,431 · COMPANY 626.
- `primary_role` (top): GOVERNMENT_OFFICIAL, INFRASTRUCTURE_PROJECT, IMPLEMENTING_ORGANIZATION,
  ACADEMIC, DIPLOMAT, VENUE, CIVIL_SOCIETY, MILITARY_OFFICIAL, BUSINESS_LEADER.
- `entity_relationships.relationship_type`: co_occurrence 4,756 · works_with 1,042 · visited
  929 · partnered_with 759 · represents 311 · leads 210 · signed_agreement_with 172 ·
  employed_by 123 · located_in 18. Edges carry `relationship_description` + `co_occurrence_count`.
- Example top Iran entities by doc volume: Abbas Araghchi (3,545), Masoud Pezeshkian (1,093),
  Iranian Red Crescent Society (720), Hassan Nasrallah (629).

### AidData overlap with media window ≈ nil (reaffirms the narrow stance)
China MENA commitments are 2000–2023 (latest commitment_year 2021): Egypt 119 proj/$32.1B,
Iran 113/$95.3B, Jordan 100/$4.7B, Iraq 52/$24.0B, etc.; flow_class ODA-like 396 / OOF-like
207. Only ~2 projects in major recipients complete in 2023+, so direct overlap with 2024+
reporting is essentially nonexistent — corroborate only on an exact named-project match.

### Query gotchas (Postgres)
- `round(double precision, int)` ERRORS — cast floats: `round(x::numeric, 1)`. Affects
  `amount_nominal_usd`, `material_score` math, any avg/ratio over float columns.
- `source_geofocus` is a text rendering of an array (`{Iran}`, `{"Saudi Arabia"}`) — match
  with `LIKE '%Iran%'` or strip braces; it's the key to provenance normalization.
- Embeddings: `canonical_entities.embedding_vector` 768-dim 100% (restored); document vectors
  in `langchain_pg_embedding` (collection `chunk_embeddings`, 721K, one per doc).

---

## PART J — Derived Artifacts: License to Transform (and Document)

The schema in `public` is the app's, not a constraint on the analysis. The agent is
**explicitly authorized** to create any transformation, aggregation, index, or materialization
it judges useful — and is expected to look for such opportunities, not just consume what
exists. The only rules are isolation and documentation.

### Rules
1. **Write only in the `analytics` schema** (already created). NEVER `ALTER`/`DROP`/`UPDATE`/
   `DELETE` anything in `public` — app tables are read-only inputs. Derived objects go in
   `analytics.*` with clear, prefixed names (e.g. `analytics.provenance_intensity`).
2. **Prefer materialized views or tables** for anything reused across threads or actors;
   CTEs/temp tables are fine for one-off steps.
3. **Document every persisted artifact** in a manifest at
   `docs/reports/_derived/manifest.md`, one entry each: name · grain · purpose · thread(s)
   served · full migration-ready `CREATE` DDL · refresh logic · and a **persistence
   recommendation** (ephemeral / keep as matview / promote into `public` via an Alembic
   migration). Save the DDL as a sibling `.sql` so it can be lifted into `alembic/versions/`
   later. The goal: a clean hand-off list of "derived structures worth making permanent."
4. **Verify before trusting** — a derived aggregate still passes the Part-D verification gate
   (source-diversity, self-report, bias-artifact) before any finding built on it ships.

### Pre-identified high-value opportunities (starting menu — extend freely)
These are gaps the app's schema leaves on the table, ordered by analytic payoff:

1. **`analytics.provenance_intensity`** — grain (initiator, recipient, category, month).
   Columns: raw_docs, distinct_events, self_reported_docs, third_party_docs,
   self_report_share, distinct_sources, normalized_intensity. The backbone metric for every
   thread; replaces raw, bias-blind counts. **Highest priority.**
2. **`analytics.actor_recipient_category_month`** — the full cross-actor tensor (all 4
   initiators in one long table) enabling competitive-collision, substitution, and
   co-movement analysis the per-pair summary tables can't express. *(Thread 2)*
3. **`analytics.entity_graph_metrics`** — per canonical_entity: degree, betweenness, community
   id, cross-recipient reach. Precomputes the network analytics so brokers/hubs/communities
   are queryable, not recomputed each time. *(Thread 3)*
4. **`analytics.event_entities`** — fills a real gap: `event_summaries.entities_mentioned` is
   EMPTY; reconstruct event→entity links from `daily_entity_mentions.associated_event_ids` so
   named events carry their actors. *(Threads 3, citations)*
5. **`analytics.source_provenance_map`** — curated classification of all ~590 `source_name`/
   `source_geofocus` values into {initiator-aligned, recipient-aligned, third-party/neutral}.
   Makes provenance normalization exact and reusable instead of inferred per query.
6. **`analytics.recipient_blocs`** — empirical clustering of recipients by their
   who-engages-them-on-what profile; persists bloc labels for thread-2 narrative. *(Thread 2)*
7. **`analytics.relationship_changepoints`** — detected monthly inflection dates per
   relationship, with magnitude, for thread-4 surge/trigger alignment. *(Thread 4)*
8. **`analytics.narrative_themes`** — semantic clusters over event/distilled_text embeddings to
   surface latent campaigns and cross-recipient narrative propagation. *(Threads 1, 4)*
9. **`analytics.geo_intensity`** — recipient-level and sub-national (lat_long-clustered)
   intensity for choropleth/point maps (location/lat_long are 97.7% populated). *(viz)*
10. **`analytics.monetary_parsed`** — best-effort parse of the 24.8% populated, messy
    `monetary_commitment` free-text into numeric USD where unambiguous; flag the rest. Low
    yield, anecdotal use only — but worth capturing the parseable subset.

Anything the agent builds that proves load-bearing should be flagged in the manifest as a
**promotion candidate** — a derived structure the app itself would benefit from persisting.
