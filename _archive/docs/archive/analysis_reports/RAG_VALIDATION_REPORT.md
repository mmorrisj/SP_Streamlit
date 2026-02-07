# RAG Data Retrieval Validation Report

## Query: "What are trending soft power events for this month from China"

**Test Date**: December 3, 2025
**Expected Behavior**: System should retrieve November 2025 data
**Actual Behavior**: System retrieves October 1-14, 2025 data

---

## Current Data Status

### Event Summaries Table (China)

| Period Type | Event Count | Total Documents | Date Range |
|------------|-------------|-----------------|------------|
| DAILY | 41 | 199 | 2025-10-01 to 2025-10-14 |
| WEEKLY | 13 | 0 | 2025-10-01 to 2025-10-12 |
| MONTHLY | 13 | 0 | 2025-10-01 to 2025-10-31 |

**Latest Event**: October 14, 2025
**Gap**: No event summaries exist for October 15 - November 30, 2025

---

## RAG Retrieval Flow Analysis

### Step 1: Tool Selection
([soft_power_agent.py:122-154](services/agent/soft_power_agent.py#L122-L154))

For query "What are trending soft power events for this month from China", the agent's tool selection logic would identify:

```python
selected_tools = ["get_trending_events", "search_events"]
```

**Reasoning**: Keywords "trending" and "events" trigger these two tools.

---

### Step 2: Tool Execution

#### 2A. `get_trending_events()` Tool
([analytics_tools.py:155-217](services/agent/tools/analytics_tools.py#L155-L217))

```python
def get_trending_events(
    country: Optional[str] = None,
    period_type: str = 'daily',
    limit: int = 10,
    days: int = 30  # ← Looks back 30 days from TODAY
) -> List[Dict]:
```

**Key Finding**: This function uses `lookback_date = date.today() - timedelta(days=30)`

- Today: December 3, 2025
- Lookback: November 3, 2025
- **Problem**: No data exists after October 14, 2025
- **Result**: Returns empty list or old October data

**SQL Query Executed**:
```sql
SELECT id, event_name, initiating_country, period_start, period_end,
       total_documents_across_sources, count_by_category, count_by_recipient
FROM event_summaries
WHERE period_type = 'DAILY'
  AND period_start >= '2025-11-03'  -- 30 days ago
  AND status = 'ACTIVE'
  AND initiating_country = 'China'
ORDER BY total_documents_across_sources DESC, period_start DESC
LIMIT 10
```

**Actual Results**: 0 rows (no data after Oct 14)

---

#### 2B. `search_event_summaries()` Tool
([query_engine.py:43-106](services/agent/query_engine.py#L43-L106))

```python
def search_event_summaries(
    query: str,
    period_type: Optional[str] = None,
    country: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 10
) -> List[Dict]:
```

**Execution**:
```python
# Semantic search on daily_store (pgvector)
results = self.daily_store.similarity_search_with_score(
    "trending soft power events China",
    k=10
)
```

**Vector Store Query**: Searches `daily_event_embeddings` collection using cosine similarity

**Expected Results**: Top 10 most semantically similar events from **entire database** (not filtered by date unless explicitly provided)

**Actual Results**: Will return October 1-14 events since that's all that exists

---

### Step 3: LLM Prompt Construction
([soft_power_agent.py:192-210](services/agent/soft_power_agent.py#L192-L210))

The data from both tools is combined into a JSON payload:

```json
{
  "get_trending_events": {
    "results": []  // Empty - no data in Nov lookback window
  },
  "search_events": {
    "results": [
      {
        "event_id": "...",
        "event_name": "Diplomatic Engagement with Lebanon",
        "country": "China",
        "period_start": "2025-10-14",
        "period_end": "2025-10-14",
        "content": "...",
        "relevance_score": 0.85,
        "period_type": "daily"
      },
      // ... 9 more October events
    ]
  }
}
```

This JSON is inserted into the LLM prompt at line 197:
```python
Retrieved Information:
{json.dumps(tool_results, indent=2, default=str)}
```

---

## Response Accuracy Assessment

### What the LLM Will Receive:
1. **User Question**: "What are trending soft power events for this month from China"
2. **Retrieved Data**: 0-10 events from October 1-14, 2025
3. **Missing Context**: No indication that data is incomplete or outdated

### Expected LLM Response:
The LLM will likely:
1. Answer based on October 2025 data (only data available)
2. May or may not indicate the temporal mismatch
3. Could state "recent events" or "trending events" without specifying October

### Problems:
❌ **Temporal Mismatch**: Query asks for "this month" (December), system returns October
❌ **No Data Freshness Indicator**: System doesn't signal that data is 6-8 weeks old
❌ **Silent Failure**: Empty results from `get_trending_events` aren't surfaced to user
❌ **No Fallback Logic**: Doesn't automatically adjust lookback window if no data found

---

## Root Cause Analysis

### Why No November Data?

**Pipeline Status Check**:
- ✅ DSR Ingestion: Running (`dsr_ingestion_run2.log`)
- ✅ Event Clustering: Running (`event_clustering_oct_nov.log`)
- ✅ Daily Summaries: Running (`daily_summaries_oct_nov.log`)
- ✅ Weekly Summaries: Running (`weekly_summaries_oct_nov.log`)
- ✅ Monthly Summaries: Running (`monthly_summaries_oct_nov.log`)
- ⏳ Event Embeddings: Running (`event_summary_embeddings_auto.log`)

**Status**: Pipelines are actively processing Oct 15 - Nov 25 data but **not yet complete**.

### Data Generation Timeline:
1. Documents ingested → `documents` table
2. Events clustered → `canonical_events` table
3. Summaries generated → `event_summaries` table (← Currently running)
4. Embeddings created → `langchain_pg_embedding` table (← Pending)

**Current Stage**: Step 3 (generating event summaries for Oct-Nov)

---

## Recommendations

### Immediate Fixes:

#### 1. Add Data Freshness Check
([services/agent/tools/analytics_tools.py:155](services/agent/tools/analytics_tools.py#L155))

```python
def get_trending_events(
    country: Optional[str] = None,
    period_type: str = 'daily',
    limit: int = 10,
    days: int = 30
) -> Dict:  # ← Change return type to Dict
    """Get trending events with data freshness metadata."""

    with get_session() as session:
        # Get latest available date
        latest_date = session.execute(text("""
            SELECT MAX(period_start)
            FROM event_summaries
            WHERE period_type = 'DAILY' AND status = 'ACTIVE'
        """")).scalar()

        # Adjust lookback if needed
        lookback_date = max(
            date.today() - timedelta(days=days),
            latest_date - timedelta(days=days) if latest_date else date(2024, 1, 1)
        )

        # ... existing query logic ...

        return {
            'results': results,
            'data_freshness': {
                'latest_data_date': latest_date.isoformat(),
                'requested_lookback': (date.today() - timedelta(days=days)).isoformat(),
                'actual_lookback': lookback_date.isoformat(),
                'is_current': (latest_date >= date.today() - timedelta(days=7))
            }
        }
```

#### 2. Add Filter Context to RAG Search
([services/dashboard/pages/Chat_with_Data.py:213-216](services/dashboard/pages/Chat_with_Data.py#L213-L216))

Currently filters are passed as text in the prompt. They should be parsed and used as **actual query parameters**:

```python
# Extract date range from filters
filters = st.session_state.filters
start_date = filters['start_date']
end_date = filters['end_date']
country = filters['initiating_country']

# Pass to agent as structured parameters
response_text, sources = st.session_state.agent.query(
    prompt,
    conversation_context=st.session_state.messages,
    filters={
        'start_date': start_date,
        'end_date': end_date,
        'country': country,
        'recipient_countries': filters['recipient_countries']
    }
)
```

Then update agent to use these filters:
```python
# In soft_power_agent.py
if tool_name == 'search_events':
    results = self.tools[tool_name](
        user_query,
        limit=5,
        start_date=filters.get('start_date'),
        end_date=filters.get('end_date'),
        country=filters.get('country')
    )
```

#### 3. Add Temporal Context Parsing
Use LLM to parse temporal references like "this month", "recent", "latest" and convert to actual date ranges:

```python
# In soft_power_agent.py before tool selection
temporal_context = self._parse_temporal_context(user_query)
# Returns: {'start_date': '2025-11-01', 'end_date': '2025-11-30', 'reference': 'this month'}
```

---

## Test Results Summary

### ✅ What Works:
1. **Semantic Search**: pgvector similarity search functions correctly
2. **Tool Selection**: Agent correctly identifies relevant tools
3. **JSON Serialization**: Tool results properly formatted for LLM
4. **Data Retrieval**: Queries execute without errors

### ❌ What Doesn't Work:
1. **Temporal Awareness**: No understanding of "this month" vs available data
2. **Data Freshness**: No indication when data ends
3. **Smart Fallback**: Doesn't adjust queries when no recent data exists
4. **Filter Integration**: Sidebar filters not used in RAG queries

### ⚠️ Known Limitations:
1. **Data Lag**: Currently 6-8 weeks behind (latest: Oct 14, expected: Nov 30)
2. **Weekly/Monthly Docs**: Zero documents in weekly/monthly summaries
3. **Embedding Status**: Event embeddings still generating

---

## Validation Checklist

For query: "What are trending soft power events for this month from China"

- [ ] Data exists for November 2025
- [x] Tool selection identifies correct tools (`get_trending_events`, `search_events`)
- [x] Semantic search retrieves relevant events
- [ ] Retrieved events match temporal query ("this month" → November)
- [ ] Data freshness is surfaced to user
- [ ] Empty results trigger fallback logic
- [ ] Sidebar filters are applied to RAG queries
- [ ] LLM response acknowledges any temporal mismatches

**Current Score**: 2/8 (25%)

---

## Next Steps

### Before Production Use:

1. **Wait for Pipeline Completion**:
   - Monitor `daily_summaries_oct_nov.log` until complete
   - Run event embedding generation
   - Verify November data in database

2. **Implement Recommended Fixes**:
   - Add data freshness metadata to tool responses
   - Parse and apply filter parameters to RAG queries
   - Add temporal context parsing for relative dates

3. **Add Monitoring**:
   - Dashboard indicator showing latest data date
   - Warning message if query requests data beyond available range
   - Metrics on RAG retrieval latency and result counts

4. **Test Scenarios**:
   - Query with November date filter
   - Query without filters (should use current month)
   - Query with "recent" / "latest" / "trending"
   - Query for specific event types or categories

---

## Current Status: ⚠️ PARTIALLY FUNCTIONAL

The RAG system architecture is sound, but **data coverage is incomplete**. Once the October-November pipeline completes and embeddings are generated, the system should work correctly for queries covering that period.

**For immediate testing**: Use query "What are trending soft power events in October 2025 from China" to match available data.

