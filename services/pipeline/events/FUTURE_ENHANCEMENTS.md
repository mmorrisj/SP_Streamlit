# Future Enhancements for Event Processing Pipeline

## 1. Retrieval-Based Historical Context

**Goal:** Improve temporal event linking by providing LLM with relevant historical context from previously processed events.

**Current Limitation:**
- Daily clustering only sees events from a single day
- No awareness of similar events from previous days/weeks/months
- Cannot easily link "China announces Belt and Road Forum" (Aug 1) with "Belt and Road Forum begins" (Aug 25)

**Proposed Solution:**

### Approach 1: Vector Similarity Search
```python
def get_historical_context(event_name: str, country: str, target_date: date, lookback_days: int = 90):
    """
    Retrieve similar historical events using vector similarity.

    Args:
        event_name: Current event name to match
        country: Initiating country
        target_date: Current date
        lookback_days: How far back to search (default 90 days)

    Returns:
        List of similar canonical events from the past
    """
    # Generate embedding for current event
    embedding = embedding_model.encode(event_name)

    # Query canonical_events using pgvector cosine similarity
    query = """
        SELECT
            canonical_name,
            first_mention_date,
            last_mention_date,
            story_phase,
            total_mention_days,
            embedding_vector <=> :embedding as similarity
        FROM canonical_events
        WHERE initiating_country = :country
          AND last_mention_date >= :cutoff_date
          AND last_mention_date < :target_date
        ORDER BY embedding_vector <=> :embedding
        LIMIT 5
    """

    cutoff_date = target_date - timedelta(days=lookback_days)

    results = session.execute(query, {
        'embedding': embedding,
        'country': country,
        'cutoff_date': cutoff_date,
        'target_date': target_date
    })

    return results.fetchall()
```

### Approach 2: Enhanced LLM Prompt with Context
```python
HISTORICAL_CONTEXT_PROMPT = """
**HISTORICAL CONTEXT (Past 90 days):**

We've previously tracked these related events for {country}:

{historical_events}

**TODAY'S EVENTS ({target_date}):**
{current_events}

**TASK:**
1. Determine if any of today's events are continuations of historical events
2. Group today's events that refer to the same underlying event
3. Note which historical events (if any) are being continued

**OUTPUT:**
{{
    "groups": [[1,2,3], [4,5]],
    "historical_links": [
        {{"current_group": [1,2,3], "historical_event": "Belt and Road Forum", "relationship": "continuation"}},
        {{"current_group": [4,5], "historical_event": null, "relationship": "new_event"}}
    ]
}}
"""
```

### Implementation Timeline
- **Phase 1** (Current): Build up August-December 2024 data using current approach
- **Phase 2** (Q1 2025): Implement vector similarity search for historical context
- **Phase 3** (Q2 2025): Integrate historical context into LLM deconfliction prompt
- **Phase 4** (Q2 2025): Build temporal consolidation script that creates master_events

### Data Requirements
- Minimum 3 months of processed data before historical context becomes useful
- Current data: August 2024 onwards
- Ready for Phase 2: November 2024 onwards (3+ months of history)

## 2. Automated Stage Detection

**Goal:** Automatically classify events by lifecycle stage (announcement, preparation, execution, aftermath)

**Implementation:**
```python
STAGE_KEYWORDS = {
    'announcement': ['announces', 'will', 'plans to', 'scheduled', 'upcoming'],
    'preparation': ['preparing', 'ahead of', 'in preparation', 'getting ready'],
    'execution': ['begins', 'started', 'opened', 'launched', 'underway'],
    'continuation': ['ongoing', 'continues', 'still', 'progressing'],
    'aftermath': ['concluded', 'ended', 'resulted in', 'outcome', 'achieved']
}

def detect_stage(event_name: str) -> str:
    """Classify event by lifecycle stage based on keywords."""
    event_lower = event_name.lower()

    for stage, keywords in STAGE_KEYWORDS.items():
        if any(keyword in event_lower for keyword in keywords):
            return stage

    return 'general'
```

## 3. Event Timeline Visualization

**Goal:** Dashboard page showing event evolution over time

**Features:**
- Timeline view showing announcement → preparation → execution → aftermath
- Heatmap of event intensity by day
- Story arc visualization (coverage patterns)
- Source diversity over time

## 4. Confidence-Based Manual Review Queue

**Goal:** Surface low-confidence LLM decisions for manual review

**Implementation:**
- Track confidence scores from LLM responses
- Create review queue for confidence < 0.80
- Dashboard page for manual event linking/splitting
- Learn from manual reviews to improve prompts

## 5. Multi-Country Event Linking

**Goal:** Link related events across different initiating countries

**Example:**
- China-Egypt bilateral meeting (China as initiator)
- Egypt-China bilateral meeting (Egypt as initiator)
→ Should be linked as same event from different perspectives

**Challenge:**
- Current pipeline processes each country independently
- Need cross-country deduplication step

## 6. Project/Initiative Tracking

**Goal:** Link events to long-term initiatives (Belt and Road, BRICS, etc.)

**Implementation:**
- Extract project/initiative names from events
- Create `initiatives` table
- Link events to initiatives via junction table
- Track initiative evolution over time

---

**Last Updated:** 2025-10-23
**Data Range:** August 2024 onwards
**Current Pipeline:** Daily clustering → LLM deconfliction → (temporal consolidation pending)
