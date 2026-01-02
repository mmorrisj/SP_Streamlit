# Source-Traceable Summary Pipeline
## Maintaining Full Fidelity to Source Documents

## Executive Summary

This proposal updates the hierarchical summary pipeline to **prioritize source traceability** - ensuring every claim in every summary is linked back to specific source documents with hyperlinks for user verification.

**Key Principle:** Every event overview and outcome statement must be traceable to specific `doc_ids` that support that claim.

---

## Architecture Changes for Source Traceability

### **1. Enhanced Data Storage**

#### **A. Add URL Field to Documents Table**

```sql
-- Add URL column to documents table
ALTER TABLE documents
ADD COLUMN source_url TEXT;

-- Create index for fast lookups
CREATE INDEX ix_documents_source_url ON documents(source_url);
```

**Populate Strategy:**
```python
# Option 1: If doc_id contains URL information
UPDATE documents SET source_url = doc_id WHERE doc_id LIKE 'http%';

# Option 2: Construct URL from metadata
UPDATE documents
SET source_url = 'https://example.com/article/' || doc_id;

# Option 3: Manual upload from external source
# Import from CSV mapping doc_id -> source_url
```

#### **B. Enhanced EventSourceLink Usage**

The existing `EventSourceLink` table is perfect - we'll use it extensively:

```python
class EventSourceLink(Base):
    event_summary_id: UUID  # Links to EventSummary
    doc_id: str  # Links to Document (and thus source_url)
    contribution_weight: float  # NEW: How much this doc supports the summary
    linked_at: datetime
```

**Strategy:**
- Store **ALL** doc_ids that contributed to a summary
- `contribution_weight` ranks documents by importance (0.0-1.0)
- Top-weighted documents become "Featured Sources" in UI

---

## Revised Pipeline with Source Tracking

### **Phase 1: Daily Summaries (Source-Grounded)**

```python
def generate_daily_summary(country, date):
    """
    Generate daily summary with full source traceability.
    """
    # 1. Get master events active on this day
    active_events = get_active_master_events(country, date)

    # 2. For each event, get ALL doc_ids for this day
    event_sources = {}
    for event in active_events[:10]:  # Top 10 events
        doc_ids = get_doc_ids_for_event_on_date(event.id, date)

        # 3. Select representative documents (but track ALL)
        representative_docs = select_representative_docs(doc_ids, limit=5)

        event_sources[event.canonical_name] = {
            'all_doc_ids': doc_ids,  # All supporting documents
            'featured_docs': representative_docs,  # Used in LLM prompt
            'doc_count': len(doc_ids)
        }

    # 4. Call LLM with featured docs
    summary_response = call_llm_for_daily_summary(
        country=country,
        date=date,
        events=active_events,
        event_sources=event_sources
    )

    # 5. Store summaries WITH source links
    for event_summary in summary_response['events']:
        # Create EventSummary record
        summary_record = EventSummary(
            period_type=PeriodType.DAILY,
            event_name=event_summary['event_name'],
            narrative_summary={
                'overview': event_summary['overview'],
                'outcomes': event_summary['outcomes'],
                'featured_sources': []  # Will populate below
            },
            ...
        )
        session.add(summary_record)
        session.flush()  # Get ID

        # 6. Create EventSourceLink records for ALL supporting docs
        source_info = event_sources[event_summary['event_name']]

        for doc_id in source_info['all_doc_ids']:
            # Weight: 1.0 for featured docs, 0.5 for others
            weight = 1.0 if doc_id in source_info['featured_docs'] else 0.5

            link = EventSourceLink(
                event_summary_id=summary_record.id,
                doc_id=doc_id,
                contribution_weight=weight
            )
            session.add(link)

        # 7. Store featured source metadata in narrative_summary
        summary_record.narrative_summary['featured_sources'] = [
            {
                'doc_id': doc.doc_id,
                'title': doc.title,
                'source_name': doc.source_name,
                'date': str(doc.date),
                'url': doc.source_url,  # NEW FIELD
                'excerpt': doc.distilled_text[:200]
            }
            for doc in source_info['featured_docs']
        ]

    session.commit()
```

---

### **Phase 2: Weekly Summaries (Aggregated Source Tracking)**

```python
def generate_weekly_summary(country, week_start, week_end):
    """
    Generate weekly summary by aggregating daily summaries.
    Maintains source links from all daily summaries.
    """
    # 1. Get all daily EventSummary records for this week
    daily_summaries = session.query(EventSummary).filter(
        EventSummary.period_type == PeriodType.DAILY,
        EventSummary.initiating_country == country,
        EventSummary.period_start >= week_start,
        EventSummary.period_end <= week_end
    ).all()

    # 2. Group by event_name
    events_by_name = defaultdict(list)
    for summary in daily_summaries:
        events_by_name[summary.event_name].append(summary)

    # 3. For each event, aggregate sources
    weekly_summaries = []
    for event_name, daily_summaries_list in events_by_name.items():
        # Get ALL source doc_ids from all daily summaries
        all_source_ids = set()
        for daily_summary in daily_summaries_list:
            # Query EventSourceLink to get all source doc_ids
            source_links = session.query(EventSourceLink).filter(
                EventSourceLink.event_summary_id == daily_summary.id
            ).all()
            all_source_ids.update([link.doc_id for link in source_links])

        # Aggregate daily overviews and outcomes
        daily_narratives = [
            {
                'date': s.period_start,
                'overview': s.narrative_summary.get('overview'),
                'outcomes': s.narrative_summary.get('outcomes'),
                'featured_sources': s.narrative_summary.get('featured_sources', [])
            }
            for s in daily_summaries_list
        ]

        # 4. Call LLM to synthesize weekly summary
        weekly_summary = call_llm_for_weekly_summary(
            event_name=event_name,
            daily_narratives=daily_narratives,
            total_source_count=len(all_source_ids)
        )

        # 5. Create weekly EventSummary
        weekly_record = EventSummary(
            period_type=PeriodType.WEEKLY,
            period_start=week_start,
            period_end=week_end,
            event_name=event_name,
            initiating_country=country,
            narrative_summary={
                'overview': weekly_summary['overview'],
                'outcomes': weekly_summary['outcomes'],
                'progression': weekly_summary['progression'],
                'source_breakdown_by_day': {
                    str(date): count for date, count in ...
                }
            }
        )
        session.add(weekly_record)
        session.flush()

        # 6. Link to ALL source documents from daily summaries
        # Use max contribution_weight from daily summaries
        doc_weights = defaultdict(float)
        for daily_summary in daily_summaries_list:
            source_links = session.query(EventSourceLink).filter(
                EventSourceLink.event_summary_id == daily_summary.id
            ).all()
            for link in source_links:
                doc_weights[link.doc_id] = max(
                    doc_weights[link.doc_id],
                    link.contribution_weight
                )

        for doc_id, weight in doc_weights.items():
            link = EventSourceLink(
                event_summary_id=weekly_record.id,
                doc_id=doc_id,
                contribution_weight=weight
            )
            session.add(link)

    session.commit()
```

---

### **Phase 3: Monthly Summaries (Complete Source Lineage)**

Same pattern - aggregate all sources from weekly summaries, maintaining full traceability chain:

```
Monthly EventSummary
    ↓ (EventSourceLink)
Weekly EventSummary
    ↓ (EventSourceLink)
Daily EventSummary
    ↓ (EventSourceLink)
Original Documents (with source_url)
```

---

## Enhanced LLM Prompts with Source Attribution

### **Daily Summary Prompt (Source-Aware)**

```python
DAILY_SUMMARY_PROMPT = """
You are analyzing news coverage for {country} on {date}.

For each event below, create a summary with specific attribution to sources.

EVENT: {event_name}
Articles analyzed: {doc_count}

Featured articles:
[1] {doc_1_title} - {doc_1_source} - {doc_1_date}
    Excerpt: {doc_1_excerpt}

[2] {doc_2_title} - {doc_2_source} - {doc_2_date}
    Excerpt: {doc_2_excerpt}

[3] ...

IMPORTANT: When you describe outcomes, cite which article number(s) support each claim.

Provide:
1. Overview: Brief summary of developments
2. Outcomes: Specific results with source citations

Format:
{{
  "overview": "According to [1] and [3], Iran provided... [2] reported that...",
  "outcomes": [
    {{
      "outcome": "Opened 3 additional border crossings",
      "supporting_sources": [1, 2],
      "confidence": "high"
    }},
    {{
      "outcome": "Deployed 45 medical teams",
      "supporting_sources": [1],
      "confidence": "medium"
    }}
  ]
}}
```

This allows you to map outcomes back to specific doc_ids!

---

## UI/Dashboard Implementation

### **Display Format with Hyperlinks**

```python
# Streamlit dashboard code
def display_event_summary(event_summary_id):
    """Display event summary with clickable source links."""

    # Get summary
    summary = session.get(EventSummary, event_summary_id)

    # Get source links with documents
    source_links = (
        session.query(EventSourceLink, Document)
        .join(Document, EventSourceLink.doc_id == Document.doc_id)
        .filter(EventSourceLink.event_summary_id == event_summary_id)
        .order_by(EventSourceLink.contribution_weight.desc())
        .all()
    )

    # Display summary
    st.header(summary.event_name)
    st.write(summary.narrative_summary['overview'])

    # Display outcomes with sources
    st.subheader("Key Outcomes")
    for outcome in summary.narrative_summary['outcomes']:
        st.markdown(f"**• {outcome['outcome']}**")

        # Show supporting sources as clickable links
        if 'supporting_sources' in outcome:
            source_indices = outcome['supporting_sources']
            featured_sources = summary.narrative_summary['featured_sources']

            cols = st.columns(len(source_indices))
            for i, source_idx in enumerate(source_indices):
                source = featured_sources[source_idx - 1]  # 1-indexed
                with cols[i]:
                    # Create clickable link
                    st.markdown(
                        f"[📰 {source['source_name']}]({source['url']})",
                        unsafe_allow_html=True
                    )
                    st.caption(f"{source['title'][:50]}...")

    # Show all sources section
    with st.expander(f"View All Sources ({len(source_links)})"):
        for link, doc in source_links:
            st.markdown(
                f"**[{doc.title}]({doc.source_url})**  \n"
                f"*{doc.source_name}* - {doc.date}  \n"
                f"Contribution: {'⭐' * int(link.contribution_weight * 5)}"
            )
```

### **Example Dashboard Display**

```
┌────────────────────────────────────────────────────────────────┐
│ Iran - August 15, 2024                                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Arbaeen Pilgrimage Support Services                           │
│                                                                 │
│ Overview:                                                      │
│ Iran continued large-scale logistical support for Arbaeen     │
│ pilgrims traveling to Karbala. Coordination with Iraqi        │
│ authorities expanded, with additional border crossings opened  │
│ and medical facilities deployed.                               │
│                                                                 │
│ Key Outcomes:                                                  │
│ • Opened 3 additional border crossings (Mehran, Shalamcheh)   │
│   ┌─────────────┐ ┌─────────────┐                            │
│   │ 📰 Reuters  │ │ 📰 AP News  │                            │
│   │ Iran opens  │ │ Border      │                            │
│   │ border...   │ │ crossing... │                            │
│   └─────────────┘ └─────────────┘                            │
│                                                                 │
│ • Deployed 45 medical teams along pilgrimage routes           │
│   ┌─────────────┐                                             │
│   │ 📰 IRNA     │                                             │
│   │ Medical     │                                             │
│   │ teams...    │                                             │
│   └─────────────┘                                             │
│                                                                 │
│ ▼ View All Sources (89 articles)                              │
│   • Iran Opens Additional Border Crossings for Arbaeen...     │
│     Reuters - 2024-08-15  Contribution: ⭐⭐⭐⭐⭐              │
│                                                                 │
│   • Medical Support Expanded for Pilgrims...                  │
│     AP News - 2024-08-15  Contribution: ⭐⭐⭐⭐⭐              │
│                                                                 │
│   • Iraq Thanks Iran for Cooperation...                       │
│     IRNA - 2024-08-15  Contribution: ⭐⭐⭐⭐                  │
│   ...                                                          │
└────────────────────────────────────────────────────────────────┘
```

---

## Database Schema Summary

### **Required Changes**

```sql
-- 1. Add URL field to documents
ALTER TABLE documents ADD COLUMN source_url TEXT;
CREATE INDEX ix_documents_source_url ON documents(source_url);

-- 2. Add narrative_summary to event_summaries (if not exists)
ALTER TABLE event_summaries
ADD COLUMN narrative_summary JSONB DEFAULT '{}'::jsonb;

-- Already exists (no changes needed):
-- - event_summaries table
-- - event_source_links table
-- - period_summaries table
```

### **EventSourceLink Usage Pattern**

```python
# For each EventSummary, track ALL source documents
EventSourceLink:
  - event_summary_id → EventSummary.id
  - doc_id → Document.doc_id → Document.source_url
  - contribution_weight (1.0 = featured, 0.5 = supporting)
```

---

## Source Traceability Benefits

### ✅ **Full Transparency**
- Every claim traceable to specific articles
- Users can click through to verify original sources
- Builds trust in AI-generated summaries

### ✅ **Academic Rigor**
- Citation-like system for news analysis
- Can export summaries with full bibliographies
- Defensible claims with evidence trail

### ✅ **Audit Trail**
- Track which documents contributed to which insights
- Identify most influential sources
- Detect potential biases in source selection

### ✅ **Legal Protection**
- Clear attribution to original sources
- No plagiarism concerns
- Proper credit to news organizations

---

## Implementation Priority

### **Phase 0: Setup (Week 1)**
1. ✅ Add `source_url` column to documents table
2. ✅ Populate URLs (manual upload or automated extraction)
3. ✅ Add `narrative_summary` JSONB column to event_summaries
4. ✅ Create source link tracking utilities

### **Phase 1: Daily Summaries (Week 2)**
1. Implement daily summary generation with source tracking
2. Store ALL doc_ids via EventSourceLink
3. Include featured sources in narrative_summary JSONB
4. Test on single day/country

### **Phase 2: Weekly Summaries (Week 3)**
1. Aggregate source links from daily summaries
2. Maintain source lineage through hierarchy
3. Generate weekly summaries with source attribution

### **Phase 3: Monthly Summaries (Week 4)**
1. Complete source lineage from monthly → weekly → daily → docs
2. Generate comprehensive monthly reports
3. Export with full source bibliography

### **Phase 4: Dashboard (Week 5)**
1. Create source-linked summary displays
2. Add clickable hyperlinks to original articles
3. Build "All Sources" expandable sections
4. Export functionality with citations

---

## Alternative: Outcome-Level Source Tracking

For even finer granularity, track sources per outcome:

```python
narrative_summary = {
    "overview": "...",
    "outcomes": [
        {
            "outcome": "Opened 3 border crossings",
            "supporting_doc_ids": ["doc123", "doc456"],  # Specific docs
            "confidence": "high",
            "source_count": 2
        },
        {
            "outcome": "Deployed 45 medical teams",
            "supporting_doc_ids": ["doc123"],
            "confidence": "medium",
            "source_count": 1
        }
    ]
}
```

This allows users to see exactly which articles support each specific claim!

---

## Cost Estimate (Unchanged)

Source tracking adds minimal cost:
- Daily summaries: $0.66 (same as before)
- Weekly summaries: $0.30
- Monthly summaries: $0.10
- **Total: ~$1.06**

The LLM prompt changes don't significantly increase token usage.

---

## Questions for You

1. **URL Source:** How will we populate `documents.source_url`?
   - Do you have a mapping file?
   - Is URL embedded in doc_id?
   - Need to extract from external system?

2. **Source Display:** For each outcome, show:
   - Top 3 supporting articles? All articles?
   - Just hyperlinks or include excerpts?

3. **Confidence Levels:** Should we ask LLM to rate confidence for each outcome?
   - High = supported by multiple sources
   - Medium = single source
   - Low = inferred/contextual

4. **Export Format:** Priority order?
   - PDF with clickable links
   - JSON with doc_id arrays
   - Word document with footnotes

---

## Conclusion

This revised pipeline maintains complete source traceability while still using the efficient hierarchical summarization approach. Every summary, at every level, is fully grounded in specific source documents that users can verify.

**Key Advantage:** Unlike typical LLM summaries that blend sources, this approach maintains forensic-level traceability from monthly insights down to individual articles.

Ready to implement Phase 0 (database setup)?
