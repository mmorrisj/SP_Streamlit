"""
Test RAG Data Retrieval Validation

Simulates the query: "What are trending soft power events for this month from China"
Shows exactly what data would be loaded into the prompt.
"""

import sys
from pathlib import Path
import json
from datetime import date, timedelta

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from services.agent.soft_power_agent import SoftPowerAgent
from services.agent.tools.analytics_tools import get_trending_events
from services.agent.query_engine import QueryEngine

print("=" * 80)
print("RAG DATA RETRIEVAL VALIDATION")
print("=" * 80)
print("\nQuery: 'What are trending soft power events for this month from China'\n")

# Step 1: Check what get_trending_events returns
print("\n" + "=" * 80)
print("STEP 1: get_trending_events() Tool Output")
print("=" * 80)

trending_results = get_trending_events(country='China', period_type='daily', limit=10, days=30)
print(f"\nRetrieved {len(trending_results['results'])} trending events")
print("\nFull Tool Output:")
print(json.dumps(trending_results, indent=2, default=str))

if trending_results['results']:
    print("\n--- Event Details ---")
    for i, event in enumerate(trending_results['results'][:5], 1):
        print(f"\n{i}. {event['event_name']}")
        print(f"   Period: {event['period_start']} to {event['period_end']}")
        print(f"   Documents: {event['total_documents']}")
        print(f"   Categories: {', '.join(event.get('categories', []))}")
        print(f"   Recipients: {', '.join(event.get('recipients', []))}")

# Step 2: Test semantic search on event summaries
print("\n" + "=" * 80)
print("STEP 2: QueryEngine.search_event_summaries() Output")
print("=" * 80)

query_engine = QueryEngine()
search_results = query_engine.search_event_summaries(
    query="trending soft power events China",
    period_type='daily',
    country='China',
    limit=5
)

print(f"\nRetrieved {len(search_results)} results from semantic search")
print("\nFull Search Results:")
print(json.dumps(search_results, indent=2, default=str))

if search_results:
    print("\n--- Top Semantic Matches ---")
    for i, result in enumerate(search_results[:3], 1):
        print(f"\n{i}. {result.get('event_name', 'N/A')}")
        print(f"   Relevance Score: {result.get('relevance_score', 0):.4f}")
        print(f"   Period: {result.get('period_start')} to {result.get('period_end')}")
        print(f"   Content Preview: {result.get('content', '')[:200]}...")

# Step 3: Simulate what the agent would send to the LLM
print("\n" + "=" * 80)
print("STEP 3: Data Sent to LLM Prompt")
print("=" * 80)

# This is what would be in tool_results in soft_power_agent.py line 197
simulated_tool_results = {
    'get_trending_events': trending_results,
    'search_events': {'results': search_results}
}

print("\nJSON payload that would be included in LLM prompt:")
print(json.dumps(simulated_tool_results, indent=2, default=str))

# Step 4: Analysis
print("\n" + "=" * 80)
print("STEP 4: VALIDATION ANALYSIS")
print("=" * 80)

# Check date ranges
if trending_results['results']:
    dates = [event['period_start'] for event in trending_results['results']]
    earliest = min(dates)
    latest = max(dates)
    print(f"\n✓ Trending events date range: {earliest} to {latest}")

    # Check if we have November 2025 data
    november_events = [e for e in trending_results['results'] if '2025-11' in e['period_start']]
    october_events = [e for e in trending_results['results'] if '2025-10' in e['period_start']]

    print(f"\n📊 Event Distribution:")
    print(f"   - November 2025 events: {len(november_events)}")
    print(f"   - October 2025 events: {len(october_events)}")

    if len(november_events) == 0:
        print("\n⚠️  WARNING: No November 2025 data found!")
        print("   The agent will respond based on October 2025 data.")
        print("   This is the most recent data available in the database.")
else:
    print("\n❌ ERROR: No trending events found!")

# Check embedding availability
print("\n" + "=" * 80)
print("STEP 5: Embedding Availability Check")
print("=" * 80)

from shared.database.database import get_session
from sqlalchemy import text

with get_session() as session:
    # Check latest embeddings
    latest_embedding = session.execute(text("""
        SELECT
            MAX((cmetadata->>'period_start')::date) as latest_date,
            COUNT(*) as total_embeddings
        FROM langchain_pg_embedding lpe
        JOIN langchain_pg_collection lc ON lpe.collection_id = lc.uuid
        WHERE lc.name = 'daily_event_embeddings'
          AND cmetadata->>'country' = 'China'
    """)).fetchone()

    if latest_embedding:
        print(f"\n✓ Latest event embedding for China: {latest_embedding[0]}")
        print(f"✓ Total China event embeddings: {latest_embedding[1]}")

    # Check data coverage
    coverage = session.execute(text("""
        SELECT
            DATE_TRUNC('month', period_start) as month,
            COUNT(*) as event_count,
            SUM(total_documents_across_sources) as total_docs
        FROM event_summaries
        WHERE initiating_country = 'China'
          AND status = 'ACTIVE'
          AND period_type = 'DAILY'
        GROUP BY DATE_TRUNC('month', period_start)
        ORDER BY month DESC
        LIMIT 3
    """)).fetchall()

    print("\n📅 Recent Data Coverage (Daily Events):")
    for row in coverage:
        print(f"   - {row[0].strftime('%Y-%m')}: {row[1]} events, {row[2]} total documents")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print("""
The RAG system will:
1. Use get_trending_events() to retrieve the top 10 events by document count
2. Use semantic search to find contextually relevant events
3. Send this data to the LLM in JSON format

IMPORTANT NOTE:
- Current data coverage ends at October 14, 2025
- Query for "this month" (December 2025) will return no data
- The agent will need to work with October 2025 data as the most recent
- For accurate "current month" queries, need to run summaries for November-December

RECOMMENDATION:
Update the query to: "What are trending soft power events in October 2025 from China"
Or run summary generation for November-December before testing.
""")

print("\n" + "=" * 80)
