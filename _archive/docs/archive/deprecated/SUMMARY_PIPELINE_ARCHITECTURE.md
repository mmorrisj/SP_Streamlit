# Summary Pipeline Architecture Diagram

## Data Flow Visualization

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXISTING INFRASTRUCTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Documents (439K) → Clustering → LLM Deconfliction → Master Events (3.5K)│
│                                                                           │
│  Master Events have:                                                      │
│  ✓ canonical_name, initiating_country, date_range                       │
│  ✓ primary_categories, primary_recipients                               │
│  ✓ daily_event_mentions (with doc_ids)                                  │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       NEW SUMMARY PIPELINE                               │
└─────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  PHASE 1: DAILY SUMMARIES                                  │
│  Script: generate_daily_summaries.py                       │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  For each day (Aug 1-31) × country (5):                    │
│                                                              │
│  1. Query: Get master events active on this day             │
│     SELECT * FROM canonical_events m                        │
│     JOIN daily_event_mentions dem ON dem.canonical_event_id│
│     WHERE dem.mention_date = '2024-08-15'                   │
│       AND m.initiating_country = 'Iran'                     │
│     ORDER BY dem.article_count DESC                         │
│     LIMIT 10                                                │
│                                                              │
│  2. For each event:                                         │
│     - Get 5 representative documents from dem.doc_ids       │
│     - Extract document text                                 │
│                                                              │
│  3. LLM Call:                                               │
│     ┌──────────────────────────────────────┐               │
│     │ INPUT (3K tokens)                    │               │
│     │ - Event names                        │               │
│     │ - Sample article texts               │               │
│     │ - Categories/recipients              │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ GPT-4o                               │               │
│     │ temp=0.3, max_tokens=2000            │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ OUTPUT (1.5K tokens)                 │               │
│     │ {                                    │               │
│     │   "events": [                        │               │
│     │     {                                │               │
│     │       "event_name": "...",           │               │
│     │       "overview": "...",             │               │
│     │       "outcomes": ["...", "..."]     │               │
│     │     }                                │               │
│     │   ]                                  │               │
│     │ }                                    │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│  4. Store:                                                  │
│     INSERT INTO event_summaries (                          │
│       period_type = 'DAILY',                               │
│       period_start = '2024-08-15',                         │
│       period_end = '2024-08-15',                           │
│       event_name = '...',                                  │
│       narrative_summary = {                                │
│         "overview": "...",                                 │
│         "outcomes": [...]                                  │
│       },                                                   │
│       count_by_category = {...},                          │
│       count_by_recipient = {...}                          │
│     )                                                      │
│                                                              │
│  Output: 155 daily summaries (31 days × 5 countries)       │
│  Cost: ~$0.66                                               │
└────────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────────┐
│  PHASE 2: WEEKLY SUMMARIES                                 │
│  Script: generate_weekly_summaries.py                      │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  For each week (4-5 weeks) × country (5):                  │
│                                                              │
│  1. Query: Get daily summaries for this week                │
│     SELECT * FROM event_summaries                          │
│     WHERE period_type = 'DAILY'                            │
│       AND period_start BETWEEN '2024-08-11' AND '2024-08-17'│
│       AND initiating_country = 'Iran'                      │
│                                                              │
│  2. Group by event_name:                                    │
│     - Combine overviews from multiple days                  │
│     - Merge outcomes (deduplicate)                          │
│     - Track progression                                     │
│                                                              │
│  3. LLM Call:                                               │
│     ┌──────────────────────────────────────┐               │
│     │ INPUT (11K tokens)                   │               │
│     │ Monday: [daily summaries]            │               │
│     │ Tuesday: [daily summaries]           │               │
│     │ ...                                  │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ GPT-4o                               │               │
│     │ "Synthesize 7 days into weekly arc"  │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ OUTPUT (2K tokens)                   │               │
│     │ {                                    │               │
│     │   "events": [                        │               │
│     │     {                                │               │
│     │       "event_name": "...",           │               │
│     │       "weekly_overview": "...",      │               │
│     │       "key_outcomes": [...],         │               │
│     │       "progression": "..."           │               │
│     │     }                                │               │
│     │   ]                                  │               │
│     │ }                                    │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│  4. Store as WEEKLY EventSummary                            │
│                                                              │
│  Output: ~25 weekly summaries (5 weeks × 5 countries)       │
│  Cost: ~$0.30                                               │
└────────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────────┐
│  PHASE 3: MONTHLY SUMMARIES                                │
│  Script: generate_monthly_summaries.py                     │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  For each country (5):                                      │
│                                                              │
│  1. Query: Get weekly summaries for August                  │
│     SELECT * FROM event_summaries                          │
│     WHERE period_type = 'WEEKLY'                           │
│       AND period_start >= '2024-08-01'                     │
│       AND period_end <= '2024-08-31'                       │
│       AND initiating_country = 'Iran'                      │
│                                                              │
│  2. Rank events by total coverage across weeks              │
│     - Select top 15-20 most significant                     │
│                                                              │
│  3. LLM Call (Per Event):                                   │
│     ┌──────────────────────────────────────┐               │
│     │ INPUT (10.5K tokens)                 │               │
│     │ Week 1: [weekly overview]            │               │
│     │ Week 2: [weekly overview]            │               │
│     │ Week 3: [weekly overview]            │               │
│     │ Week 4: [weekly overview]            │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ GPT-4o                               │               │
│     │ "Show full monthly arc + outcomes"   │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ OUTPUT (2.5K tokens)                 │               │
│     │ {                                    │               │
│     │   "monthly_overview": "...",         │               │
│     │   "key_outcomes": [...],             │               │
│     │   "strategic_significance": "..."    │               │
│     │ }                                    │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│  4. LLM Call (Country-Level):                               │
│     ┌──────────────────────────────────────┐               │
│     │ INPUT: All event monthly summaries   │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ GPT-4o                               │               │
│     │ "Create executive country summary"   │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│     ┌──────────────────────────────────────┐               │
│     │ FINAL MONTHLY SUMMARY                │               │
│     │ - Executive overview (2-3 paragraphs)│               │
│     │ - Key themes                         │               │
│     │ - Strategic outcomes                 │               │
│     │ - Notable trends                     │               │
│     └──────────────────────────────────────┘               │
│                    ↓                                         │
│  5. Store:                                                  │
│     - EventSummary records (period_type=MONTHLY)            │
│     - PeriodSummary (country-level overview)                │
│                                                              │
│  Output: 5 monthly summaries (1 per country)                │
│  Cost: ~$0.10                                               │
└────────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────────┐
│  FINAL OUTPUT                                               │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  Per Country (e.g., Iran - August 2024):                   │
│  ┌──────────────────────────────────────────┐              │
│  │ IRAN - AUGUST 2024 SUMMARY               │              │
│  │                                          │              │
│  │ Executive Overview:                      │              │
│  │ Iran's August activities centered on...  │              │
│  │ [2-3 paragraphs]                         │              │
│  │                                          │              │
│  │ Top Events:                              │              │
│  │ 1. Arbaeen Pilgrimage Support            │              │
│  │    Overview: [monthly arc]               │              │
│  │    Outcomes:                             │              │
│  │    - Facilitated 4.2M pilgrims           │              │
│  │    - 180+ medical teams                  │              │
│  │    - Enhanced soft power in Iraq         │              │
│  │                                          │              │
│  │ 2. Russia Defense Cooperation            │              │
│  │    Overview: [monthly arc]               │              │
│  │    Outcomes:                             │              │
│  │    - UAV tech transfer signed            │              │
│  │    - Joint exercises planned             │              │
│  │                                          │              │
│  │ Key Themes:                              │              │
│  │ - Religious/Cultural Diplomacy           │              │
│  │ - Strategic Partnerships                 │              │
│  │ - Economic Reconstruction                │              │
│  │                                          │              │
│  │ Strategic Significance:                  │              │
│  │ [Assessment of overall impact]           │              │
│  │                                          │              │
│  │ Statistics:                              │              │
│  │ - Total Events: 487                      │              │
│  │ - Total Articles: 12,450                 │              │
│  │ - Top Categories: Social (55%), ...      │              │
│  │ - Top Recipients: Iraq (66%), ...        │              │
│  └──────────────────────────────────────────┘              │
│                                                              │
│  Available as:                                              │
│  ✓ JSON (via API)                                           │
│  ✓ Streamlit Dashboard Page                                 │
│  ✓ PDF Export                                               │
│  ✓ Email Digest                                             │
│                                                              │
└────────────────────────────────────────────────────────────┘
```

## Database Tables Used

```sql
-- INPUT: Existing master events
canonical_events (3,571 records)
  ├─ id, canonical_name, initiating_country
  ├─ first_mention_date, last_mention_date
  ├─ primary_categories, primary_recipients
  └─ total_articles, total_mention_days

daily_event_mentions (daily occurrences)
  ├─ canonical_event_id (FK)
  ├─ mention_date
  ├─ article_count
  └─ doc_ids (array of document IDs)

-- OUTPUT: New summary records
event_summaries (new records)
  ├─ period_type (DAILY/WEEKLY/MONTHLY)
  ├─ period_start, period_end
  ├─ event_name, initiating_country
  ├─ narrative_summary (JSONB) ← NEW FIELD
  │   ├─ overview
  │   ├─ outcomes
  │   └─ significance
  ├─ count_by_category (JSONB)
  ├─ count_by_recipient (JSONB)
  └─ count_by_source (JSONB)

period_summaries (country-level aggregations)
  ├─ period_type (DAILY/WEEKLY/MONTHLY)
  ├─ period_start, period_end
  ├─ initiating_country
  ├─ overview ← LLM-generated executive summary
  ├─ outcome ← LLM-generated strategic outcomes
  ├─ metrics ← Statistics and trends
  └─ aggregated_categories/recipients/sources
```

## Execution Timeline

```
Week 1: Setup
├─ Add narrative_summary column to event_summaries
├─ Create services/pipeline/summaries/ directory
├─ Write prompt templates
└─ Write utility functions

Week 2: Phase 1 (Daily Summaries)
├─ Implement generate_daily_summaries.py
├─ Test on single day/country
├─ Process all August 2024
└─ Validate 155 daily summaries created

Week 3: Phase 2 (Weekly Summaries)
├─ Implement generate_weekly_summaries.py
├─ Test on single week/country
├─ Process all August weeks
└─ Validate ~25 weekly summaries created

Week 4: Phase 3 (Monthly Summaries)
├─ Implement generate_monthly_summaries.py
├─ Generate 5 monthly summaries
├─ Create PeriodSummary records
└─ Validate output quality

Week 5: Delivery & Polish
├─ Create Streamlit dashboard page
├─ Add PDF export functionality
├─ Build email digest system
└─ Documentation and handoff
```

## Token Budget & Costs

```
Daily Summaries:  155 × 4,500 tokens  = ~700K tokens  → $0.66
Weekly Summaries:  25 × 13,000 tokens = ~325K tokens  → $0.30
Monthly Summaries:  5 × 13,000 tokens =  ~65K tokens  → $0.10
                                        ─────────────────────
                                  Total = ~1.09M tokens → $1.06

For comparison:
- One analyst hour: ~$50-100
- This pipeline: $1.06 + dev time (one-time)
- Monthly recurring cost: $1-2 for updates
```

## Success Metrics

✓ All 155 daily summaries generated without errors
✓ LLM outputs match JSON schema 95%+ of time
✓ Human review finds summaries accurate and useful
✓ Monthly summaries provide actionable strategic insights
✓ Process completes in <3 hours for full month
✓ Cost stays under $2 per month
