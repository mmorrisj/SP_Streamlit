# Hierarchical Summary Pipeline Proposal

## Executive Summary

Build a **bottom-up hierarchical summarization pipeline** that produces daily → weekly → monthly summaries for each influencer country, with each summary containing:
1. **Key events** - Most significant events for that period
2. **Overview** - Narrative synthesis of developments
3. **Outcomes** - Specific results/impacts of each event

## Recommended Architecture

### **Pipeline Flow**

```
Master Events (3,571 for Aug 2024)
         ↓
    Daily Summaries (31 days × 5 countries = 155 summaries)
         ↓
    Weekly Summaries (4-5 weeks × 5 countries = ~25 summaries)
         ↓
    Monthly Summaries (1 month × 5 countries = 5 summaries)
```

### **Why This Approach?**

✅ **Leverage existing master events** - You already have high-quality consolidated events
✅ **Incremental summarization** - Each level synthesizes the level below, reducing hallucination
✅ **Consistent structure** - Same format across all time periods
✅ **Efficient token usage** - Summaries get progressively smaller as you move up
✅ **Traceability** - Each summary links back to source events and documents

## Detailed Pipeline Design

### **Phase 1: Daily Event Summaries**

**Input:** Master events that were active on a specific day for a specific country
**Output:** EventSummary records with `period_type=DAILY`

**Process:**
```python
For each day in August 2024:
    For each influencer country:
        1. Get all master events active on that day (via daily_event_mentions)
        2. Filter to top N events by article_count (e.g., top 10)
        3. For each top event:
            - Extract doc_ids from daily_event_mentions
            - Sample representative documents (e.g., 3-5 most central)
            - Create LLM prompt with event context
        4. Call LLM to generate:
            - Event name (from canonical_name)
            - Brief overview (2-3 sentences per event)
            - Specific outcomes (bullet points of concrete results)
        5. Store as EventSummary with:
            - period_type = DAILY
            - period_start = period_end = target_date
            - Populated JSONB fields for categories/recipients/sources
```

**LLM Prompt Template:**
```
You are analyzing news coverage for {country} on {date}.

Below are the top events for this day with sample articles:

EVENT 1: {canonical_name}
- Articles: {article_count}
- Categories: {categories}
- Recipients: {recipients}
Sample articles:
{article_texts}

EVENT 2: ...

For each event, provide:
1. Event Name: (use canonical name)
2. Overview: (2-3 sentence summary of developments)
3. Outcomes: (specific concrete results, diplomatic reactions, policy changes)

Format as JSON:
{
  "events": [
    {
      "event_name": "...",
      "overview": "...",
      "outcomes": ["...", "..."]
    }
  ]
}
```

**Storage:**
- One `EventSummary` record per event per day
- `PeriodSummary` for the day aggregates stats (total events, docs, categories)

---

### **Phase 2: Weekly Event Summaries**

**Input:** Daily EventSummary records for the week
**Output:** EventSummary records with `period_type=WEEKLY`

**Process:**
```python
For each week in August 2024:
    For each influencer country:
        1. Get all daily EventSummary records for the week
        2. Group by event_name (same event across multiple days)
        3. For each event that appeared in the week:
            - Aggregate daily overviews
            - Aggregate daily outcomes
            - Track which days it appeared
        4. Call LLM to synthesize:
            - Weekly event overview (consolidate daily summaries)
            - Weekly outcomes (deduplicate and organize)
            - Progression narrative (how event evolved)
        5. Store as EventSummary with:
            - period_type = WEEKLY
            - period_start = first day of week
            - period_end = last day of week
```

**LLM Prompt Template:**
```
You are creating a weekly summary for {country} covering {week_start} to {week_end}.

Below are daily summaries for key events:

EVENT: {event_name}
Active on: {list_of_days}

Daily summaries:
{date_1}: {overview_1}
  Outcomes: {outcomes_1}
{date_2}: {overview_2}
  Outcomes: {outcomes_2}
...

Synthesize into a weekly summary:
1. Weekly Overview: (3-4 sentences showing progression)
2. Key Outcomes: (consolidated list of distinct outcomes)
3. Significance: (why this event mattered this week)

Format as JSON.
```

---

### **Phase 3: Monthly Event Summaries**

**Input:** Weekly EventSummary records for the month
**Output:** EventSummary records with `period_type=MONTHLY` + PeriodSummary for the month

**Process:**
```python
For each month:
    For each influencer country:
        1. Get all weekly EventSummary records
        2. Rank events by total article coverage across all weeks
        3. Select top 15-20 most significant events
        4. For each top event:
            - Aggregate weekly summaries
            - Track temporal evolution
        5. Call LLM to create:
            - Monthly event narrative (how it evolved over month)
            - Comprehensive outcomes list
            - Strategic significance assessment
        6. Create PeriodSummary for the entire month:
            - Overview: High-level narrative of country's activities
            - Key themes and patterns
            - Strategic implications
```

**LLM Prompt Template (Per-Event):**
```
You are creating a monthly summary for {country} in {month} {year}.

EVENT: {event_name}
Total articles: {total_articles}
Active weeks: {week_count}

Weekly progressions:
Week 1 ({dates}): {weekly_overview_1}
  Outcomes: {weekly_outcomes_1}
Week 2 ({dates}): {weekly_overview_2}
  Outcomes: {weekly_outcomes_2}
...

Create monthly summary:
1. Monthly Overview: (4-5 sentences showing full arc)
2. Key Outcomes: (final consolidated outcomes)
3. Strategic Significance: (impact on regional dynamics)

Format as JSON.
```

**LLM Prompt Template (Country-Level Monthly Summary):**
```
You are creating an overall monthly summary for {country} in {month} {year}.

Top events:
1. {event_1_name} - {event_1_monthly_overview}
2. {event_2_name} - {event_2_monthly_overview}
...

Aggregated statistics:
- Total events tracked: {total_events}
- Total articles: {total_articles}
- Primary categories: {category_breakdown}
- Primary recipients: {recipient_breakdown}

Create comprehensive monthly summary:
1. Executive Overview: (2-3 paragraph narrative of the month)
2. Key Themes: (major patterns across all events)
3. Strategic Outcomes: (overall impact on regional influence)
4. Notable Trends: (changes in activity patterns)

Format as JSON.
```

---

## Implementation Plan

### **Scripts to Create**

```
services/pipeline/summaries/
├── generate_daily_summaries.py      # Phase 1
├── generate_weekly_summaries.py     # Phase 2
├── generate_monthly_summaries.py    # Phase 3
├── summary_prompts.py               # LLM prompt templates
└── summary_utils.py                 # Helper functions
```

### **Key Implementation Details**

#### **1. Document Sampling Strategy**

For each event, select representative documents:
```python
def get_representative_documents(event_id, date, limit=5):
    """
    Get most representative documents for an event on a specific day.

    Strategy:
    1. Get all doc_ids from daily_event_mentions
    2. If > limit, sample by:
       - Temporal centrality (mid-day articles)
       - Source diversity (different news sources)
       - Length (prefer longer, more detailed articles)
    """
    pass
```

#### **2. LLM Configuration**

Use GPT-4 for quality summaries:
```python
model = "gpt-4o"  # From config.yaml: aws.default_model
temperature = 0.3  # Low for consistency
max_tokens = 2000  # Sufficient for structured output
```

#### **3. Chunking Strategy**

For days with many events:
```python
if num_events > 10:
    # Process in batches
    batches = chunk_events(events, batch_size=10)
    for batch in batches:
        summaries = generate_batch_summaries(batch)
```

#### **4. Error Handling**

```python
@retry(max_attempts=3, backoff=exponential)
def call_llm_with_retry(prompt):
    """Retry LLM calls with exponential backoff"""
    pass

def validate_summary_json(response):
    """Ensure LLM response matches expected schema"""
    required_fields = ['event_name', 'overview', 'outcomes']
    # Validate and repair if possible
```

---

## Database Schema Usage

### **EventSummary Table**

You already have the perfect schema! Here's how to use it:

```python
# Daily summary
daily_summary = EventSummary(
    period_type=PeriodType.DAILY,
    period_start=date(2024, 8, 15),
    period_end=date(2024, 8, 15),
    event_name="Ceasefire Proposal in Gaza",
    initiating_country="United States",
    first_observed_date=date(2024, 8, 1),
    last_observed_date=date(2024, 8, 31),
    status=EventStatus.ACTIVE,

    # Store LLM-generated content in existing text fields
    # Use a JSONB column for structured event data:
    count_by_category={'Diplomacy': 156, 'Military': 89},
    count_by_recipient={'Israel': 98, 'Palestine': 87, 'Egypt': 45},
    count_by_source={'Reuters': 45, 'AP': 38, ...},

    # Counts
    category_count=2,
    recipient_count=3,
    source_count=15,
    total_documents_across_categories=245  # Sum of category counts
)
```

**IMPORTANT:** The current schema doesn't have dedicated fields for `overview` and `outcomes`. You have two options:

**Option A:** Add new JSONB field for narrative content:
```sql
ALTER TABLE event_summaries
ADD COLUMN narrative_summary JSONB DEFAULT '{}'::jsonb;

-- Store like:
{
  "overview": "...",
  "outcomes": ["...", "..."],
  "significance": "..."
}
```

**Option B:** Use `PeriodSummary` fields (already exists):
```python
# PeriodSummary.overview - for narrative overview
# PeriodSummary.outcome - for outcomes text
# PeriodSummary.metrics - for metrics/stats
```

**Recommendation:** Use **Option A** to keep event-level narratives separate from period aggregations.

### **PeriodSummary Table**

Use for daily/weekly/monthly country-level aggregations:

```python
# Monthly country summary
monthly_summary = PeriodSummary(
    period_type=PeriodType.MONTHLY,
    period_start=date(2024, 8, 1),
    period_end=date(2024, 8, 31),
    initiating_country="Iran",

    overview="Iran's August activities centered on...",  # ← LLM-generated
    outcome="Key outcomes included...",  # ← LLM-generated
    metrics="Statistical summary...",

    total_events=487,
    total_documents=12450,
    total_sources=234,

    aggregated_categories={'Social': 6789, 'Diplomacy': 3456, ...},
    aggregated_recipients={'Iraq': 4567, 'Syria': 3210, ...},
    aggregated_sources={'IRNA': 890, 'Tasnim': 678, ...}
)
```

---

## Execution Strategy

### **Sequential Processing (Recommended)**

```bash
# Phase 1: Generate daily summaries
python services/pipeline/summaries/generate_daily_summaries.py \
  --start-date 2024-08-01 \
  --end-date 2024-08-31 \
  --countries China Russia Iran Turkey "United States"

# Phase 2: Generate weekly summaries (after daily complete)
python services/pipeline/summaries/generate_weekly_summaries.py \
  --start-date 2024-08-01 \
  --end-date 2024-08-31 \
  --countries China Russia Iran Turkey "United States"

# Phase 3: Generate monthly summaries (after weekly complete)
python services/pipeline/summaries/generate_monthly_summaries.py \
  --month 2024-08 \
  --countries China Russia Iran Turkey "United States"
```

### **Parallel Processing (Advanced)**

Use Celery tasks to parallelize country processing:
```python
# Process all 5 countries in parallel
for country in countries:
    generate_daily_summaries.delay(
        country=country,
        start_date='2024-08-01',
        end_date='2024-08-31'
    )
```

---

## Token Estimation & Cost

### **Daily Summaries**

```
Per day per country:
- Top 10 events
- 5 sample articles per event × 500 tokens each = 2,500 tokens
- Prompt overhead: ~500 tokens
- Total input: ~3,000 tokens per day
- Output: ~1,500 tokens

August 2024: 31 days × 5 countries = 155 daily summaries
Total tokens: 155 × 4,500 = ~700K tokens
Cost (GPT-4o): ~$0.21 (input) + $0.45 (output) = $0.66
```

### **Weekly Summaries**

```
Per week per country:
- Daily summaries: 7 days × 1,500 tokens = 10,500 tokens
- Prompt overhead: ~300 tokens
- Total input: ~11,000 tokens
- Output: ~2,000 tokens

August 2024: 5 weeks × 5 countries = 25 weekly summaries
Total tokens: 25 × 13,000 = ~325K tokens
Cost (GPT-4o): ~$0.10 + $0.20 = $0.30
```

### **Monthly Summaries**

```
Per month per country:
- Weekly summaries: 4-5 weeks × 2,000 tokens = 10,000 tokens
- Prompt overhead: ~500 tokens
- Total input: ~10,500 tokens
- Output: ~2,500 tokens

August 2024: 1 month × 5 countries = 5 monthly summaries
Total tokens: 5 × 13,000 = ~65K tokens
Cost (GPT-4o): ~$0.02 + $0.08 = $0.10
```

**Total Cost for August 2024: ~$1.06** (very affordable!)

---

## Output Format Example

### **Daily Summary (Aug 15, 2024 - Iran)**

```json
{
  "date": "2024-08-15",
  "country": "Iran",
  "total_events": 12,
  "total_articles": 456,
  "key_events": [
    {
      "event_name": "Arbaeen Pilgrimage Support Services",
      "overview": "Iran continued large-scale logistical support for Arbaeen pilgrims traveling to Karbala. Coordination with Iraqi authorities expanded, with additional border crossings opened and medical facilities deployed.",
      "outcomes": [
        "Opened 3 additional border crossings (Mehran, Shalamcheh, Chazabeh)",
        "Deployed 45 medical teams along pilgrimage routes",
        "Iraq thanked Iran for cooperation in joint statement"
      ],
      "articles": 89,
      "categories": ["Social", "Diplomacy"],
      "recipients": ["Iraq"]
    },
    {
      "event_name": "Russia-Iran Defense Cooperation Meeting",
      "overview": "High-level defense officials met in Tehran to discuss military-technical cooperation. Focus on joint production of UAVs and missile systems.",
      "outcomes": [
        "Signed MoU for UAV technology transfer",
        "Agreed to joint air defense exercises in Caspian Sea",
        "Russia to invest in Iranian defense manufacturing facility"
      ],
      "articles": 67,
      "categories": ["Military", "Economic"],
      "recipients": ["Russia"]
    }
  ]
}
```

### **Monthly Summary (August 2024 - Iran)**

```json
{
  "month": "2024-08",
  "country": "Iran",
  "executive_overview": "Iran's August activities centered on three main themes: religious diplomacy through Arbaeen pilgrimage support, deepening military-technical cooperation with Russia, and expanding economic engagement in Iraq and Syria. The Arbaeen pilgrimage dominated social and diplomatic channels, with Iran providing unprecedented logistical support to millions of pilgrims. Simultaneously, defense cooperation with Russia intensified, including UAV technology transfers and joint military exercises. Economic outreach focused on reconstruction projects in Iraq and Syria, leveraging cultural and religious ties.",

  "key_events": [
    {
      "event_name": "Arbaeen Pilgrimage Support Services",
      "monthly_overview": "Iran provided comprehensive support for Arbaeen pilgrimage throughout August, coordinating with Iraq on border management, medical services, and transportation. Support scaled up progressively, peaking in final week with over 4 million pilgrims crossing borders. Created significant positive coverage in Iraqi and regional media.",
      "outcomes": [
        "Facilitated safe passage for 4.2M pilgrims through 7 border crossings",
        "Deployed 180+ medical teams providing free healthcare",
        "Secured multiple public acknowledgments from Iraqi government",
        "Enhanced Iran's soft power image in Iraq and broader Shia communities"
      ],
      "strategic_significance": "Reinforced Iran's position as protector of Shia religious practices and strengthened popular support in Iraq, complementing government-to-government relations."
    },
    {
      "event_name": "Russia-Iran Defense Cooperation",
      "monthly_overview": "Defense ties deepened significantly with multiple high-level meetings, technology transfer agreements, and joint exercise planning. Focus on UAV production, air defense systems, and Caspian Sea security. Represents strategic alignment amid Western sanctions.",
      "outcomes": [
        "UAV technology transfer agreement signed",
        "Commitment to joint air defense system development",
        "Planned joint naval exercises in Caspian Sea (Sept 2024)",
        "Russian investment in Iranian defense manufacturing"
      ],
      "strategic_significance": "Solidifies Iran-Russia military partnership and reduces Iran's technological isolation under sanctions regime."
    }
  ],

  "key_themes": [
    "Religious/Cultural Diplomacy: Leveraging Shia identity for regional influence",
    "Strategic Partnerships: Deepening Russia ties amid Western pressure",
    "Economic Reconstruction: Positioning as key player in Iraq/Syria rebuilding"
  ],

  "strategic_outcomes": "August demonstrated Iran's multi-faceted influence strategy combining soft power (religious diplomacy), hard power (military cooperation), and economic engagement. Arbaeen support enhanced popular legitimacy in Iraq while defense cooperation with Russia strengthened deterrence capabilities.",

  "notable_trends": [
    "Increased focus on Iraq as primary influence target",
    "Growing military-technical cooperation with Russia",
    "Use of religious events for diplomatic gains"
  ],

  "statistics": {
    "total_events": 487,
    "total_articles": 12450,
    "top_categories": {
      "Social": 6789,
      "Diplomacy": 3456,
      "Military": 1890,
      "Economic": 315
    },
    "top_recipients": {
      "Iraq": 8234,
      "Syria": 2109,
      "Russia": 1456,
      "Lebanon": 651
    }
  }
}
```

---

## Alternative Approaches Considered

### ❌ **Top-Down (Month → Week → Day)**
**Cons:**
- Prone to hallucination without bottom-up grounding
- Can't validate against actual event data
- Less traceable

### ❌ **Single-Pass Monthly Summaries**
**Cons:**
- Must process thousands of events at once
- Exceeds context windows
- Loses nuance and detail
- No intermediate checkpoints

### ✅ **Recommended: Bottom-Up Hierarchical (Day → Week → Month)**
**Pros:**
- Each level grounded in previous level
- Manageable token counts per call
- Preserves event detail
- Allows human review at each level
- Incremental processing (can resume if interrupted)

---

## Next Steps

### **Immediate (Week 1)**
1. Add `narrative_summary` JSONB column to `event_summaries` table
2. Create `services/pipeline/summaries/` directory structure
3. Write `summary_prompts.py` with all LLM templates
4. Write `summary_utils.py` with helper functions

### **Phase 1 Implementation (Week 2)**
1. Implement `generate_daily_summaries.py`
2. Test on single day (Aug 15, 2024) for one country (Iran)
3. Validate EventSummary storage
4. Process all of August for all countries

### **Phase 2 Implementation (Week 3)**
1. Implement `generate_weekly_summaries.py`
2. Test on one week for one country
3. Process all weeks of August

### **Phase 3 Implementation (Week 4)**
1. Implement `generate_monthly_summaries.py`
2. Generate final monthly summaries
3. Create dashboard page to display summaries

### **Polish (Week 5)**
1. Add export functionality (PDF, Word, JSON)
2. Create email digest system
3. Add comparison across months
4. Build trend analysis

---

## Questions to Consider

1. **Event Selection:** Top N events by article count or use salience/importance scoring?
2. **Document Sampling:** Random sampling or embedding-based centrality?
3. **Outcome Format:** Bullet points or narrative paragraphs?
4. **Human Review:** Should summaries require human approval before publication?
5. **Update Frequency:** Re-generate summaries as new data arrives or one-time generation?
6. **Multi-language:** Support non-English sources in summaries?

---

## Conclusion

This hierarchical pipeline leverages your excellent existing master event infrastructure to build rich, traceable summaries at multiple time scales. The bottom-up approach ensures accuracy while the structured format provides consistency across time periods and countries.

**Estimated effort:** 3-4 weeks for full implementation
**Estimated cost:** <$2/month for processing
**Expected output:** Professional-grade country reports suitable for briefings

Ready to start with Phase 1?
