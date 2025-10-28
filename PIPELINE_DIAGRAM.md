# Soft Power Event Processing Pipeline - Visual Architecture

## High-Level Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SOFT POWER EVENT PIPELINE                           │
│                        September 2024 Implementation                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT: PostgreSQL Database                                                  │
│  ┌──────────────────┐         ┌──────────────────┐                          │
│  │   Documents      │         │   RawEvents      │                          │
│  │  (~18K articles) │────────▶│  (extracted via  │                          │
│  │                  │         │   GPT-4 analysis)│                          │
│  └──────────────────┘         └──────────────────┘                          │
│                                                                               │
│  Metadata: pub_date, initiating_country, recipient_countries, categories    │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: DAILY CLUSTERING                                                    │
│  Script: batch_cluster_events.py                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  For Each (Country, Date):                                          │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  1. Query all RawEvents for that country + date             │  │    │
│  │  │     Example: China, 2024-09-01 → ~60-70 events              │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  2. Filter out self-directed events (country→same country)   │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  3. Normalize event names:                                   │  │    │
│  │  │     - Lowercase text                                         │  │    │
│  │  │     - Remove punctuation, generic terms                      │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  4. Generate embeddings:                                     │  │    │
│  │  │     - Model: sentence-transformers/all-MiniLM-L6-v2         │  │    │
│  │  │     - 384-dimensional vectors                                │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  5. DBSCAN Clustering:                                       │  │    │
│  │  │     - eps=0.15 (cosine distance)                            │  │    │
│  │  │     - min_samples=2                                          │  │    │
│  │  │     - Clusters ALL events together in one pass              │  │    │
│  │  │     - Result: ~50-60 clusters per day                       │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  6. Organize into batches:                                   │  │    │
│  │  │     - batch_size = 150 events per LLM batch                 │  │    │
│  │  │     - Usually 1 batch per day (unless >150 clusters)        │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  7. Calculate cluster metadata:                              │  │    │
│  │  │     - Centroid embedding (mean of all vectors)              │  │    │
│  │  │     - Representative name (closest to centroid)             │  │    │
│  │  │     - Cluster size, doc_ids, event_names array              │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  OUTPUT TABLE: event_clusters                                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ initiating_country  │ cluster_date │ batch_number │ cluster_id       │  │
│  │ China               │ 2024-09-01   │ 0            │ 0                │  │
│  │ China               │ 2024-09-01   │ 0            │ 1                │  │
│  │ China               │ 2024-09-01   │ 0            │ 2                │  │
│  │ ...                 │ ...          │ ...          │ ...              │  │
│  │                                                                       │  │
│  │ Fields: event_names[], doc_ids[], centroid_embedding,                │  │
│  │         representative_name, is_noise, processed, llm_deconflicted   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  September 2024 Results: 10,288 clusters (China: 2,109, Iran: 3,545, etc.)  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: LLM DECONFLICTION + CANONICAL EVENT CREATION                        │
│  Script: llm_deconflict_clusters.py                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  For Each Batch (Country, Date, BatchNumber):                       │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  1. Load clusters where llm_deconflicted = False            │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  2. For each cluster, check if LLM review needed:            │  │    │
│  │  │     - Skip if only 1 unique event name                       │  │    │
│  │  │     - Send to LLM if 2+ unique names                         │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  3. LLM Analysis (GPT-4o-mini):                              │  │    │
│  │  │     ┌────────────────────────────────────────────────────┐  │  │    │
│  │  │     │ CHAIN-OF-THOUGHT PROMPT (temporal tracking):      │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ STEP 1 - Identify Core Events:                    │  │  │    │
│  │  │     │   Extract: main activity, actors, context         │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ STEP 2 - Match Across Lifecycle Stages:           │  │  │    │
│  │  │     │   "China announces BRI Forum"                     │  │  │    │
│  │  │     │   "China preparing for BRI Forum"                 │  │  │    │
│  │  │     │   "BRI Forum begins in Beijing"        ──┐        │  │  │    │
│  │  │     │   "BRI Forum concludes with agreements"   │        │  │  │    │
│  │  │     │   └─ ALL SAME EVENT (temporal evolution) ─┘        │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ STEP 3 - Distinguish Different Events:            │  │  │    │
│  │  │     │   "First China-Egypt summit"                      │  │  │    │
│  │  │     │   "Second China-Egypt summit"    ── DIFFERENT     │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ STEP 4 - Validation:                              │  │  │    │
│  │  │     │   Would these fit the same event timeline?        │  │  │    │
│  │  │     └────────────────────────────────────────────────────┘  │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  4. LLM Response (JSON):                                 │  │    │
│  │  │     {                                                    │  │    │
│  │  │       "groups": [                                        │  │    │
│  │  │         {                                                │  │    │
│  │  │           "canonical_name": "Belt and Road Forum 2024", │  │    │
│  │  │           "event_names": ["announces forum", ...],      │  │    │
│  │  │           "reasoning": "Same event across stages",      │  │    │
│  │  │           "lifecycle_stage": "execution"                │  │    │
│  │  │         }                                                │  │    │
│  │  │       ]                                                  │  │    │
│  │  │     }                                                    │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  5. Create CanonicalEvent records:                       │  │    │
│  │  │     - One per unique real-world event                    │  │    │
│  │  │     - Generate embedding for canonical_name              │  │    │
│  │  │     - Store alternative_names[]                          │  │    │
│  │  │     - Calculate metadata (dates, counts, sources)        │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  6. Create DailyEventMention records:                    │  │    │
│  │  │     - Links canonical_event to specific date             │  │    │
│  │  │     - Stores doc_ids, article_count                      │  │    │
│  │  │     - Tracks mention_context (announcement/execution/etc)│  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  7. Mark cluster as llm_deconflicted = True              │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  OUTPUT TABLES:                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ canonical_events (deduplicated events)                                │  │
│  │ ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │ │ id (UUID) │ canonical_name │ initiating_country │ master_event_id││ │  │
│  │ │ abc-123   │ BRI Forum 2024 │ China              │ NULL          ││ │  │
│  │ │                                                                  ││ │  │
│  │ │ Fields: first_mention_date, last_mention_date, total_articles,  ││ │  │
│  │ │         story_phase, alternative_names[], primary_categories,   ││ │  │
│  │ │         primary_recipients, embedding_vector                    ││ │  │
│  │ └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  │ daily_event_mentions (event occurrences by date)                     │  │
│  │ ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │ │ canonical_event_id │ mention_date │ doc_ids[]    │ article_count││ │  │
│  │ │ abc-123            │ 2024-09-01   │ [d1,d2,d3]  │ 15           ││ │  │
│  │ │ abc-123            │ 2024-09-02   │ [d4,d5]     │ 11           ││ │  │
│  │ │                                                                  ││ │  │
│  │ │ Fields: consolidated_headline, mention_context, news_intensity, ││ │  │
│  │ │         source_names[], source_diversity_score                  ││ │  │
│  │ └──────────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  Note: master_event_id = NULL means this IS a master event                   │
│        master_event_id = <UUID> means this is a child of that master         │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: TEMPORAL CONSOLIDATION (Master Events)                              │
│  Status: PENDING IMPLEMENTATION                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Goal: Cluster canonical events across time to create master events │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  1. Load canonical_events from Step 2                        │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  2. For each canonical event, search temporal window:        │  │    │
│  │  │     - Look back/forward N days (e.g., ±14 days)             │  │    │
│  │  │     - Find similar events using semantic similarity          │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  3. Similarity scoring:                                       │  │    │
│  │  │     - Semantic: cosine(embedding1, embedding2)               │  │    │
│  │  │     - Temporal: decay function (closer dates = higher)       │  │    │
│  │  │     - Source overlap: shared news sources                    │  │    │
│  │  │     - Entity consistency: same recipients/categories         │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  4. Decision logic:                                          │  │    │
│  │  │     IF similarity > threshold:                               │  │    │
│  │  │       → Link to existing master event (set master_event_id) │  │    │
│  │  │     ELSE:                                                    │  │    │
│  │  │       → Create new master event (master_event_id = NULL)    │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  5. Track story phases:                                      │  │    │
│  │  │     - emerging → developing → peak → fading → dormant       │  │    │
│  │  │     - Update story_phase field                               │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  OUTPUT: canonical_events table updated with master_event_id links           │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Master Event Hierarchy:                                               │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────┐    │  │
│  │  │ Master: "Belt and Road Forum 2024"                          │    │  │
│  │  │ (master_event_id = NULL)                                    │    │  │
│  │  │  ├─ Child: "Forum announced for September" (2024-08-15)     │    │  │
│  │  │  ├─ Child: "Preparations for forum underway" (2024-08-28)   │    │  │
│  │  │  ├─ Child: "Forum begins in Beijing" (2024-09-01)           │    │  │
│  │  │  ├─ Child: "Forum continues with agreements" (2024-09-02)   │    │  │
│  │  │  └─ Child: "Forum concludes with 50 deals" (2024-09-03)     │    │  │
│  │  └─────────────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: DAILY SUMMARY GENERATION                                            │
│  Script: generate_daily_summaries.py                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  For Each (Country, Date):                                          │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  1. Query master events active on this date:                 │  │    │
│  │  │     - WHERE master_event_id IS NULL                          │  │    │
│  │  │     - AND has daily_event_mention on this date               │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  2. Rank by article count, select top N (default: 10)        │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  3. For each master event:                                   │  │    │
│  │  │     - Sample 5 representative documents                      │  │    │
│  │  │     - Include high salience + diverse sources                │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  4. LLM Summary Generation (GPT-4o-mini):                    │  │    │
│  │  │     ┌────────────────────────────────────────────────────┐  │  │    │
│  │  │     │ Prompt: "Generate AP-style summary"               │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ Input:                                             │  │  │    │
│  │  │     │   - Event name                                     │  │  │    │
│  │  │     │   - 5 sampled document excerpts                   │  │  │    │
│  │  │     │   - Metadata (dates, categories, recipients)      │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ Output (JSON):                                     │  │  │    │
│  │  │     │ {                                                  │  │  │    │
│  │  │     │   "overview": "2-3 sentences about what happened",│  │  │    │
│  │  │     │   "outcomes": "2-3 sentences about results"       │  │  │    │
│  │  │     │ }                                                  │  │  │    │
│  │  │     │                                                    │  │  │    │
│  │  │     │ Style: Associated Press                           │  │  │    │
│  │  │     │   - Factual, attributed, no analysis              │  │  │    │
│  │  │     │   - Who, what, when, where format                 │  │  │    │
│  │  │     └────────────────────────────────────────────────────┘  │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  5. Generate ATOM hyperlinks:                            │  │    │
│  │  │     - Create links to all source documents               │  │    │
│  │  │     - Format: atom://doc/<doc_id>                        │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  6. Generate citations:                                  │  │    │
│  │  │     - First 10 documents                                 │  │    │
│  │  │     - Format: "Source Name (Date): Headline"             │  │    │
│  │  ├──────────────────────────────────────────────────────────────┤  │    │
│  │  │  7. Save to event_summaries table                        │  │    │
│  │  │  8. Save source links to event_source_links table        │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  OUTPUT TABLES:                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ event_summaries                                                       │  │
│  │ ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │ │ period_type │ period_start │ event_name      │ narrative_summary││ │  │
│  │ │ DAILY       │ 2024-09-01   │ BRI Forum 2024  │ {overview: ...} ││ │  │
│  │ │                                                                  ││ │  │
│  │ │ narrative_summary (JSONB):                                       ││ │  │
│  │ │   {                                                              ││ │  │
│  │ │     "overview": "China hosted the Belt and Road Forum...",      ││ │  │
│  │ │     "outcomes": "The forum concluded with 50 agreements...",    ││ │  │
│  │ │     "source_link": "atom://event-sources/abc-123",              ││ │  │
│  │ │     "citations": ["Source 1 (2024-09-01): Headline", ...]       ││ │  │
│  │ │   }                                                              ││ │  │
│  │ └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                       │  │
│  │ event_source_links (traceability)                                    │  │
│  │ ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │ │ event_summary_id │ doc_id │ contribution_weight                 ││ │  │
│  │ │ summary-xyz      │ d1     │ 1.0 (featured source)               ││ │  │
│  │ │ summary-xyz      │ d2     │ 0.5 (supporting source)             ││ │  │
│  │ └──────────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  FINAL OUTPUT: Dashboard Visualization                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Streamlit Dashboard (services/dashboard/app.py)                    │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  • Daily Summary View                                        │  │    │
│  │  │    - Top 10 events per country per day                       │  │    │
│  │  │    - AP-style narrative summaries                            │  │    │
│  │  │    - Clickable ATOM links to source documents                │  │    │
│  │  │    - Citations for full transparency                         │  │    │
│  │  │                                                               │  │    │
│  │  │  • Event Timeline View                                       │  │    │
│  │  │    - Track event evolution over time                         │  │    │
│  │  │    - See lifecycle stages (announcement → execution → etc.)  │  │    │
│  │  │    - Article count trends                                    │  │    │
│  │  │                                                               │  │    │
│  │  │  • Analytics                                                 │  │    │
│  │  │    - Category breakdown                                      │  │    │
│  │  │    - Recipient country analysis                              │  │    │
│  │  │    - Source diversity metrics                                │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Two-Stage Clustering Architecture (Detail)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHY TWO STAGES?                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Problem: News articles about events arrive continuously over time           │
│                                                                               │
│  Example Timeline:                                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Aug 15: "China announces Belt and Road Forum for September"          │  │
│  │ Aug 28: "China preparing for major diplomatic forum"                 │  │
│  │ Sep 01: "Belt and Road Forum begins in Beijing"                      │  │
│  │ Sep 02: "Forum continues with trade agreements"                      │  │
│  │ Sep 03: "China's forum concludes with 50 deals"                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  Challenge: These are all THE SAME EVENT but:                                │
│    • Different dates (can't cluster all together initially)                  │
│    • Different wording (announcement vs execution)                           │
│    • Different details (preparation vs outcomes)                             │
│                                                                               │
│  Solution: Two-stage approach                                                │
│    Stage 1: Cluster within each day (fast, handles same-day duplicates)     │
│    Stage 2: Link across days (temporal tracking, event evolution)           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: DAILY CONSOLIDATION (Same-Day Clustering)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Input: All articles published on 2024-09-01 about China                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Source 1: "China's Belt and Road Forum opens in Beijing"             │  │
│  │ Source 2: "Xi Jinping hosts Belt and Road Initiative summit"         │  │
│  │ Source 3: "Beijing welcomes delegates to BRI Forum"                  │  │
│  │ Source 4: "China launches new trade initiative"         ← Different  │  │
│  │ Source 5: "Belt and Road Forum begins with 100 countries"            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  DBSCAN Clustering (eps=0.15):                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Cluster 0: [Source 1, Source 2, Source 3, Source 5]                  │  │
│  │   → Same event (Belt and Road Forum opening)                         │  │
│  │                                                                       │  │
│  │ Cluster 1: [Source 4]                                                │  │
│  │   → Different event (trade initiative)                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  Purpose: Eliminate same-day duplicates from different news sources          │
│  Result: Clean daily event clusters                                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: TEMPORAL LINKING (Cross-Day Clustering)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Input: Canonical events from multiple days                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Aug 15: "China announces Belt and Road Forum for September"          │  │
│  │ Sep 01: "Belt and Road Forum begins in Beijing"                      │  │
│  │ Sep 02: "Forum continues with trade agreements"                      │  │
│  │ Sep 03: "Belt and Road Forum concludes with 50 deals"                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  Temporal Matching (with LLM chain-of-thought):                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Analysis:                                                             │  │
│  │   • Same core event: "Belt and Road Forum"                           │  │
│  │   • Same actors: China                                               │  │
│  │   • Same context: September 2024 forum                               │  │
│  │   • Different stages: announcement → execution → aftermath           │  │
│  │                                                                       │  │
│  │ Decision: LINK ALL TO MASTER EVENT                                   │  │
│  │                                                                       │  │
│  │ Master Event: "Belt and Road Forum 2024"                             │  │
│  │   ├─ Child 1 (Aug 15): Announcement stage                            │  │
│  │   ├─ Child 2 (Sep 01): Execution stage                               │  │
│  │   ├─ Child 3 (Sep 02): Continuation stage                            │  │
│  │   └─ Child 4 (Sep 03): Aftermath stage                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  Purpose: Track event evolution and lifecycle                                │
│  Result: Master events with temporal children                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Technology Stack

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CORE TECHNOLOGIES                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Database:                                                                    │
│    • PostgreSQL 13+ with pgvector extension                                  │
│    • SQLAlchemy 2.0 ORM                                                      │
│    • Connection pooling (10 base + 20 overflow)                              │
│                                                                               │
│  AI/ML:                                                                       │
│    • OpenAI GPT-4o-mini (event deconfliction, summarization)                 │
│    • sentence-transformers/all-MiniLM-L6-v2 (embeddings)                     │
│    • scikit-learn DBSCAN (clustering algorithm)                              │
│                                                                               │
│  Data Processing:                                                             │
│    • NumPy, pandas (data manipulation)                                       │
│    • Python 3.12                                                             │
│    • Docker containers (api-service, dashboard, db)                          │
│                                                                               │
│  Visualization:                                                               │
│    • Streamlit (interactive dashboard)                                       │
│    • Altair (charts)                                                         │
│    • Custom ATOM protocol (document linking)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Performance Metrics (September 2024)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT DATA                                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Total documents: 18,347 articles                                          │
│  • Date range: September 1-30, 2024 (30 days)                               │
│  • Countries: 5 (China, Russia, Iran, Turkey, United States)                │
│  • Breakdown:                                                                │
│    - Iran: 7,024 articles                                                   │
│    - China: 3,736 articles                                                  │
│    - United States: 2,989 articles                                          │
│    - Turkey: 2,714 articles                                                 │
│    - Russia: 1,884 articles                                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: DAILY CLUSTERING RESULTS                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Total clusters created: 10,288                                            │
│  • Processing time: ~45 minutes                                              │
│  • Breakdown by country:                                                     │
│    - Iran: 3,545 clusters (from 7,024 articles)                             │
│    - China: 2,109 clusters (from 3,736 articles)                            │
│    - United States: 1,859 clusters (from 2,989 articles)                    │
│    - Turkey: 1,612 clusters (from 2,714 articles)                           │
│    - Russia: 1,163 clusters (from 1,884 articles)                           │
│  • Compression ratio: ~56% (18K articles → 10K clusters)                    │
│  • Cost: $0 (no LLM usage)                                                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: LLM DECONFLICTION (IN PROGRESS)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Status: Currently running (Sep 2024 data)                                 │
│  • Input: 10,288 clusters                                                    │
│  • Batch size: 150 events per LLM batch                                      │
│  • Model: GPT-4o-mini                                                        │
│  • Chain-of-thought: 4-step temporal tracking                               │
│  • Estimated time: 2-3 hours                                                 │
│  • Estimated cost: $5-10                                                     │
│  • Expected output: ~10K canonical events + daily mentions                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: TEMPORAL CONSOLIDATION                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Status: Pending implementation                                            │
│  • Goal: Create master events from canonical events                         │
│  • Expected compression: 10K canonical → ~3-5K master events                │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: SUMMARY GENERATION                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Status: Pending (awaits Step 3)                                           │
│  • Top N events per day: 10                                                  │
│  • Expected summaries: 30 days × 5 countries × 10 events = 1,500 summaries  │
│  • Estimated time: 30-60 minutes                                             │
│  • Estimated cost: $5-7                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Algorithms

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DBSCAN CLUSTERING                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  Parameters:                                                                  │
│    • eps = 0.15 (maximum distance for clustering)                           │
│    • min_samples = 2 (minimum points to form cluster)                       │
│    • metric = cosine distance                                                │
│                                                                               │
│  Why DBSCAN?                                                                  │
│    • Handles noise (outlier events)                                          │
│    • No need to specify number of clusters                                   │
│    • Works well with high-dimensional embeddings (384D)                      │
│    • Density-based (groups semantically similar events)                      │
│                                                                               │
│  Distance Metric:                                                             │
│    cosine_distance(v1, v2) = 1 - (v1 · v2) / (||v1|| × ||v2||)             │
│                                                                               │
│  Tuning:                                                                      │
│    • Lower eps (0.10-0.12): Stricter, more clusters                         │
│    • Higher eps (0.20-0.30): Looser, fewer clusters                         │
│    • Default 0.15: Balanced for news events                                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  EMBEDDING GENERATION                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  Model: sentence-transformers/all-MiniLM-L6-v2                               │
│    • Output: 384-dimensional vectors                                         │
│    • Speed: ~1000 sentences/second on CPU                                    │
│    • Quality: Optimized for semantic similarity                              │
│                                                                               │
│  Process:                                                                     │
│    1. Normalize event name (lowercase, remove punctuation)                   │
│    2. Pass to transformer model                                              │
│    3. Get fixed-length vector representation                                 │
│    4. Store for clustering and similarity search                             │
│                                                                               │
│  Example:                                                                     │
│    Input:  "China announces Belt and Road Forum"                             │
│    Output: [0.123, -0.456, 0.789, ..., 0.234]  (384 dimensions)             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CHAIN-OF-THOUGHT REASONING                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 1: Identify Core Events                                                │
│    • Extract: main activity, actors, context                                 │
│    • Example: "forum", "China", "September 2024"                             │
│                                                                               │
│  Step 2: Match Across Stages                                                 │
│    • Look for temporal evolution indicators:                                 │
│      - "announces" → "preparing" → "begins" → "continues" → "concludes"      │
│    • Group events with same core but different stages                        │
│                                                                               │
│  Step 3: Distinguish Different Events                                        │
│    • Separate based on:                                                      │
│      - Different instances ("First meeting" vs "Second meeting")             │
│      - Different topics (trade vs defense)                                   │
│      - Different entities (different countries)                              │
│                                                                               │
│  Step 4: Validation                                                           │
│    • Ask: Would these fit the same event timeline?                           │
│    • Check: Same actors, same context, same initiative?                      │
│                                                                               │
│  Output: JSON with groups, reasoning, and lifecycle stages                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Current Status Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SEPTEMBER 2024 PIPELINE STATUS                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ✓ Step 1: Daily Clustering                    COMPLETE                      │
│    └─ 10,288 clusters created from 18,347 articles                           │
│                                                                               │
│  ⟳ Step 2: LLM Deconfliction                  IN PROGRESS                    │
│    └─ Processing with temporal tracking chain-of-thought                     │
│    └─ Batch size increased to 150 events                                     │
│    └─ Unicode encoding issues resolved                                       │
│                                                                               │
│  ⧖ Step 3: Temporal Consolidation             PENDING                        │
│    └─ Awaiting implementation or integration into Step 2                     │
│                                                                               │
│  ⧖ Step 4: Summary Generation                 PENDING                        │
│    └─ Awaits completion of Steps 2-3                                         │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```
