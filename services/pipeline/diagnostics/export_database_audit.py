"""
Database Audit Export Script

Executes comprehensive database audit and exports all findings to a text file
suitable for emailing. Includes all metrics, tables, and analysis.

Usage:
    python services/pipeline/diagnostics/export_database_audit.py
    python services/pipeline/diagnostics/export_database_audit.py --output audit_report.txt
"""

import sys
from pathlib import Path
import pandas as pd
import yaml
from datetime import datetime
from sqlalchemy import create_engine, text
import argparse

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

# Database connection (from environment variables or defaults)
import os
DB_USER = os.getenv("POSTGRES_USER", "matthew50")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "softpower")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "softpower-db")

# Create engine
engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# Load config
with open(project_root / 'shared/config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

INFLUENCERS = config.get('influencers', [])
RECIPIENTS = config.get('recipients', [])
CATEGORIES = config.get('categories', [])


def run_query(query, params=None):
    """Run a SQL query and return results as DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params)


def run_scalar(query, params=None):
    """Run a SQL query and return scalar result."""
    with engine.connect() as conn:
        return conn.execute(text(query), params or {}).scalar()


def format_dataframe(df, title=None, max_rows=None):
    """Format DataFrame as text table."""
    lines = []
    if title:
        lines.append(f"\n{title}")
        lines.append("=" * len(title))

    if len(df) == 0:
        lines.append("(No data)")
        return "\n".join(lines)

    # Limit rows if specified
    display_df = df.head(max_rows) if max_rows else df

    # Convert to string representation
    lines.append(display_df.to_string(index=False))

    if max_rows and len(df) > max_rows:
        lines.append(f"\n... ({len(df) - max_rows} more rows)")

    return "\n".join(lines)


def export_audit(output_file: Path):
    """Execute database audit and export to text file."""

    output = []

    # Header
    output.append("=" * 80)
    output.append("SOFT POWER DATABASE AUDIT REPORT")
    output.append("=" * 80)
    output.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"Database: {DB_NAME} @ {DB_HOST}:{DB_PORT}")

    # Test connection
    try:
        doc_count = run_scalar("SELECT COUNT(*) FROM documents")
        output.append(f"Connection: SUCCESS")
        output.append(f"Documents: {doc_count:,}")
    except Exception as e:
        output.append(f"Connection: FAILED - {e}")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(output))
        return

    # Configuration
    output.append(f"\n{'=' * 80}")
    output.append("CONFIGURATION")
    output.append("=" * 80)
    output.append(f"\nInfluencing Countries: {', '.join(INFLUENCERS)}")
    output.append(f"Recipient Countries: {len(RECIPIENTS)} countries")
    output.append(f"Categories: {', '.join(CATEGORIES)}")

    # ====================
    # 1. TABLE OVERVIEW
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("1. TABLE OVERVIEW")
    output.append("=" * 80)

    tables_df = run_query("""
        SELECT
            relname as table_name,
            n_live_tup as row_count
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
        ORDER BY n_live_tup DESC
    """)

    output.append(f"\nTotal tables: {len(tables_df)}")
    output.append(f"Total rows: {tables_df['row_count'].sum():,}")
    output.append(format_dataframe(tables_df, "\nAll Tables:"))

    # ====================
    # 2. DOCUMENTS ANALYSIS
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("2. DOCUMENTS ANALYSIS")
    output.append("=" * 80)

    # Basic counts
    doc_count = run_scalar("SELECT COUNT(*) FROM documents")
    output.append(f"\nTotal Documents: {doc_count:,}")

    # Date range
    date_range = run_query("""
        SELECT
            MIN(date) as earliest_date,
            MAX(date) as latest_date,
            COUNT(DISTINCT date) as unique_dates
        FROM documents
        WHERE date IS NOT NULL
    """)
    output.append(f"\nDate Range:")
    output.append(f"  Earliest: {date_range['earliest_date'].iloc[0]}")
    output.append(f"  Latest: {date_range['latest_date'].iloc[0]}")
    output.append(f"  Unique Dates: {date_range['unique_dates'].iloc[0]:,}")

    # Documents by month
    docs_by_month = run_query("""
        SELECT
            DATE_TRUNC('month', date)::date as month,
            COUNT(*) as doc_count
        FROM documents
        WHERE date IS NOT NULL
        GROUP BY DATE_TRUNC('month', date)
        ORDER BY month DESC
    """)
    output.append(format_dataframe(docs_by_month, "\nDocuments by Month:", max_rows=12))

    # Initiating countries
    init_countries = run_query("""
        SELECT
            ic.initiating_country,
            COUNT(DISTINCT ic.doc_id) as doc_count,
            MIN(d.date) as earliest_date,
            MAX(d.date) as latest_date
        FROM initiating_countries ic
        JOIN documents d ON ic.doc_id = d.doc_id
        GROUP BY ic.initiating_country
        ORDER BY doc_count DESC
    """)
    init_countries['in_config'] = init_countries['initiating_country'].apply(
        lambda x: '*' if x in INFLUENCERS else ''
    )
    total_init_docs = init_countries['doc_count'].sum()
    config_init_docs = init_countries[init_countries['in_config'] == '*']['doc_count'].sum()

    output.append(format_dataframe(init_countries, "\nDocuments by Initiating Country:", max_rows=20))
    output.append(f"\nConfig Influencers Coverage: {config_init_docs:,} / {total_init_docs:,} ({config_init_docs/total_init_docs*100:.1f}%)")

    # Recipient countries
    rec_countries = run_query("""
        SELECT
            rc.recipient_country,
            COUNT(DISTINCT rc.doc_id) as doc_count,
            MIN(d.date) as earliest_date,
            MAX(d.date) as latest_date
        FROM recipient_countries rc
        JOIN documents d ON rc.doc_id = d.doc_id
        GROUP BY rc.recipient_country
        ORDER BY doc_count DESC
    """)
    rec_countries['in_config'] = rec_countries['recipient_country'].apply(
        lambda x: '*' if x in RECIPIENTS else ''
    )
    total_rec_docs = rec_countries['doc_count'].sum()
    config_rec_docs = rec_countries[rec_countries['in_config'] == '*']['doc_count'].sum()

    output.append(format_dataframe(rec_countries, "\nTop 30 Recipient Countries:", max_rows=30))
    output.append(f"\nConfig Recipients Coverage: {config_rec_docs:,} / {total_rec_docs:,} ({config_rec_docs/total_rec_docs*100:.1f}%)")

    # Categories
    categories_df = run_query("""
        SELECT
            c.category,
            COUNT(DISTINCT c.doc_id) as doc_count
        FROM categories c
        GROUP BY c.category
        ORDER BY doc_count DESC
    """)
    categories_df['in_config'] = categories_df['category'].apply(
        lambda x: '*' if x in CATEGORIES else ''
    )
    output.append(format_dataframe(categories_df, "\nDocuments by Category:"))

    # Salience
    salience_dist = run_query("""
        SELECT
            salience_bool as salience,
            COUNT(*) as doc_count
        FROM documents
        WHERE salience_bool IS NOT NULL
        GROUP BY salience_bool
        ORDER BY doc_count DESC
    """)
    output.append(format_dataframe(salience_dist, "\nSalience Distribution:"))

    # ====================
    # 3. NORMALIZED TABLES
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("3. NORMALIZED RELATIONSHIP TABLES")
    output.append("=" * 80)

    cat_count = run_scalar("SELECT COUNT(*) FROM categories")
    cat_unique = run_scalar("SELECT COUNT(DISTINCT category) FROM categories")
    output.append(f"\nCategories Table: {cat_count:,} rows, {cat_unique} unique")

    subcat_count = run_scalar("SELECT COUNT(*) FROM subcategories")
    subcat_unique = run_scalar("SELECT COUNT(DISTINCT subcategory) FROM subcategories")
    output.append(f"Subcategories Table: {subcat_count:,} rows, {subcat_unique} unique")

    init_count = run_scalar("SELECT COUNT(*) FROM initiating_countries")
    init_unique = run_scalar("SELECT COUNT(DISTINCT initiating_country) FROM initiating_countries")
    output.append(f"Initiating Countries Table: {init_count:,} rows, {init_unique} unique")

    rec_count = run_scalar("SELECT COUNT(*) FROM recipient_countries")
    rec_unique = run_scalar("SELECT COUNT(DISTINCT recipient_country) FROM recipient_countries")
    output.append(f"Recipient Countries Table: {rec_count:,} rows, {rec_unique} unique")

    raw_events_count = run_scalar("SELECT COUNT(*) FROM raw_events")
    raw_events_unique = run_scalar("SELECT COUNT(DISTINCT event_name) FROM raw_events")
    output.append(f"Raw Events Table: {raw_events_count:,} rows, {raw_events_unique:,} unique events")

    # ====================
    # 4. EVENT HIERARCHY
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("4. EVENT HIERARCHY ANALYSIS")
    output.append("=" * 80)

    # Event Clusters
    try:
        cluster_count = run_scalar("SELECT COUNT(*) FROM event_clusters")
        output.append(f"\nEvent Clusters: {cluster_count:,}")

        if cluster_count > 0:
            clusters_by_country = run_query("""
                SELECT
                    initiating_country,
                    COUNT(*) as cluster_count,
                    SUM(cluster_size) as total_events,
                    MIN(cluster_date) as earliest_date,
                    MAX(cluster_date) as latest_date
                FROM event_clusters
                GROUP BY initiating_country
                ORDER BY cluster_count DESC
            """)
            clusters_by_country['in_config'] = clusters_by_country['initiating_country'].apply(
                lambda x: '*' if x in INFLUENCERS else ''
            )
            output.append(format_dataframe(clusters_by_country, "\nClusters by Country:"))
    except Exception as e:
        output.append(f"\nEvent Clusters: Not available ({e})")

    # Canonical Events
    try:
        canonical_count = run_scalar("SELECT COUNT(*) FROM canonical_events")
        master_count = run_scalar("SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NULL")
        child_count = run_scalar("SELECT COUNT(*) FROM canonical_events WHERE master_event_id IS NOT NULL")

        output.append(f"\nCanonical Events: {canonical_count:,}")
        output.append(f"  Master events: {master_count:,}")
        output.append(f"  Child events: {child_count:,}")

        if canonical_count > 0:
            canonical_by_country = run_query("""
                SELECT
                    initiating_country,
                    COUNT(*) as event_count,
                    SUM(total_articles) as total_articles,
                    ROUND(AVG(total_mention_days)::numeric, 1) as avg_mention_days,
                    MIN(first_mention_date) as earliest_mention,
                    MAX(last_mention_date) as latest_mention
                FROM canonical_events
                GROUP BY initiating_country
                ORDER BY event_count DESC
            """)
            canonical_by_country['in_config'] = canonical_by_country['initiating_country'].apply(
                lambda x: '*' if x in INFLUENCERS else ''
            )
            output.append(format_dataframe(canonical_by_country, "\nCanonical Events by Country:"))

            # Materiality scores
            materiality = run_query("""
                SELECT
                    initiating_country,
                    COUNT(*) as events_with_score,
                    ROUND(AVG(material_score)::numeric, 2) as avg_score,
                    MIN(material_score) as min_score,
                    MAX(material_score) as max_score
                FROM canonical_events
                WHERE material_score IS NOT NULL
                GROUP BY initiating_country
                ORDER BY avg_score DESC
            """)
            output.append(format_dataframe(materiality, "\nMateriality Scores by Country:"))

            total_events = run_scalar("SELECT COUNT(*) FROM canonical_events")
            scored_events = run_scalar("SELECT COUNT(*) FROM canonical_events WHERE material_score IS NOT NULL")
            output.append(f"\nMateriality Score Coverage: {scored_events:,} / {total_events:,} ({scored_events/total_events*100:.1f}%)")
    except Exception as e:
        output.append(f"\nCanonical Events: Not available ({e})")

    # Daily Event Mentions
    try:
        mention_count = run_scalar("SELECT COUNT(*) FROM daily_event_mentions")
        output.append(f"\nDaily Event Mentions: {mention_count:,}")

        if mention_count > 0:
            mentions_by_country = run_query("""
                SELECT
                    initiating_country,
                    COUNT(*) as mention_count,
                    SUM(article_count) as total_articles,
                    COUNT(DISTINCT mention_date) as unique_dates,
                    MIN(mention_date) as earliest_date,
                    MAX(mention_date) as latest_date
                FROM daily_event_mentions
                GROUP BY initiating_country
                ORDER BY mention_count DESC
            """)
            mentions_by_country['in_config'] = mentions_by_country['initiating_country'].apply(
                lambda x: '*' if x in INFLUENCERS else ''
            )
            output.append(format_dataframe(mentions_by_country, "\nDaily Mentions by Country:"))

            # Data integrity check
            mentions_with_docs = run_scalar("SELECT COUNT(*) FROM daily_event_mentions WHERE doc_ids IS NOT NULL AND array_length(doc_ids, 1) > 0")
            output.append(f"\nData Integrity: {mentions_with_docs:,} / {mention_count:,} mentions have doc_ids ({mentions_with_docs/mention_count*100:.2f}%)")
    except Exception as e:
        output.append(f"\nDaily Event Mentions: Not available ({e})")

    # Event Summaries
    try:
        summary_count = run_scalar("SELECT COUNT(*) FROM event_summaries")
        output.append(f"\nEvent Summaries: {summary_count:,}")

        if summary_count > 0:
            summaries_by_type = run_query("""
                SELECT
                    period_type,
                    COUNT(*) as summary_count,
                    MIN(period_start) as earliest_period,
                    MAX(period_end) as latest_period
                FROM event_summaries
                GROUP BY period_type
                ORDER BY summary_count DESC
            """)
            output.append(format_dataframe(summaries_by_type, "\nSummaries by Period Type:"))

            summaries_by_country = run_query("""
                SELECT
                    initiating_country,
                    COUNT(*) as summary_count,
                    SUM(total_documents_across_sources) as total_docs,
                    MIN(period_start) as earliest_period,
                    MAX(period_end) as latest_period
                FROM event_summaries
                GROUP BY initiating_country
                ORDER BY summary_count DESC
            """)
            summaries_by_country['in_config'] = summaries_by_country['initiating_country'].apply(
                lambda x: '*' if x in INFLUENCERS else ''
            )
            output.append(format_dataframe(summaries_by_country, "\nSummaries by Country:"))
    except Exception as e:
        output.append(f"\nEvent Summaries: Not available ({e})")

    # ====================
    # 5. EMBEDDINGS
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("5. EMBEDDINGS ANALYSIS")
    output.append("=" * 80)

    try:
        collections = run_query("""
            SELECT
                c.name as collection_name,
                COUNT(e.uuid) as embedding_count
            FROM langchain_pg_collection c
            LEFT JOIN langchain_pg_embedding e ON c.uuid = e.collection_id
            GROUP BY c.name
            ORDER BY embedding_count DESC
        """)
        total_embeddings = collections['embedding_count'].sum()
        output.append(f"\nTotal Embedding Collections: {len(collections)}")
        output.append(f"Total Embeddings: {total_embeddings:,}")
        output.append(format_dataframe(collections, "\nCollections:"))
    except Exception as e:
        output.append(f"\nEmbeddings: Not available ({e})")

    # ====================
    # 6. INFLUENCER DEEP DIVE
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("6. INFLUENCER COUNTRY DEEP DIVE")
    output.append("=" * 80)

    for country in INFLUENCERS:
        output.append(f"\n{'-' * 80}")
        output.append(f"{country.upper()}")
        output.append("-" * 80)

        # Documents
        doc_stats = run_query("""
            SELECT
                COUNT(DISTINCT ic.doc_id) as total_docs,
                MIN(d.date) as earliest_date,
                MAX(d.date) as latest_date,
                COUNT(DISTINCT d.date) as unique_dates
            FROM initiating_countries ic
            JOIN documents d ON ic.doc_id = d.doc_id
            WHERE ic.initiating_country = :country
        """, {'country': country})
        output.append(f"\nDocuments: {doc_stats['total_docs'].iloc[0]:,}")
        output.append(f"Date Range: {doc_stats['earliest_date'].iloc[0]} to {doc_stats['latest_date'].iloc[0]}")
        output.append(f"Unique Dates: {doc_stats['unique_dates'].iloc[0]:,}")

        # Top recipients
        top_recipients = run_query("""
            SELECT
                rc.recipient_country,
                COUNT(DISTINCT rc.doc_id) as doc_count
            FROM recipient_countries rc
            JOIN initiating_countries ic ON rc.doc_id = ic.doc_id
            WHERE ic.initiating_country = :country
            GROUP BY rc.recipient_country
            ORDER BY doc_count DESC
            LIMIT 15
        """, {'country': country})
        top_recipients['in_config'] = top_recipients['recipient_country'].apply(
            lambda x: '*' if x in RECIPIENTS else ''
        )
        output.append(format_dataframe(top_recipients, "\nTop 15 Recipient Countries:"))

        # Categories
        categories = run_query("""
            SELECT
                c.category,
                COUNT(DISTINCT c.doc_id) as doc_count
            FROM categories c
            JOIN initiating_countries ic ON c.doc_id = ic.doc_id
            WHERE ic.initiating_country = :country
            GROUP BY c.category
            ORDER BY doc_count DESC
        """, {'country': country})
        output.append(format_dataframe(categories, "\nCategories:"))

        # Canonical events
        try:
            event_stats = run_query("""
                SELECT
                    COUNT(*) as total_events,
                    SUM(total_articles) as total_articles,
                    ROUND(AVG(material_score)::numeric, 2) as avg_materiality,
                    COUNT(CASE WHEN material_score IS NOT NULL THEN 1 END) as scored_events
                FROM canonical_events
                WHERE initiating_country = :country
            """, {'country': country})
            output.append(f"\nCanonical Events: {event_stats['total_events'].iloc[0]:,}")
            if event_stats['total_articles'].iloc[0]:
                output.append(f"Total Articles: {int(event_stats['total_articles'].iloc[0]):,}")
            if event_stats['avg_materiality'].iloc[0]:
                output.append(f"Avg Materiality Score: {float(event_stats['avg_materiality'].iloc[0]):.2f}")
                output.append(f"Scored Events: {event_stats['scored_events'].iloc[0]:,} / {event_stats['total_events'].iloc[0]:,}")
        except:
            pass

    # ====================
    # 7. BILATERAL SUMMARIES
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("7. BILATERAL RELATIONSHIP SUMMARIES")
    output.append("=" * 80)

    try:
        bilateral_count = run_scalar("SELECT COUNT(*) FROM bilateral_relationship_summaries")
        output.append(f"\nTotal Bilateral Summaries: {bilateral_count:,}")

        if bilateral_count > 0:
            bilateral_summaries = run_query("""
                SELECT
                    initiating_country,
                    recipient_country,
                    total_documents,
                    total_daily_events,
                    ROUND(material_score_avg::numeric, 2) as avg_material_score,
                    first_interaction_date,
                    last_interaction_date
                FROM bilateral_relationship_summaries
                WHERE is_deleted = false
                ORDER BY total_documents DESC
                LIMIT 30
            """)
            output.append(format_dataframe(bilateral_summaries, "\nTop 30 Bilateral Relationships:"))
    except Exception as e:
        output.append(f"\nBilateral Summaries: Not available ({e})")

    # ====================
    # 8. DATA QUALITY
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("8. DATA QUALITY CHECKS")
    output.append("=" * 80)

    # Null checks
    null_checks = run_query("""
        SELECT
            COUNT(*) as total_docs,
            SUM(CASE WHEN date IS NULL THEN 1 ELSE 0 END) as null_dates,
            SUM(CASE WHEN initiating_country IS NULL THEN 1 ELSE 0 END) as null_init_country,
            SUM(CASE WHEN recipient_country IS NULL THEN 1 ELSE 0 END) as null_rec_country,
            SUM(CASE WHEN category IS NULL THEN 1 ELSE 0 END) as null_category,
            SUM(CASE WHEN salience_bool IS NULL THEN 1 ELSE 0 END) as null_salience
        FROM documents
    """)

    total = null_checks['total_docs'].iloc[0]
    output.append(f"\nNull Value Analysis (Documents table):")
    output.append(f"  Total documents: {total:,}")
    output.append(f"  Null dates: {null_checks['null_dates'].iloc[0]:,} ({null_checks['null_dates'].iloc[0]/total*100:.1f}%)")
    output.append(f"  Null initiating_country: {null_checks['null_init_country'].iloc[0]:,} ({null_checks['null_init_country'].iloc[0]/total*100:.1f}%)")
    output.append(f"  Null recipient_country: {null_checks['null_rec_country'].iloc[0]:,} ({null_checks['null_rec_country'].iloc[0]/total*100:.1f}%)")
    output.append(f"  Null category: {null_checks['null_category'].iloc[0]:,} ({null_checks['null_category'].iloc[0]/total*100:.1f}%)")
    output.append(f"  Null salience_bool: {null_checks['null_salience'].iloc[0]:,} ({null_checks['null_salience'].iloc[0]/total*100:.1f}%)")

    # ====================
    # 9. EXECUTIVE SUMMARY
    # ====================
    output.append(f"\n\n{'=' * 80}")
    output.append("9. EXECUTIVE SUMMARY")
    output.append("=" * 80)

    summary_stats = []

    # Documents
    summary_stats.append(f"Total Documents: {run_scalar('SELECT COUNT(*) FROM documents'):,}")

    # Date range
    date_info = run_query("SELECT MIN(date), MAX(date) FROM documents WHERE date IS NOT NULL")
    summary_stats.append(f"Date Range: {date_info.iloc[0, 0]} to {date_info.iloc[0, 1]}")

    # Influencer coverage
    influencer_docs = run_scalar(f"""
        SELECT COUNT(DISTINCT doc_id) FROM initiating_countries
        WHERE initiating_country IN {tuple(INFLUENCERS)}
    """)
    summary_stats.append(f"Documents from Config Influencers: {influencer_docs:,}")

    # Recipient coverage
    recipient_docs = run_scalar(f"""
        SELECT COUNT(DISTINCT doc_id) FROM recipient_countries
        WHERE recipient_country IN {tuple(RECIPIENTS)}
    """)
    summary_stats.append(f"Documents to Config Recipients: {recipient_docs:,}")

    # Events
    try:
        summary_stats.append(f"Event Clusters: {run_scalar('SELECT COUNT(*) FROM event_clusters'):,}")
    except:
        pass

    try:
        summary_stats.append(f"Canonical Events: {run_scalar('SELECT COUNT(*) FROM canonical_events'):,}")
    except:
        pass

    try:
        summary_stats.append(f"Daily Event Mentions: {run_scalar('SELECT COUNT(*) FROM daily_event_mentions'):,}")
    except:
        pass

    try:
        summary_stats.append(f"Event Summaries: {run_scalar('SELECT COUNT(*) FROM event_summaries'):,}")
    except:
        pass

    # Embeddings
    try:
        summary_stats.append(f"Total Embeddings: {run_scalar('SELECT COUNT(*) FROM langchain_pg_embedding'):,}")
    except:
        pass

    for stat in summary_stats:
        output.append(f"\n  - {stat}")

    # Footer
    output.append(f"\n\n{'=' * 80}")
    output.append("END OF REPORT")
    output.append("=" * 80)
    output.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Write to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(output))

    return output_file, len(output)


def main():
    parser = argparse.ArgumentParser(description='Export database audit to text file')
    parser.add_argument('--output', type=str, default='database_audit_report.txt',
                       help='Output file path (default: database_audit_report.txt)')

    args = parser.parse_args()
    output_file = Path(args.output)

    print(f"Executing database audit...")
    print(f"Connecting to {DB_NAME} @ {DB_HOST}:{DB_PORT}")

    try:
        result_file, lines = export_audit(output_file)
        print(f"\n[SUCCESS] Audit complete!")
        print(f"   Output: {result_file.absolute()}")
        print(f"   Lines: {lines:,}")
        print(f"   Size: {result_file.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"\n[ERROR] Audit failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
