"""
Diagnostic script to check canonical events status.
Helps debug why score_canonical_event_materiality.py finds no events to score.

Usage:
    python diagnose_canonical_events.py --country China
    python diagnose_canonical_events.py --influencers
"""

import argparse
import sys
from sqlalchemy import text
from shared.database.database import get_session


def diagnose_canonical_events(country: str = None):
    """
    Run diagnostic queries to understand canonical events state.

    Args:
        country: Optional country filter. If None, shows all countries.
    """
    print("\n" + "="*80)
    print("CANONICAL EVENTS DIAGNOSTIC REPORT")
    if country:
        print(f"Country: {country}")
    else:
        print("Country: ALL")
    print("="*80 + "\n")

    with get_session() as session:
        # Query 1: Total canonical events
        if country:
            query1 = text("""
                SELECT COUNT(*) as total_events
                FROM canonical_events
                WHERE initiating_country = :country
            """)
            result1 = session.execute(query1, {'country': country}).fetchone()
        else:
            query1 = text("""
                SELECT COUNT(*) as total_events
                FROM canonical_events
            """)
            result1 = session.execute(query1).fetchone()

        print(f"1. Total Canonical Events: {result1[0]}")

        # Query 2: Master vs Child events
        if country:
            query2 = text("""
                SELECT
                    COUNT(CASE WHEN master_event_id IS NULL THEN 1 END) as master_events,
                    COUNT(CASE WHEN master_event_id IS NOT NULL THEN 1 END) as child_events
                FROM canonical_events
                WHERE initiating_country = :country
            """)
            result2 = session.execute(query2, {'country': country}).fetchone()
        else:
            query2 = text("""
                SELECT
                    COUNT(CASE WHEN master_event_id IS NULL THEN 1 END) as master_events,
                    COUNT(CASE WHEN master_event_id IS NOT NULL THEN 1 END) as child_events
                FROM canonical_events
            """)
            result2 = session.execute(query2).fetchone()

        print(f"   - Master Events (master_event_id IS NULL): {result2[0]}")
        print(f"   - Child Events (master_event_id IS NOT NULL): {result2[1]}")

        # Query 3: Materiality scoring status
        if country:
            query3 = text("""
                SELECT
                    COUNT(CASE WHEN material_score IS NULL THEN 1 END) as unscored,
                    COUNT(CASE WHEN material_score IS NOT NULL THEN 1 END) as scored,
                    ROUND(AVG(material_score), 2) as avg_score,
                    MIN(material_score) as min_score,
                    MAX(material_score) as max_score
                FROM canonical_events
                WHERE initiating_country = :country
                  AND master_event_id IS NULL
            """)
            result3 = session.execute(query3, {'country': country}).fetchone()
        else:
            query3 = text("""
                SELECT
                    COUNT(CASE WHEN material_score IS NULL THEN 1 END) as unscored,
                    COUNT(CASE WHEN material_score IS NOT NULL THEN 1 END) as scored,
                    ROUND(AVG(material_score), 2) as avg_score,
                    MIN(material_score) as min_score,
                    MAX(material_score) as max_score
                FROM canonical_events
                WHERE master_event_id IS NULL
            """)
            result3 = session.execute(query3).fetchone()

        print(f"\n2. Materiality Scoring Status (Master Events Only):")
        print(f"   - Unscored (material_score IS NULL): {result3[0]}")
        print(f"   - Scored (material_score IS NOT NULL): {result3[1]}")
        if result3[2]:
            print(f"   - Average Score: {result3[2]}")
            print(f"   - Score Range: {result3[3]} - {result3[4]}")

        # Query 4: Article count distribution for master events
        if country:
            query4 = text("""
                SELECT
                    COUNT(CASE WHEN total_articles IS NULL THEN 1 END) as null_articles,
                    COUNT(CASE WHEN total_articles < 2 THEN 1 END) as under_2,
                    COUNT(CASE WHEN total_articles >= 2 AND total_articles < 5 THEN 1 END) as between_2_5,
                    COUNT(CASE WHEN total_articles >= 5 AND total_articles < 10 THEN 1 END) as between_5_10,
                    COUNT(CASE WHEN total_articles >= 10 THEN 1 END) as over_10,
                    ROUND(AVG(total_articles), 2) as avg_articles,
                    MAX(total_articles) as max_articles
                FROM canonical_events
                WHERE initiating_country = :country
                  AND master_event_id IS NULL
            """)
            result4 = session.execute(query4, {'country': country}).fetchone()
        else:
            query4 = text("""
                SELECT
                    COUNT(CASE WHEN total_articles IS NULL THEN 1 END) as null_articles,
                    COUNT(CASE WHEN total_articles < 2 THEN 1 END) as under_2,
                    COUNT(CASE WHEN total_articles >= 2 AND total_articles < 5 THEN 1 END) as between_2_5,
                    COUNT(CASE WHEN total_articles >= 5 AND total_articles < 10 THEN 1 END) as between_5_10,
                    COUNT(CASE WHEN total_articles >= 10 THEN 1 END) as over_10,
                    ROUND(AVG(total_articles), 2) as avg_articles,
                    MAX(total_articles) as max_articles
                FROM canonical_events
                WHERE master_event_id IS NULL
            """)
            result4 = session.execute(query4).fetchone()

        print(f"\n3. Article Count Distribution (Master Events Only):")
        print(f"   - NULL articles: {result4[0]}")
        print(f"   - Under 2 articles: {result4[1]}")
        print(f"   - 2-4 articles: {result4[2]}")
        print(f"   - 5-9 articles: {result4[3]}")
        print(f"   - 10+ articles: {result4[4]}")
        if result4[5]:
            print(f"   - Average articles: {result4[5]}")
            print(f"   - Max articles: {result4[6]}")

        # Query 5: Events meeting scoring criteria
        print(f"\n4. Events Meeting Scoring Criteria:")

        criteria = [
            (1, 1, "min_days=1, min_articles=1"),
            (1, 2, "min_days=1, min_articles=2"),
            (1, 5, "min_days=1, min_articles=5"),
            (2, 5, "min_days=2, min_articles=5"),
            (3, 10, "min_days=3, min_articles=10"),
        ]

        for min_days, min_articles, label in criteria:
            if country:
                query5 = text("""
                    SELECT COUNT(*) as eligible_events
                    FROM canonical_events
                    WHERE initiating_country = :country
                      AND master_event_id IS NULL
                      AND material_score IS NULL
                      AND total_mention_days >= :min_days
                      AND total_articles >= :min_articles
                """)
                result5 = session.execute(query5, {
                    'country': country,
                    'min_days': min_days,
                    'min_articles': min_articles
                }).fetchone()
            else:
                query5 = text("""
                    SELECT COUNT(*) as eligible_events
                    FROM canonical_events
                    WHERE master_event_id IS NULL
                      AND material_score IS NULL
                      AND total_mention_days >= :min_days
                      AND total_articles >= :min_articles
                """)
                result5 = session.execute(query5, {
                    'min_days': min_days,
                    'min_articles': min_articles
                }).fetchone()

            print(f"   - {label}: {result5[0]} events")

        # Query 6: LLM validation status
        if country:
            query6 = text("""
                SELECT
                    COUNT(CASE WHEN llm_validated IS NULL THEN 1 END) as null_validation,
                    COUNT(CASE WHEN llm_validated = TRUE THEN 1 END) as validated,
                    COUNT(CASE WHEN llm_validated = FALSE THEN 1 END) as not_validated
                FROM canonical_events
                WHERE initiating_country = :country
                  AND master_event_id IS NULL
            """)
            result6 = session.execute(query6, {'country': country}).fetchone()
        else:
            query6 = text("""
                SELECT
                    COUNT(CASE WHEN llm_validated IS NULL THEN 1 END) as null_validation,
                    COUNT(CASE WHEN llm_validated = TRUE THEN 1 END) as validated,
                    COUNT(CASE WHEN llm_validated = FALSE THEN 1 END) as not_validated
                FROM canonical_events
                WHERE master_event_id IS NULL
            """)
            result6 = session.execute(query6).fetchone()

        print(f"\n5. LLM Validation Status (Master Events Only):")
        print(f"   - NULL (not processed): {result6[0]}")
        print(f"   - TRUE (validated): {result6[1]}")
        print(f"   - FALSE (rejected): {result6[2]}")

        # Query 7: Sample of unscored events
        print(f"\n6. Sample Unscored Events (with article counts):")
        if country:
            query7 = text("""
                SELECT
                    canonical_name,
                    total_articles,
                    total_mention_days,
                    first_mention_date,
                    last_mention_date
                FROM canonical_events
                WHERE initiating_country = :country
                  AND master_event_id IS NULL
                  AND material_score IS NULL
                ORDER BY total_articles DESC NULLS LAST
                LIMIT 10
            """)
            result7 = session.execute(query7, {'country': country}).fetchall()
        else:
            query7 = text("""
                SELECT
                    canonical_name,
                    initiating_country,
                    total_articles,
                    total_mention_days,
                    first_mention_date,
                    last_mention_date
                FROM canonical_events
                WHERE master_event_id IS NULL
                  AND material_score IS NULL
                ORDER BY total_articles DESC NULLS LAST
                LIMIT 10
            """)
            result7 = session.execute(query7).fetchall()

        if result7:
            for row in result7:
                if country:
                    print(f"   - {row[0][:80]}")
                    print(f"     Articles: {row[1]}, Days: {row[2]}, Period: {row[3]} to {row[4]}")
                else:
                    print(f"   - [{row[1]}] {row[0][:70]}")
                    print(f"     Articles: {row[2]}, Days: {row[3]}, Period: {row[4]} to {row[5]}")
        else:
            print("   - No unscored events found")

        # Query 8: Country breakdown
        if not country:
            print(f"\n7. Country Breakdown (Master Events):")
            query8 = text("""
                SELECT
                    initiating_country,
                    COUNT(*) as total_events,
                    COUNT(CASE WHEN material_score IS NULL THEN 1 END) as unscored,
                    COUNT(CASE WHEN material_score IS NOT NULL THEN 1 END) as scored
                FROM canonical_events
                WHERE master_event_id IS NULL
                GROUP BY initiating_country
                ORDER BY total_events DESC
            """)
            result8 = session.execute(query8).fetchall()

            for row in result8:
                print(f"   - {row[0]}: {row[1]} total ({row[2]} unscored, {row[3]} scored)")

        print("\n" + "="*80)
        print("RECOMMENDATIONS:")
        print("="*80)

        if result1[0] == 0:
            print("\n❌ No canonical events found in database!")
            print("   Run the event processing pipeline first:")
            print("   1. batch_cluster_events.py")
            print("   2. llm_deconflict_clusters.py")
            print("   3. consolidate_all_events.py")
            print("   4. llm_deconflict_canonical_events.py")
            print("   5. merge_canonical_events.py")
        elif result2[0] == 0:
            print("\n❌ No master events found (all events have master_event_id set)!")
            print("   This suggests the consolidation pipeline may not have completed.")
            print("   Run: llm_deconflict_canonical_events.py and merge_canonical_events.py")
        elif result3[0] == 0:
            print("\n✅ All master events have been scored!")
            print("   Use --rescore flag to re-score events")
        elif result4[0] > 0 or (result4[5] and result4[5] < 5):
            print("\n⚠️  Many events have NULL or low article counts!")
            print("   This suggests total_articles field may not be populated correctly.")
            print("   Check if merge_canonical_events.py completed successfully.")
        else:
            print("\n✅ Database looks healthy. Events should be scorable.")
            print("   Try running with lower thresholds:")
            print("   --min-articles 1 --min-days 1")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose canonical events to debug materiality scoring issues"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--country', type=str, help='Single country to diagnose')
    group.add_argument('--influencers', action='store_true',
                      help='Diagnose all influencer countries')

    args = parser.parse_args()

    if args.influencers:
        from shared.utils.utils import Config
        config = Config.from_yaml('shared/config/config.yaml')
        countries = config.get('influencers', [])

        if not countries:
            print("❌ No influencer countries found in config")
            return

        for country in countries:
            diagnose_canonical_events(country)
            print("\n")
    else:
        diagnose_canonical_events(args.country)


if __name__ == "__main__":
    main()
