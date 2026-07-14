"""
Foundational derived analytics for the MENA influence reports.
Writes ONLY to the `analytics` schema; treats `public` as read-only.

Builds:
  analytics.report_base                  scoped flattened fact (doc x initiator x recipient x category)
  analytics.provenance_intensity         (initiator,recipient,category,month) provenance-normalized metrics
  analytics.actor_recipient_category_month  cross-actor tensor (same grain, all 4 initiators)

Run: python docs/reports/_derived/build_analytics.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.database.database import get_session
from sqlalchemy import text

INITIATORS = ('China', 'Iran', 'Russia', 'Turkey')
# MENA recipient set from config.yaml (UAE appears as both spellings in the data)
MENA = ('Bahrain', 'Cyprus', 'Egypt', 'Iraq', 'Israel', 'Jordan', 'Kuwait', 'Lebanon',
        'Libya', 'Oman', 'Palestine', 'Qatar', 'Saudi Arabia', 'Syria',
        'United Arab Emirates', 'UAE', 'Yemen', 'Iran', 'Turkey')
START = '2024-08-01'
END = '2026-07-01'   # exclusive — last full month is June 2026 (avoid partial-month artifacts)


def build(session):
    session.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))

    # --- report_base: the scoped, flattened fact table -----------------------
    # Grain: one row per (doc, initiating_country, recipient_country, category).
    # Provenance: self_reported = the source's geo-focus is the initiator itself.
    session.execute(text("DROP TABLE IF EXISTS analytics.report_base CASCADE"))
    session.execute(text(f"""
        CREATE TABLE analytics.report_base AS
        SELECT
            d.doc_id,
            d.date,
            date_trunc('month', d.date)::date              AS month,
            ic.initiating_country,
            rc.recipient_country,
            c.category,
            d.source_name,
            d.source_geofocus,
            (d.source_geofocus ILIKE '%' || ic.initiating_country || '%') AS self_reported,
            (d.source_geofocus ILIKE '%' || rc.recipient_country || '%')  AS recipient_focused
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries  rc ON d.doc_id = rc.doc_id
        JOIN categories           c  ON d.doc_id = c.doc_id
        WHERE ic.initiating_country IN :inits
          AND rc.recipient_country  IN :mena
          AND ic.initiating_country <> rc.recipient_country
          AND c.category IN ('Economic','Social','Military','Diplomacy')
          AND d.date >= :start
          AND d.date < :end
    """).bindparams(inits=INITIATORS, mena=MENA, start=START, end=END))
    session.execute(text("CREATE INDEX ix_rb_irc ON analytics.report_base "
                         "(initiating_country, recipient_country, category)"))
    session.execute(text("CREATE INDEX ix_rb_month ON analytics.report_base (month)"))
    session.commit()

    # --- provenance_intensity: the bias-corrected backbone metric ------------
    session.execute(text("DROP TABLE IF EXISTS analytics.provenance_intensity CASCADE"))
    session.execute(text("""
        CREATE TABLE analytics.provenance_intensity AS
        SELECT
            initiating_country,
            recipient_country,
            category,
            month,
            count(DISTINCT doc_id)                                          AS raw_docs,
            count(DISTINCT doc_id) FILTER (WHERE self_reported)             AS self_reported_docs,
            count(DISTINCT doc_id) FILTER (WHERE NOT self_reported)         AS third_party_docs,
            count(DISTINCT doc_id) FILTER (WHERE recipient_focused)         AS recipient_focused_docs,
            count(DISTINCT source_name)                                     AS distinct_sources,
            round( (count(DISTINCT doc_id) FILTER (WHERE self_reported))::numeric
                   / NULLIF(count(DISTINCT doc_id),0), 3)                   AS self_report_share
        FROM analytics.report_base
        GROUP BY 1,2,3,4
    """))
    # normalized_intensity = third-party-corroborated volume (the trustworthy signal)
    session.execute(text("ALTER TABLE analytics.provenance_intensity "
                         "ADD COLUMN normalized_intensity integer"))
    session.execute(text("UPDATE analytics.provenance_intensity "
                         "SET normalized_intensity = third_party_docs"))
    session.commit()

    # --- actor_recipient_category_month: cross-actor tensor (rollup) ---------
    session.execute(text("DROP TABLE IF EXISTS analytics.actor_recipient_category_month CASCADE"))
    session.execute(text("""
        CREATE TABLE analytics.actor_recipient_category_month AS
        SELECT initiating_country, recipient_country, category, month,
               sum(raw_docs)            AS raw_docs,
               sum(third_party_docs)    AS third_party_docs,
               sum(self_reported_docs)  AS self_reported_docs,
               sum(distinct_sources)    AS distinct_sources
        FROM analytics.provenance_intensity
        GROUP BY 1,2,3,4
    """))
    session.commit()


def report(session):
    def q(sql):
        return session.execute(text(sql)).fetchall()
    print("report_base rows:", q("SELECT count(*) FROM analytics.report_base")[0][0])
    print("provenance_intensity rows:", q("SELECT count(*) FROM analytics.provenance_intensity")[0][0])
    print("\n== Raw vs. third-party-corroborated volume by initiator (the bias, quantified) ==")
    for r in q("""SELECT initiating_country,
                         sum(raw_docs) raw,
                         sum(third_party_docs) third_party,
                         round(avg(self_report_share),3) avg_self_share
                  FROM analytics.provenance_intensity GROUP BY 1 ORDER BY raw DESC"""):
        print(f"  {r[0]:<8} raw={r[1]:>7,}  third_party={r[2]:>7,}  avg_self_share={r[3]}")


if __name__ == "__main__":
    with get_session() as s:
        build(s)
        report(s)
    print("\n[done] analytics foundation built.")
