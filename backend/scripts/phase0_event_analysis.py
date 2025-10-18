"""
Phase 0: Statistical Analysis of Raw Events (Production Scale)

Analyzes the distribution of raw events across 400K+ documents to inform
consolidation strategy and set realistic expectations for each phase.
"""

from backend.database import get_session
from sqlalchemy import text
import json
from datetime import datetime
from collections import defaultdict

def analyze_event_distribution():
    """Analyze frequency distribution of raw events"""
    with get_session() as session:
        print("=" * 100)
        print("PHASE 0: STATISTICAL ANALYSIS OF RAW EVENTS")
        print("=" * 100)
        print(f"Analysis started: {datetime.now()}\n")

        # Total statistics
        print("📊 OVERALL STATISTICS")
        print("-" * 100)

        total_docs = session.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        total_events_unique = session.execute(text("SELECT COUNT(DISTINCT event_name) FROM raw_events")).scalar()
        total_relationships = session.execute(text("SELECT COUNT(*) FROM raw_events")).scalar()

        print(f"Total Documents: {total_docs:,}")
        print(f"Unique Event Names: {total_events_unique:,}")
        print(f"Event-Document Relationships: {total_relationships:,}")
        print(f"Average Events per Document: {total_relationships/total_docs:.2f}")
        print(f"Average Documents per Event: {total_relationships/total_events_unique:.2f}\n")

        # Frequency distribution (CRITICAL for strategy)
        print("=" * 100)
        print("📈 FREQUENCY DISTRIBUTION (How many docs per event?)")
        print("-" * 100)

        distribution = session.execute(text("""
            WITH event_counts AS (
                SELECT event_name, COUNT(*) as doc_count
                FROM raw_events
                GROUP BY event_name
            )
            SELECT
                CASE
                    WHEN doc_count = 1 THEN '1. Singleton (1 doc)'
                    WHEN doc_count BETWEEN 2 AND 5 THEN '2. Very Low (2-5 docs)'
                    WHEN doc_count BETWEEN 6 AND 10 THEN '3. Low (6-10 docs)'
                    WHEN doc_count BETWEEN 11 AND 25 THEN '4. Medium-Low (11-25 docs)'
                    WHEN doc_count BETWEEN 26 AND 50 THEN '5. Medium (26-50 docs)'
                    WHEN doc_count BETWEEN 51 AND 100 THEN '6. Medium-High (51-100 docs)'
                    WHEN doc_count BETWEEN 101 AND 250 THEN '7. High (101-250 docs)'
                    WHEN doc_count BETWEEN 251 AND 500 THEN '8. Very High (251-500 docs)'
                    WHEN doc_count > 500 THEN '9. Extreme (500+ docs)'
                END as frequency_bucket,
                COUNT(*) as event_count,
                SUM(doc_count) as total_docs_in_bucket,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct_of_events,
                ROUND(100.0 * SUM(doc_count) / SUM(SUM(doc_count)) OVER (), 2) as pct_of_docs
            FROM event_counts
            GROUP BY frequency_bucket
            ORDER BY MIN(doc_count)
        """)).fetchall()

        cumulative_events = 0
        cumulative_docs = 0
        for bucket, event_count, doc_count, pct_events, pct_docs in distribution:
            cumulative_events += pct_events
            cumulative_docs += pct_docs
            print(f"{bucket:30} | Events: {event_count:>6,} ({pct_events:>5}%) | Docs: {doc_count:>8,} ({pct_docs:>5}%) | Cum: {cumulative_events:>6.1f}% events, {cumulative_docs:>6.1f}% docs")

        # Top events (highest priority for LLM review)
        print("\n" + "=" * 100)
        print("🎯 TOP 100 EVENTS (Tier 1 - MUST consolidate with LLM)")
        print("-" * 100)

        top_events = session.execute(text("""
            SELECT
                event_name,
                COUNT(*) as doc_count,
                COUNT(DISTINCT ic.initiating_country) as country_count,
                MIN(d.date) as first_seen,
                MAX(d.date) as last_seen,
                EXTRACT(DAY FROM MAX(d.date) - MIN(d.date)) as days_span
            FROM raw_events re
            JOIN documents d ON re.doc_id = d.doc_id
            LEFT JOIN initiating_countries ic ON d.doc_id = ic.doc_id
            GROUP BY event_name
            ORDER BY doc_count DESC
            LIMIT 100
        """)).fetchall()

        tier1_total_docs = 0
        for i, (event_name, doc_count, country_count, first, last, span) in enumerate(top_events[:20], 1):
            tier1_total_docs += doc_count
            print(f"{i:3}. {event_name[:70]:70} | {doc_count:>5} docs | {country_count:>2} countries | {span:>4} days")

        print(f"\nTop 100 events cover: {tier1_total_docs:,} documents ({100*tier1_total_docs/total_relationships:.1f}% of all relationships)")

        # Naming pattern analysis
        print("\n" + "=" * 100)
        print("🔍 NAMING PATTERN ANALYSIS (Opportunities for string consolidation)")
        print("-" * 100)

        # Check for common patterns
        patterns = session.execute(text("""
            WITH event_words AS (
                SELECT
                    event_name,
                    regexp_split_to_array(LOWER(event_name), '\s+') as words,
                    COUNT(*) as doc_count
                FROM raw_events
                GROUP BY event_name
            ),
            word_freq AS (
                SELECT
                    unnest(words) as word,
                    COUNT(*) as event_count,
                    SUM(doc_count) as total_docs
                FROM event_words
                GROUP BY word
                HAVING LENGTH(unnest(words)) > 3  -- Skip short words
            )
            SELECT word, event_count, total_docs
            FROM word_freq
            ORDER BY event_count DESC
            LIMIT 50
        """)).fetchall()

        print("Top 50 words in event names (potential pattern markers):\n")
        for word, event_count, total_docs in patterns[:20]:
            print(f"  '{word}': {event_count:>5} events, {total_docs:>7} docs")

        # Check for obvious duplicates (case differences)
        print("\n" + "=" * 100)
        print("🔄 CASE-INSENSITIVE DUPLICATES (Easy wins)")
        print("-" * 100)

        duplicates = session.execute(text("""
            WITH normalized_events AS (
                SELECT
                    LOWER(TRIM(event_name)) as normalized,
                    array_agg(DISTINCT event_name) as variations,
                    SUM(cnt) as total_docs
                FROM (
                    SELECT event_name, COUNT(*) as cnt
                    FROM raw_events
                    GROUP BY event_name
                ) t
                GROUP BY LOWER(TRIM(event_name))
                HAVING COUNT(DISTINCT event_name) > 1
            )
            SELECT
                normalized,
                array_length(variations, 1) as variation_count,
                total_docs,
                variations
            FROM normalized_events
            ORDER BY total_docs DESC
            LIMIT 30
        """)).fetchall()

        if duplicates:
            total_saved = 0
            for normalized, var_count, total_docs, variations in duplicates[:15]:
                total_saved += (var_count - 1)
                print(f"\n'{normalized}' ({total_docs} docs, {var_count} variations):")
                for var in variations[:5]:  # Show first 5 variations
                    print(f"  - {var}")
            print(f"\n💡 Easy reduction: {total_saved:,} events can be merged with simple normalization")

        # Temporal distribution
        print("\n" + "=" * 100)
        print("📅 TEMPORAL DISTRIBUTION (Event lifecycle)")
        print("-" * 100)

        temporal = session.execute(text("""
            WITH event_lifespan AS (
                SELECT
                    event_name,
                    MIN(d.date) as first_seen,
                    MAX(d.date) as last_seen,
                    EXTRACT(DAY FROM MAX(d.date) - MIN(d.date)) as days_span,
                    COUNT(*) as doc_count
                FROM raw_events re
                JOIN documents d ON re.doc_id = d.doc_id
                GROUP BY event_name
            )
            SELECT
                CASE
                    WHEN days_span = 0 THEN '1 day only'
                    WHEN days_span BETWEEN 1 AND 7 THEN '2-7 days'
                    WHEN days_span BETWEEN 8 AND 30 THEN '1 week - 1 month'
                    WHEN days_span BETWEEN 31 AND 90 THEN '1-3 months'
                    WHEN days_span BETWEEN 91 AND 180 THEN '3-6 months'
                    WHEN days_span > 180 THEN '6+ months'
                END as lifespan,
                COUNT(*) as event_count,
                SUM(doc_count) as total_docs,
                ROUND(AVG(doc_count), 1) as avg_docs_per_event
            FROM event_lifespan
            GROUP BY lifespan
            ORDER BY MIN(days_span)
        """)).fetchall()

        for lifespan, event_count, total_docs, avg_docs in temporal:
            print(f"{lifespan:20} | {event_count:>7,} events | {total_docs:>9,} docs | {avg_docs:>6.1f} avg docs/event")

        # Geographic distribution
        print("\n" + "=" * 100)
        print("🌍 GEOGRAPHIC DISTRIBUTION (Events by initiating country)")
        print("-" * 100)

        geo = session.execute(text("""
            SELECT
                ic.initiating_country,
                COUNT(DISTINCT re.event_name) as unique_events,
                COUNT(*) as total_relationships,
                ROUND(AVG(docs_per_event), 1) as avg_docs_per_event
            FROM raw_events re
            JOIN initiating_countries ic ON re.doc_id = ic.doc_id
            JOIN (
                SELECT event_name, COUNT(*) as docs_per_event
                FROM raw_events
                GROUP BY event_name
            ) event_stats ON re.event_name = event_stats.event_name
            GROUP BY ic.initiating_country
            ORDER BY unique_events DESC
        """)).fetchall()

        for country, unique_events, total_rels, avg_docs in geo:
            print(f"{country:25} | {unique_events:>6,} unique events | {total_rels:>8,} relationships | {avg_docs:>6.1f} avg docs/event")

        # Consolidation strategy recommendations
        print("\n" + "=" * 100)
        print("💡 CONSOLIDATION STRATEGY RECOMMENDATIONS")
        print("=" * 100)

        # Calculate expected reductions
        singleton_count = 0
        low_freq_count = 0
        med_freq_count = 0
        high_freq_count = 0

        for bucket, event_count, doc_count, pct_events, pct_docs in distribution:
            if 'Singleton' in bucket:
                singleton_count = event_count
            elif 'Very Low' in bucket or 'Low' in bucket:
                low_freq_count += event_count
            elif 'Medium' in bucket:
                med_freq_count += event_count
            else:
                high_freq_count += event_count

        print(f"""
Phase 1 (String Consolidation):
  - Target: Case normalization, punctuation, pattern matching
  - Expected events: {total_events_unique:,} → {int(total_events_unique * 0.5):,} (50% reduction)
  - Cost: $0 (SQL operations only)
  - Time: ~30-60 minutes

Phase 2 (Semantic Clustering):
  - Target: Reduced event set from Phase 1
  - Sample Strategy:
    • High frequency (100+ docs): {high_freq_count:,} events → EMBED ALL
    • Medium frequency (11-100): {med_freq_count:,} events → SAMPLE 50% = {int(med_freq_count*0.5):,}
    • Low frequency (2-10): {low_freq_count:,} events → SAMPLE 10% = {int(low_freq_count*0.1):,}
    • Singletons: {singleton_count:,} events → SAMPLE 1% = {int(singleton_count*0.01):,}
  - Total embeddings needed: ~{int(high_freq_count + med_freq_count*0.5 + low_freq_count*0.1 + singleton_count*0.01):,}
  - Expected clusters: ~{int(total_events_unique * 0.2):,} (80% reduction from original)
  - Cost: $50-100 (GPU + LLM)
  - Time: ~4-6 hours

Phase 3 (LLM Review):
  - Tier 1 (100+ docs): ~{high_freq_count:,} clusters → LLM cost: ~${high_freq_count * 0.05:.0f}
  - Tier 2 (25-100 docs): Consider based on budget
  - Total LLM cost estimate: ${high_freq_count * 0.05:.0f}-${(high_freq_count + med_freq_count) * 0.05:.0f}

Final Expected Output:
  - Canonical events: ~{int(total_events_unique * 0.25):,} (75% reduction from original)
  - Confidence Tier 1 (LLM verified): ~{int(total_events_unique * 0.05):,}
  - Confidence Tier 2 (High similarity): ~{int(total_events_unique * 0.10):,}
  - Confidence Tier 3 (Auto-merged): ~{int(total_events_unique * 0.10):,}
  - Coverage: {100 - (singleton_count/total_events_unique*100):.1f}% of relationships (excluding rare singletons)
""")

        # Save summary to JSON
        summary = {
            "analysis_date": datetime.now().isoformat(),
            "total_documents": total_docs,
            "unique_event_names": total_events_unique,
            "total_relationships": total_relationships,
            "distribution": [
                {"bucket": bucket, "event_count": event_count, "doc_count": doc_count, "pct_events": float(pct_events), "pct_docs": float(pct_docs)}
                for bucket, event_count, doc_count, pct_events, pct_docs in distribution
            ],
            "top_100_events": [
                {"rank": i+1, "event_name": name, "doc_count": count, "country_count": countries, "days_span": int(span) if span else 0}
                for i, (name, count, countries, first, last, span) in enumerate(top_events)
            ],
            "recommendations": {
                "phase1_expected_reduction": 0.5,
                "phase2_embeddings_needed": int(high_freq_count + med_freq_count*0.5 + low_freq_count*0.1 + singleton_count*0.01),
                "phase3_llm_cost_estimate": f"${high_freq_count * 0.05:.0f}-${(high_freq_count + med_freq_count) * 0.05:.0f}",
                "final_canonical_events_estimate": int(total_events_unique * 0.25)
            }
        }

        with open('event_analysis_summary.json', 'w') as f:
            json.dump(summary, f, indent=2)

        print("\n✅ Analysis complete! Summary saved to event_analysis_summary.json")
        print(f"Analysis finished: {datetime.now()}")

if __name__ == "__main__":
    analyze_event_distribution()
