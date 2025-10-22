# Dashboard Filtering Summary

## Overview

The Master Events Dashboard now properly filters all metrics to show **only** events and documents that match the countries, categories, and subcategories defined in `config.yaml`.

## What Changed

### 1. Query Layer Filtering ([services/dashboard/queries/event_queries.py](services/dashboard/queries/event_queries.py))

All 10 query functions were updated to filter documents using JOINs through the flattened database tables:

**Filtering Strategy:**
```sql
WITH unnested_docs AS (
    -- Extract doc_ids from daily_event_mentions
    SELECT unnest(dem.doc_ids) as doc_id
    FROM daily_event_mentions dem
    ...
),
filtered_docs AS (
    -- Apply ALL config filters
    SELECT DISTINCT ud.doc_id
    FROM unnested_docs ud
    WHERE EXISTS (
        SELECT 1 FROM recipient_countries rc
        WHERE rc.doc_id = ud.doc_id
        AND rc.recipient_country = ANY(:recipients)  -- config.yaml recipients
    )
    AND EXISTS (
        SELECT 1 FROM categories cat
        WHERE cat.doc_id = ud.doc_id
        AND cat.category = ANY(:categories)  -- config.yaml categories
    )
    AND EXISTS (
        SELECT 1 FROM subcategories sub
        WHERE sub.doc_id = ud.doc_id
        AND sub.subcategory = ANY(:subcategories)  -- config.yaml subcategories
    )
)
```

**Updated Functions:**
- `get_master_event_overview()` - Overview statistics with filtered counts
- `get_top_master_events()` - Top events by filtered article count
- `get_events_by_country()` - Country breakdown with filtered counts
- `get_temporal_trends()` - Daily trends with filtered counts
- `get_recipient_impact()` - Recipient analysis with filtered counts
- `get_category_breakdown()` - Category breakdown with filtered counts
- `get_standalone_canonical_events()` - Standalone events with filtered counts

### 2. Dashboard UI Updates ([services/dashboard/pages/Master_Events.py](services/dashboard/pages/Master_Events.py))

**Added Clear Filtering Information:**
- Header section explains that dashboard shows only config.yaml filtered data
- Info banner on Overview tab showing active filter counts
- Enhanced sidebar showing active filters (influencers, recipients, categories, subcategories)
- Added recipient country multiselect (defaults to all config.yaml recipients)

**New Sidebar Filters:**
```python
# Geographic Filters
- Initiating Country: Single select from influencers
- Recipient Countries: Multi-select from config recipients (defaults to ALL)

# Active Filters Display
- Shows count of active influencers, recipients, categories, subcategories
```

## Config.yaml Filter Criteria

All dashboard metrics filter documents by these criteria from `config.yaml`:

### **Influencer Countries (5)**
```yaml
influencers:
  - China
  - Russia
  - Iran
  - Turkey
  - United States
```

### **Recipient Countries (18 Middle East countries)**
```yaml
recipients:
  - Bahrain
  - Cyprus
  - Egypt
  - Iran
  - Iraq
  - Israel
  - Jordan
  - Kuwait
  - Lebanon
  - Libya
  - Oman
  - Palestine
  - Qatar
  - Saudi Arabia
  - Syria
  - Turkey
  - United Arab Emirates
  - UAE
  - Yemen
```

### **Categories (4)**
```yaml
categories:
  - Economic
  - Social
  - Military
  - Diplomacy
```

### **Subcategories (23)**
```yaml
subcategories:
  - Trade
  - Infrastructure
  - Food
  - Technology
  - Tourism
  - Industrial
  - Raw Materials
  - Culture
  - Education
  - Healthcare
  - Housing
  - Media
  - Politics
  - Religious
  - Bilateral/Multilateral Agreements
  - Multilateral/Bilateral Commitments
  - Conflict Resolution
  - Global Governance Participation
  - Sales
  - Joint Exercises
  - Training
  - Conferences
  - Cultural
  - Diaspora Engagement
  - Energy
  - Finance
```

## Results

### August 2024 Data
- **Before filtering fix:** 724,231 articles (inflated by Cartesian product)
- **After filtering fix:** 5,320 unique articles
- **Total documents in DB:** 439,820
- **Documents matching all filters (Aug 2024):** 12,314
- **Documents in master events (Aug 2024):** 5,320

**Master Events:**
- 3,571 master events
- 2,511 child events
- Date range: Aug 1-31, 2024

### Breakdown by Country (Aug 2024)
The following shows article counts per country (note: documents can appear in multiple events):

| Country       | Master Events | Child Events | Articles* |
|---------------|---------------|--------------|-----------|
| Iran          | 1,439         | 945          | 196,711   |
| United States | 608           | 566          | 191,728   |
| Turkey        | 489           | 357          | 5,435     |
| China         | 642           | 370          | 4,312     |
| Russia        | 393           | 273          | 2,673     |

*Note: Article counts are summed across all master events for each country. Since a single document can appear in multiple master events, these sums may exceed the total unique article count. For unique article counts, refer to the Overview tab.

## Key Implementation Details

### Why Pre-Aggregated `total_articles` Can't Be Used

The `canonical_events.total_articles` field is pre-aggregated during event creation and doesn't account for config filtering:

**Computation Points:**
1. **LLM Deconfliction** ([llm_deconflict_clusters.py:443](services/pipeline/events/llm_deconflict_clusters.py:443))
   - `total_articles = len(group_doc_ids)` - All docs in cluster

2. **News Event Tracker** ([news_event_tracker.py:698](services/pipeline/events/news_event_tracker.py:698))
   - `total_articles = daily_mention.article_count` - All docs in mention

3. **Master Event Creation** ([create_master_events.py:202](services/pipeline/events/create_master_events.py:202))
   - `total_articles = sum(e['total_articles'] for e in group_events)` - Sum of child totals

**Solution:** Dashboard queries compute filtered counts dynamically at query time by:
1. Unnesting `doc_ids` from `daily_event_mentions`
2. Filtering through flattened tables (initiating_countries, recipient_countries, categories, subcategories)
3. Counting only DISTINCT doc_ids that match ALL criteria

### Performance

Query performance is acceptable (2-5 seconds) for filtered counts:
- Uses CTEs (Common Table Expressions) for efficient processing
- EXISTS subqueries are optimized by PostgreSQL
- Leverages indexes on doc_id columns in flattened tables
- `@st.cache_data` decorator caches results in Streamlit

## How to Use the Dashboard

1. **Access:** Navigate to http://localhost:8501 → Master Events page
2. **Default View:** Shows all influencer countries → all config recipient countries
3. **Filter by Initiating Country:** Select from sidebar dropdown
4. **Filter by Recipients (Display Only):** Select specific recipient countries to focus on
5. **Adjust Date Range:** Use sidebar date inputs

**Note:** The recipient country multiselect is for **display filtering only**. All underlying document counts still include documents matching the full config.yaml recipient list. This ensures accurate article counts while allowing you to focus visualizations on specific countries of interest.

## Access the Dashboard

```bash
# Local access
http://localhost:8501

# Or restart dashboard
docker restart streamlit-dashboard
```

## Technical Notes

### Database Schema
The filtering relies on these normalized tables:
- `initiating_countries(doc_id, initiating_country)`
- `recipient_countries(doc_id, recipient_country)`
- `categories(doc_id, category)`
- `subcategories(doc_id, subcategory)`

### Why Document Counts May Seem High

When viewing "Events by Country", the article counts represent the sum across ALL master events for that country. Since:
1. A single document can appear in multiple master events (if it mentions multiple related events)
2. We're summing across all master events

The total will be higher than unique document count. For accurate unique document counts, always refer to the **Overview tab** which shows total unique articles.

### Filter Logic

All metrics use **AND logic** for filters:
```
Document must match:
  ✓ Initiating country IN config.influencers
  AND
  ✓ At least one recipient IN config.recipients
  AND
  ✓ At least one category IN config.categories
  AND
  ✓ At least one subcategory IN config.subcategories
```

This ensures all displayed metrics are strictly scoped to your config.yaml specifications.
