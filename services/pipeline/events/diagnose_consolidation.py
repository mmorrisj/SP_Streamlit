"""
Diagnostic Script: Event Consolidation Pipeline Analysis

This script checks the state of canonical_events to diagnose why multi-day events aren't appearing.
"""

from sqlalchemy import text
from shared.database.database import get_session


def diagnose_country(country: str):
    """Run comprehensive diagnostics for a specific country."""

    print("=" * 100)
    print(f"DIAGNOSTIC ANALYSIS: {country}")
    print("=" * 100)

    with get_session() as session:
        # 1. Count canonical events by type
        print("\n1. CANONICAL EVENTS BREAKDOWN:")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE master_event_id IS NULL) as masters,
                COUNT(*) FILTER (WHERE master_event_id IS NOT NULL) as children,
                COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = TRUE) as validated_masters,
                COUNT(*) FILTER (WHERE master_event_id IS NULL AND llm_validated = FALSE) as unvalidated_masters,
                COUNT(*) FILTER (WHERE embedding_vector IS NULL) as no_embedding,
                COUNT(*) as total
            FROM canonical_events
            WHERE initiating_country = :country
        """), {'country': country}).fetchone()

        print(f"   Total canonical events: {result[5]:,}")
        print(f"   Master events (master_event_id IS NULL): {result[0]:,}")
        print(f"   Child events (master_event_id IS NOT NULL): {result[1]:,}")
        print(f"   Validated masters (llm_validated=TRUE): {result[2]:,}")
        print(f"   Unvalidated masters (llm_validated=FALSE): {result[3]:,}")
        print(f"   Events without embeddings: {result[4]:,}")

        # 2. Check daily_event_mentions
        print("\n2. DAILY EVENT MENTIONS:")
        print("-" * 100)

        result = session.execute(text("""
            SELECT COUNT(*)
            FROM daily_event_mentions dem
            JOIN canonical_events ce ON dem.canonical_event_id = ce.id
            WHERE ce.initiating_country = :country
        """), {'country': country}).scalar()

        print(f"   Total daily_event_mentions: {result:,}")

        # Check mentions linked to masters vs children
        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE ce.master_event_id IS NULL) as master_mentions,
                COUNT(*) FILTER (WHERE ce.master_event_id IS NOT NULL) as child_mentions
            FROM daily_event_mentions dem
            JOIN canonical_events ce ON dem.canonical_event_id = ce.id
            WHERE ce.initiating_country = :country
        """), {'country': country}).fetchone()

        print(f"   Mentions linked to masters: {result[0]:,}")
        print(f"   Mentions linked to children: {result[1]:,}")

        # 3. Sample master-child relationships
        print("\n3. MASTER-CHILD RELATIONSHIPS (Sample of 5):")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                m.id as master_id,
                m.canonical_name as master_name,
                m.llm_validated,
                COUNT(c.id) as child_count
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id
            WHERE m.initiating_country = :country
              AND m.master_event_id IS NULL
            GROUP BY m.id, m.canonical_name, m.llm_validated
            ORDER BY COUNT(c.id) DESC
            LIMIT 5
        """), {'country': country}).fetchall()

        if result:
            for master_id, master_name, validated, child_count in result:
                safe_name = master_name.encode('ascii', 'replace').decode('ascii')[:60]
                val_str = "VALIDATED" if validated else "UNVALIDATED"
                print(f"   Master ID {master_id}: {safe_name}")
                print(f"      {val_str}, {child_count} children")
        else:
            print("   No master events found")

        # 4. Check multi-day events
        print("\n4. MULTI-DAY EVENT CHECK:")
        print("-" * 100)

        result = session.execute(text("""
            SELECT
                ce.canonical_name,
                COUNT(DISTINCT dem.mention_date) as days,
                ce.master_event_id IS NULL as is_master
            FROM canonical_events ce
            JOIN daily_event_mentions dem ON ce.id = dem.canonical_event_id
            WHERE ce.initiating_country = :country
            GROUP BY ce.id, ce.canonical_name, ce.master_event_id
            HAVING COUNT(DISTINCT dem.mention_date) > 1
            ORDER BY COUNT(DISTINCT dem.mention_date) DESC
            LIMIT 5
        """), {'country': country}).fetchall()

        if result:
            print(f"   Found {len(result)} multi-day events:")
            for name, days, is_master in result:
                safe_name = name.encode('ascii', 'replace').decode('ascii')[:60]
                event_type = "MASTER" if is_master else "CHILD"
                print(f"      {safe_name} ({event_type}): {days} days")
        else:
            print("   ⚠️  WARNING: NO MULTI-DAY EVENTS FOUND")

        # 5. Check consolidation history
        print("\n5. CONSOLIDATION HISTORY:")
        print("-" * 100)

        # Check if consolidate ran (would set master_event_id on some events)
        children_count = session.execute(text("""
            SELECT COUNT(*) FROM canonical_events
            WHERE initiating_country = :country
              AND master_event_id IS NOT NULL
        """), {'country': country}).scalar()

        if children_count > 0:
            print(f"   ✅ consolidate_all_events.py RAN ({children_count:,} children created)")
        else:
            print("   ❌ consolidate_all_events.py NEVER RAN or found zero groups")

        # Check if LLM validation ran
        validated_count = session.execute(text("""
            SELECT COUNT(*) FROM canonical_events
            WHERE initiating_country = :country
              AND master_event_id IS NULL
              AND llm_validated = TRUE
        """), {'country': country}).scalar()

        if validated_count > 0:
            print(f"   ✅ llm_deconflict_canonical_events.py RAN ({validated_count:,} validated)")
        else:
            print("   ❌ llm_deconflict_canonical_events.py NEVER RAN")

        # Check if merge ran (would move mentions to masters)
        if children_count > 0 and validated_count > 0:
            # If children exist and masters are validated, check if mentions were moved
            masters_with_mentions = session.execute(text("""
                SELECT COUNT(DISTINCT ce.id)
                FROM canonical_events ce
                JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
                WHERE ce.initiating_country = :country
                  AND ce.master_event_id IS NULL
                  AND ce.llm_validated = TRUE
            """), {'country': country}).scalar()

            if masters_with_mentions > 0:
                print(f"   ✅ merge_canonical_events.py RAN ({masters_with_mentions:,} masters have mentions)")
            else:
                print("   ❌ merge_canonical_events.py NEVER RAN or failed")

        # 6. DIAGNOSIS
        print("\n6. ROOT CAUSE DIAGNOSIS:")
        print("-" * 100)

        if children_count == 0:
            print("   🔴 ISSUE: consolidate_all_events.py created ZERO groups")
            print("   REASON: Likely similarity threshold too strict (default 0.85)")
            print("   FIX: Re-run with lower threshold: --threshold 0.75")

        elif validated_count == 0:
            print("   🔴 ISSUE: llm_deconflict_canonical_events.py never ran")
            print("   REASON: Skipped Stage 5 in pipeline")
            print("   FIX: Run llm_deconflict_canonical_events.py --country <country>")

        elif result[0] == 0:  # master_mentions from step 2
            print("   🔴 ISSUE: merge_canonical_events.py never ran or failed")
            print("   REASON: Skipped Stage 6 in pipeline")
            print("   FIX: Run merge_canonical_events.py --country <country>")
        else:
            print("   🟢 Pipeline completed successfully - multi-day events exist")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose event consolidation pipeline")
    parser.add_argument('--country', type=str, required=True, help='Country to analyze')

    args = parser.parse_args()

    diagnose_country(args.country)

    print("\n" + "=" * 100)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    main()
