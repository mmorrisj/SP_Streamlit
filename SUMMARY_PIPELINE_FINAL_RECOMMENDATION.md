# Final Recommendation: Source-Traceable Hierarchical Summary Pipeline

## Executive Summary

Build a **bottom-up hierarchical summarization pipeline** that leverages your existing `build_hyperlink()` utility to maintain complete source traceability from monthly summaries down to individual articles.

**Key Innovation:** Use `EventSourceLink` table + your `build_hyperlink()` method to provide clickable links to source documents at every level of summarization.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│  HIERARCHICAL SUMMARIES WITH SOURCE LINKS                     │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  Master Events (3,571)                                        │
│  ├─ doc_ids in daily_event_mentions                          │
│  └─ build_hyperlink(doc_ids) → External article viewer       │
│                                                                │
│  Daily Summaries (155)                                        │
│  ├─ EventSummary records (period_type=DAILY)                 │
│  ├─ EventSourceLink → doc_ids                                │
│  └─ narrative_summary['source_link'] = build_hyperlink(...)  │
│                                                                │
│  Weekly Summaries (~25)                                       │
│  ├─ Aggregates daily summaries                               │
│  ├─ EventSourceLink → all doc_ids from week                  │
│  └─ Source link aggregates all daily links                   │
│                                                                │
│  Monthly Summaries (5)                                        │
│  ├─ Top 15-20 events with full narrative arcs                │
│  ├─ EventSourceLink → all doc_ids from month                 │
│  ├─ PeriodSummary with executive overview                    │
│  └─ Master hyperlink to all supporting articles              │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

---

## Using `build_hyperlink()` for Source Attribution

### **Current Utility (Assumed Implementation)**

```python
def build_hyperlink(doc_ids: List[str]) -> str:
    """
    Takes a list of doc_ids and produces a useable hyperlink.

    Args:
        doc_ids: List of document IDs

    Returns:
        URL that opens external page showing all articles

    Example:
        doc_ids = ['doc123', 'doc456', 'doc789']
        → 'https://yourapp.com/articles?ids=doc123,doc456,doc789'
    """
    # Your implementation here
    pass
```

### **Integration into Summary Pipeline**

```python
def generate_daily_summary(country, date):
    """Generate daily summary with hyperlinked sources."""

    # 1. Get events active on this day
    active_events = get_active_master_events(country, date)

    # 2. For each event, get doc_ids
    for event in active_events[:10]:
        doc_ids = get_doc_ids_for_event_on_date(event.id, date)

        # 3. Generate summary via LLM
        summary = call_llm_for_summary(event, doc_ids)

        # 4. Create EventSummary record
        event_summary = EventSummary(
            period_type=PeriodType.DAILY,
            period_start=date,
            period_end=date,
            event_name=event.canonical_name,
            initiating_country=country,
            narrative_summary={
                'overview': summary['overview'],
                'outcomes': summary['outcomes'],
                'source_link': build_hyperlink(doc_ids),  # ← YOUR UTILITY
                'source_count': len(doc_ids)
            },
            ...
        )
        session.add(event_summary)
        session.flush()

        # 5. Store EventSourceLink records for traceability
        for doc_id in doc_ids:
            link = EventSourceLink(
                event_summary_id=event_summary.id,
                doc_id=doc_id,
                contribution_weight=1.0
            )
            session.add(link)

    session.commit()
```

---

## Dashboard Display with Hyperlinks

### **Streamlit Implementation**

```python
def display_monthly_summary(country, month):
    """Display monthly summary with clickable source links."""

    # Get period summary
    period_summary = session.query(PeriodSummary).filter(
        PeriodSummary.period_type == PeriodType.MONTHLY,
        PeriodSummary.initiating_country == country,
        PeriodSummary.period_start >= month_start,
        PeriodSummary.period_end <= month_end
    ).first()

    # Display executive overview
    st.header(f"{country} - {month} Summary")
    st.write(period_summary.overview)

    # Get all monthly event summaries
    event_summaries = session.query(EventSummary).filter(
        EventSummary.period_summary_id == period_summary.id
    ).order_by(EventSummary.total_documents_across_sources.desc()).all()

    # Display each event
    for summary in event_summaries:
        st.subheader(summary.event_name)
        st.write(summary.narrative_summary['overview'])

        # Display outcomes
        st.markdown("**Key Outcomes:**")
        for outcome in summary.narrative_summary['outcomes']:
            st.markdown(f"- {outcome}")

        # Display source link using build_hyperlink
        source_link = summary.narrative_summary.get('source_link')
        source_count = summary.narrative_summary.get('source_count', 0)

        if source_link:
            st.markdown(
                f"📰 **[View All {source_count} Source Articles]({source_link})**",
                unsafe_allow_html=True
            )

        st.markdown("---")
```

### **Example Output**

```
┌────────────────────────────────────────────────────────────┐
│ Iran - August 2024 Summary                                 │
├────────────────────────────────────────────────────────────┤
│                                                             │
│ Executive Overview:                                        │
│ Iran's August activities centered on three main themes...  │
│ [2-3 paragraphs]                                           │
│                                                             │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│                                                             │
│ Arbaeen Pilgrimage Support Services                       │
│                                                             │
│ Iran provided comprehensive support for Arbaeen pilgrims   │
│ throughout August, coordinating with Iraq on border        │
│ management, medical services, and transportation...        │
│                                                             │
│ Key Outcomes:                                              │
│ - Facilitated safe passage for 4.2M pilgrims               │
│ - Deployed 180+ medical teams providing free healthcare    │
│ - Secured multiple public acknowledgments from Iraqi gov   │
│ - Enhanced Iran's soft power image in Iraq                 │
│                                                             │
│ 📰 [View All 89 Source Articles]                          │
│    └─> Opens external page with all articles               │
│                                                             │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│                                                             │
│ Russia-Iran Defense Cooperation                            │
│                                                             │
│ Defense ties deepened significantly with multiple high-    │
│ level meetings, technology transfer agreements...          │
│                                                             │
│ Key Outcomes:                                              │
│ - UAV technology transfer agreement signed                 │
│ - Commitment to joint air defense system development       │
│ - Planned joint naval exercises in Caspian Sea             │
│                                                             │
│ 📰 [View All 67 Source Articles]                          │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

---

## Complete Data Flow with Source Tracking

### **Phase 1: Daily Summaries**

```python
# Input: Master events with doc_ids from daily_event_mentions
master_event = {
    'canonical_name': 'Arbaeen Pilgrimage Support',
    'canonical_event_id': 'uuid-123',
    'date': '2024-08-15'
}

# Get doc_ids for this event on this day
doc_ids = get_doc_ids_from_daily_mentions(
    canonical_event_id='uuid-123',
    date='2024-08-15'
)
# → ['doc001', 'doc002', 'doc003', ..., 'doc089']

# Generate hyperlink
source_link = build_hyperlink(doc_ids)
# → 'https://yourapp.com/articles?ids=doc001,doc002,...,doc089'

# Store in EventSummary
daily_summary = EventSummary(
    period_type=PeriodType.DAILY,
    event_name='Arbaeen Pilgrimage Support',
    narrative_summary={
        'overview': '...',
        'outcomes': [...],
        'source_link': source_link,
        'source_count': 89
    }
)

# Store individual source links for detailed tracking
for doc_id in doc_ids:
    EventSourceLink(
        event_summary_id=daily_summary.id,
        doc_id=doc_id
    )
```

### **Phase 2: Weekly Summaries**

```python
# Aggregate all doc_ids from daily summaries for the week
weekly_doc_ids = set()

for daily_summary in week_daily_summaries:
    # Get all source links for this daily summary
    source_links = session.query(EventSourceLink).filter(
        EventSourceLink.event_summary_id == daily_summary.id
    ).all()

    weekly_doc_ids.update([link.doc_id for link in source_links])

# Generate weekly hyperlink
weekly_source_link = build_hyperlink(list(weekly_doc_ids))

# Store in weekly EventSummary
weekly_summary = EventSummary(
    period_type=PeriodType.WEEKLY,
    narrative_summary={
        'overview': '...',
        'source_link': weekly_source_link,
        'source_count': len(weekly_doc_ids),
        'daily_breakdown': {
            '2024-08-11': {'count': 12, 'link': daily_summaries[0].narrative_summary['source_link']},
            '2024-08-12': {'count': 15, 'link': daily_summaries[1].narrative_summary['source_link']},
            ...
        }
    }
)
```

### **Phase 3: Monthly Summaries**

```python
# Aggregate all doc_ids from weekly summaries
monthly_doc_ids = set()

for weekly_summary in month_weekly_summaries:
    source_links = session.query(EventSourceLink).filter(
        EventSourceLink.event_summary_id == weekly_summary.id
    ).all()

    monthly_doc_ids.update([link.doc_id for link in source_links])

# Generate monthly hyperlink
monthly_source_link = build_hyperlink(list(monthly_doc_ids))

# Store in PeriodSummary
period_summary = PeriodSummary(
    period_type=PeriodType.MONTHLY,
    initiating_country='Iran',
    overview='...',  # LLM-generated executive summary
    outcome='...',   # LLM-generated strategic outcomes
    metrics=json.dumps({
        'total_events': len(event_summaries),
        'total_articles': len(monthly_doc_ids),
        'source_link': monthly_source_link  # ← Master link to all articles
    })
)
```

---

## Database Schema (No Changes Needed!)

Your existing schema is perfect:

```sql
-- Already exists
event_summaries
  ├─ narrative_summary JSONB (add this column)
  │   ├─ overview: str
  │   ├─ outcomes: List[str]
  │   ├─ source_link: str  ← build_hyperlink() output
  │   └─ source_count: int
  └─ ...

event_source_links
  ├─ event_summary_id → event_summaries.id
  ├─ doc_id → documents.doc_id
  └─ contribution_weight

period_summaries
  ├─ overview: str (LLM-generated)
  ├─ outcome: str (LLM-generated)
  └─ metrics: str (JSON with source_link)
```

**Only Addition Needed:**
```sql
ALTER TABLE event_summaries
ADD COLUMN narrative_summary JSONB DEFAULT '{}'::jsonb;
```

---

## Implementation Steps

### **Week 1: Setup**
```bash
# 1. Add narrative_summary column
docker exec api-service python -c "
from shared.database.database import get_engine
from sqlalchemy import text

with get_engine().connect() as conn:
    conn.execute(text('''
        ALTER TABLE event_summaries
        ADD COLUMN narrative_summary JSONB DEFAULT '{}'::jsonb
    '''))
    conn.commit()
print('✅ Added narrative_summary column')
"

# 2. Create directory structure
mkdir -p services/pipeline/summaries

# 3. Create summary scripts
touch services/pipeline/summaries/generate_daily_summaries.py
touch services/pipeline/summaries/generate_weekly_summaries.py
touch services/pipeline/summaries/generate_monthly_summaries.py
touch services/pipeline/summaries/summary_prompts.py
touch services/pipeline/summaries/summary_utils.py
```

### **Week 2: Daily Summaries**
```python
# services/pipeline/summaries/generate_daily_summaries.py

from shared.database.database import get_session
from shared.models.models import EventSummary, EventSourceLink, CanonicalEvent
from shared.utils.utils import build_hyperlink, gai
from summary_prompts import DAILY_SUMMARY_PROMPT

def generate_daily_summaries(country, date):
    with get_session() as session:
        # Get master events active on this day
        active_events = get_active_events(session, country, date)

        for event in active_events[:10]:  # Top 10 by article_count
            # Get doc_ids
            doc_ids = get_event_doc_ids(session, event.id, date)

            # Generate summary
            summary_json = gai(
                sys_prompt="You are a geopolitical analyst...",
                user_prompt=DAILY_SUMMARY_PROMPT.format(
                    event_name=event.canonical_name,
                    doc_ids=doc_ids[:5],  # Sample for LLM
                    ...
                )
            )

            # Create EventSummary
            event_summary = EventSummary(
                period_type=PeriodType.DAILY,
                period_start=date,
                period_end=date,
                event_name=event.canonical_name,
                initiating_country=country,
                narrative_summary={
                    'overview': summary_json['overview'],
                    'outcomes': summary_json['outcomes'],
                    'source_link': build_hyperlink(doc_ids),  # ← YOUR UTILITY
                    'source_count': len(doc_ids)
                }
            )
            session.add(event_summary)
            session.flush()

            # Create EventSourceLink records
            for doc_id in doc_ids:
                link = EventSourceLink(
                    event_summary_id=event_summary.id,
                    doc_id=doc_id,
                    contribution_weight=1.0
                )
                session.add(link)

        session.commit()
```

### **Week 3: Weekly Summaries**
- Aggregate daily summaries
- Generate weekly narratives
- Combine source links

### **Week 4: Monthly Summaries**
- Aggregate weekly summaries
- Generate monthly narratives
- Create PeriodSummary with master source link

### **Week 5: Dashboard**
```python
# services/dashboard/pages/Monthly_Summaries.py

import streamlit as st
from queries.summary_queries import get_monthly_summary

country = st.sidebar.selectbox("Country", ['Iran', 'China', 'Russia', 'Turkey', 'United States'])
month = st.sidebar.date_input("Month")

summary = get_monthly_summary(country, month)

st.header(f"{country} - {month.strftime('%B %Y')}")
st.write(summary['overview'])

# Display events
for event in summary['events']:
    with st.expander(event['name']):
        st.write(event['overview'])
        st.markdown("**Outcomes:**")
        for outcome in event['outcomes']:
            st.markdown(f"- {outcome}")

        # Hyperlink to sources
        st.markdown(
            f"📰 **[View {event['source_count']} Source Articles]({event['source_link']})**"
        )
```

---

## Cost Estimate

Same as original proposal:
- **Daily summaries:** $0.66 (155 summaries)
- **Weekly summaries:** $0.30 (25 summaries)
- **Monthly summaries:** $0.10 (5 summaries)
- **Total: ~$1.06 for August 2024**

---

## Key Advantages

### ✅ **Complete Source Traceability**
- Every summary links back to original articles via `build_hyperlink()`
- Users can verify claims with one click
- Full audit trail from monthly insights to individual documents

### ✅ **Leverages Existing Infrastructure**
- Uses your `build_hyperlink()` utility (no reinvention)
- Uses existing `EventSourceLink` table
- Uses existing master events and daily_event_mentions

### ✅ **Scalable & Maintainable**
- Clean separation: summaries in EventSummary, links in EventSourceLink
- Easy to regenerate summaries without losing source links
- Can add more granular linking (per-outcome sources) later

### ✅ **Professional Output**
- Summaries suitable for briefings/reports
- Clickable source links for verification
- Export to PDF with hyperlinked citations

---

## Next Steps

1. **Confirm `build_hyperlink()` details:**
   - Where is it located?
   - What parameters does it accept?
   - What URL format does it return?

2. **Add narrative_summary column** to event_summaries table

3. **Implement Phase 1** (daily summaries) with source linking

4. **Review sample output** to ensure source links work correctly

5. **Scale to weeks and months**

Ready to start implementation?
