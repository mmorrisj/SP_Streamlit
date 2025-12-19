"""
Data Integrity Verification Script

Checks the complete linkage chain in the event processing pipeline:
    Documents → DailyEventMentions → CanonicalEvents

Identifies:
1. Daily event mentions without doc_ids
2. Doc_ids that reference non-existent documents
3. Canonical events without any daily mentions
4. Event clusters without doc_ids
5. Orphaned data at each level
"""

import sys
from pathlib import Path
from sqlalchemy import text, func
from shared.database.database import get_session

def print_section(title):
    """Print formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")

def check_daily_event_mentions_without_docs(session):
    """Check for daily_event_mentions with missing or empty doc_ids."""
    print_section("1. DAILY_EVENT_MENTIONS WITHOUT DOC_IDS")

    # Count records without doc_ids
    result = session.execute(text("""
        SELECT COUNT(*) as count
        FROM daily_event_mentions
        WHERE doc_ids IS NULL OR doc_ids = '{}'
    """)).fetchone()

    missing_count = result[0]
    print(f"Records with missing/empty doc_ids: {missing_count:,}")

    if missing_count > 0:
        print(f"\n⚠️  WARNING: {missing_count:,} daily event mentions have NO source documents!")
        print("This breaks traceability from events back to original sources.\n")

        # Sample records
        print("Sample records without doc_ids:")
        samples = session.execute(text("""
            SELECT
                dem.id,
                dem.canonical_event_id,
                dem.mention_date,
                dem.initiating_country,
                dem.consolidated_headline,
                ce.canonical_name
            FROM daily_event_mentions dem
            LEFT JOIN canonical_events ce ON ce.id = dem.canonical_event_id
            WHERE dem.doc_ids IS NULL OR dem.doc_ids = '{}'
            LIMIT 10
        """)).fetchall()

        for row in samples:
            print(f"  ID: {row[0]}")
            print(f"  Event: {row[5]}")
            print(f"  Date: {row[2]}, Country: {row[3]}")
            print(f"  Headline: {row[4][:80] if row[4] else 'None'}...")
            print()
    else:
        print("✅ All daily event mentions have doc_ids")

    return missing_count

def check_doc_id_references(session):
    """Verify that doc_ids in daily_event_mentions reference actual documents."""
    print_section("2. DOC_ID REFERENCE INTEGRITY")

    # Get total daily_event_mentions with doc_ids
    total_result = session.execute(text("""
        SELECT COUNT(*) FROM daily_event_mentions
        WHERE doc_ids IS NOT NULL AND doc_ids != '{}'
    """)).fetchone()
    total_with_docs = total_result[0]

    print(f"Total daily_event_mentions with doc_ids: {total_with_docs:,}")

    # Check for broken references (this is expensive, so we sample)
    print("\nVerifying doc_id references (sampling 100 records)...")

    samples = session.execute(text("""
        SELECT dem.id, dem.doc_ids, dem.canonical_event_id
        FROM daily_event_mentions dem
        WHERE dem.doc_ids IS NOT NULL AND dem.doc_ids != '{}'
        LIMIT 100
    """)).fetchall()

    broken_refs = 0
    valid_refs = 0

    for row in samples:
        doc_ids = row[1]
        if not doc_ids or len(doc_ids) == 0:
            continue

        # Check each doc_id
        for doc_id in doc_ids:
            check = session.execute(text("""
                SELECT COUNT(*) FROM softpower_documents WHERE id = :doc_id
            """), {'doc_id': doc_id}).fetchone()[0]

            if check == 0:
                broken_refs += 1
                if broken_refs <= 5:  # Only print first 5
                    print(f"  ⚠️  Broken reference: mention {row[0]} → doc_id {doc_id} (not found)")
            else:
                valid_refs += 1

    print(f"\nSample results:")
    print(f"  Valid references: {valid_refs}")
    print(f"  Broken references: {broken_refs}")

    if broken_refs > 0:
        print(f"\n⚠️  WARNING: Found broken doc_id references!")
    else:
        print(f"\n✅ All sampled doc_id references are valid")

    return broken_refs

def check_canonical_events_without_mentions(session):
    """Check for canonical events with no daily_event_mentions."""
    print_section("3. CANONICAL EVENTS WITHOUT DAILY_EVENT_MENTIONS")

    result = session.execute(text("""
        SELECT COUNT(*) as count
        FROM canonical_events ce
        LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
        WHERE dem.id IS NULL
    """)).fetchone()

    orphaned_count = result[0]
    print(f"Canonical events without mentions: {orphaned_count:,}")

    if orphaned_count > 0:
        print(f"\n⚠️  WARNING: {orphaned_count:,} canonical events have NO daily mentions!")
        print("These events exist but have no linkage to when/where they were mentioned.\n")

        # Sample orphaned events
        print("Sample orphaned canonical events:")
        samples = session.execute(text("""
            SELECT ce.id, ce.canonical_name, ce.initiating_country, ce.first_mention_date
            FROM canonical_events ce
            LEFT JOIN daily_event_mentions dem ON dem.canonical_event_id = ce.id
            WHERE dem.id IS NULL
            LIMIT 10
        """)).fetchall()

        for row in samples:
            print(f"  ID: {row[0]}")
            print(f"  Name: {row[1][:80]}...")
            print(f"  Country: {row[2]}, First Mention: {row[3]}")
            print()
    else:
        print("✅ All canonical events have at least one daily mention")

    return orphaned_count

def check_event_clusters_without_docs(session):
    """Check for event_clusters with missing doc_ids."""
    print_section("4. EVENT CLUSTERS WITHOUT DOC_IDS")

    result = session.execute(text("""
        SELECT COUNT(*) as count
        FROM event_clusters
        WHERE doc_ids IS NULL OR doc_ids = '{}'
    """)).fetchone()

    missing_count = result[0]
    print(f"Event clusters with missing/empty doc_ids: {missing_count:,}")

    if missing_count > 0:
        print(f"\n⚠️  WARNING: {missing_count:,} event clusters have NO source documents!")
        print("This breaks the initial clustering → canonical event linkage.\n")

        # Sample records
        print("Sample clusters without doc_ids:")
        samples = session.execute(text("""
            SELECT id, initiating_country, cluster_date, cluster_size, representative_name
            FROM event_clusters
            WHERE doc_ids IS NULL OR doc_ids = '{}'
            LIMIT 10
        """)).fetchall()

        for row in samples:
            print(f"  ID: {row[0]}, Country: {row[1]}, Date: {row[2]}")
            print(f"  Size: {row[3]}, Name: {row[4]}")
            print()
    else:
        print("✅ All event clusters have doc_ids")

    return missing_count

def get_pipeline_statistics(session):
    """Get overall pipeline statistics."""
    print_section("5. OVERALL PIPELINE STATISTICS")

    # Documents
    doc_count = session.execute(text('SELECT COUNT(*) FROM softpower_documents')).fetchone()[0]
    print(f"📄 Documents: {doc_count:,}")

    # Event Clusters
    cluster_count = session.execute(text('SELECT COUNT(*) FROM event_clusters')).fetchone()[0]
    deconflicted = session.execute(text('SELECT COUNT(*) FROM event_clusters WHERE llm_deconflicted = true')).fetchone()[0]
    print(f"\n🔵 Event Clusters: {cluster_count:,}")
    print(f"   LLM Deconflicted: {deconflicted:,} ({deconflicted/cluster_count*100:.1f}%)")

    # Canonical Events
    canonical_count = session.execute(text('SELECT COUNT(*) FROM canonical_events')).fetchone()[0]
    scored_count = session.execute(text(
        'SELECT COUNT(*) FROM canonical_events WHERE material_score IS NOT NULL AND material_score > 0'
    )).fetchone()[0]
    print(f"\n⭐ Canonical Events: {canonical_count:,}")
    print(f"   Materiality Scored: {scored_count:,} ({scored_count/canonical_count*100:.1f}%)")
    print(f"   Unscored: {canonical_count - scored_count:,}")

    # Daily Event Mentions
    mention_count = session.execute(text('SELECT COUNT(*) FROM daily_event_mentions')).fetchone()[0]
    mentions_with_docs = session.execute(text(
        "SELECT COUNT(*) FROM daily_event_mentions WHERE doc_ids IS NOT NULL AND doc_ids != '{}'"
    )).fetchone()[0]
    print(f"\n📰 Daily Event Mentions: {mention_count:,}")
    print(f"   With doc_ids: {mentions_with_docs:,} ({mentions_with_docs/mention_count*100:.1f}%)")
    print(f"   Without doc_ids: {mention_count - mentions_with_docs:,}")

    # Event Summaries
    summary_count = session.execute(text('SELECT COUNT(*) FROM event_summaries')).fetchone()[0]
    print(f"\n📊 Event Summaries: {summary_count:,}")

def get_materiality_by_country(session):
    """Get materiality scoring status by country."""
    print_section("6. MATERIALITY SCORING BY COUNTRY")

    results = session.execute(text("""
        SELECT
            initiating_country,
            COUNT(*) as total,
            COUNT(CASE WHEN material_score IS NOT NULL AND material_score > 0 THEN 1 END) as scored,
            ROUND(COUNT(CASE WHEN material_score IS NOT NULL AND material_score > 0 THEN 1 END)::numeric / COUNT(*)::numeric * 100, 1) as pct
        FROM canonical_events
        WHERE initiating_country IS NOT NULL
        GROUP BY initiating_country
        ORDER BY total DESC
    """)).fetchall()

    print(f"{'Country':<20} {'Scored':<10} {'Total':<10} {'%':<8} {'Remaining':<10}")
    print("-" * 70)

    for row in results:
        country, total, scored, pct = row
        remaining = total - scored
        print(f"{country:<20} {scored:>9,} {total:>9,} {pct:>7.1f}% {remaining:>9,}")

def check_master_event_hierarchy(session):
    """Check master event consolidation hierarchy."""
    print_section("7. MASTER EVENT HIERARCHY")

    # Master events (no parent)
    master_count = session.execute(text(
        'SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL'
    )).fetchone()[0]

    # Child events (have parent)
    child_count = session.execute(text(
        'SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NOT NULL'
    )).fetchone()[0]

    print(f"Master events (master_event_id IS NULL): {master_count:,}")
    print(f"Child events (master_event_id IS NOT NULL): {child_count:,}")

    if child_count > 0:
        # Check for broken master_event_id references
        broken_refs = session.execute(text("""
            SELECT COUNT(*) FROM canonical_events ce1
            WHERE ce1.master_event_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM canonical_events ce2
                WHERE ce2.id = ce1.master_event_id
            )
        """)).fetchone()[0]

        if broken_refs > 0:
            print(f"\n⚠️  WARNING: {broken_refs:,} child events have broken master_event_id references!")
        else:
            print(f"\n✅ All master_event_id references are valid")

def main():
    """Run all data integrity checks."""
    print("\n" + "="*80)
    print("  SOFT POWER PIPELINE - DATA INTEGRITY VERIFICATION")
    print("="*80)

    try:
        with get_session() as session:
            # Run all checks
            issues = []

            # 1. Daily event mentions without docs
            missing_docs = check_daily_event_mentions_without_docs(session)
            if missing_docs > 0:
                issues.append(f"{missing_docs:,} daily event mentions without doc_ids")

            # 2. Doc_id reference integrity
            broken_refs = check_doc_id_references(session)
            if broken_refs > 0:
                issues.append(f"{broken_refs} broken doc_id references found in sample")

            # 3. Canonical events without mentions
            orphaned_events = check_canonical_events_without_mentions(session)
            if orphaned_events > 0:
                issues.append(f"{orphaned_events:,} canonical events without daily mentions")

            # 4. Event clusters without docs
            missing_cluster_docs = check_event_clusters_without_docs(session)
            if missing_cluster_docs > 0:
                issues.append(f"{missing_cluster_docs:,} event clusters without doc_ids")

            # 5. Overall statistics
            get_pipeline_statistics(session)

            # 6. Materiality by country
            get_materiality_by_country(session)

            # 7. Master event hierarchy
            check_master_event_hierarchy(session)

            # Summary
            print_section("SUMMARY")
            if issues:
                print("❌ DATA INTEGRITY ISSUES FOUND:\n")
                for issue in issues:
                    print(f"  • {issue}")
                print("\nRECOMMENDATIONS:")
                print("  1. Investigate why doc_ids are missing from daily_event_mentions")
                print("  2. Review the event clustering and LLM deconfliction process")
                print("  3. Ensure all scripts properly populate doc_ids when creating mentions")
                print("  4. Consider backfilling missing doc_ids from event_clusters if possible")
            else:
                print("✅ ALL DATA INTEGRITY CHECKS PASSED")
                print("\nThe event pipeline has proper linkage:")
                print("  Documents ← daily_event_mentions ← canonical_events")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
