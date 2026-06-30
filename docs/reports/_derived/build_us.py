"""
US relational base: analytics.us_report_base — US-as-initiator scoped fact with FRAMING
classification (adversary / partner / neutral) instead of self_reported (US has 0 US-geofocus
outlets, so there is no self-projection signal). public stays read-only; writes go to analytics.

Run: python docs/reports/_derived/build_us.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
from shared.database.database import get_session
from sqlalchemy import text

MENA = ('Bahrain', 'Cyprus', 'Egypt', 'Iraq', 'Israel', 'Jordan', 'Kuwait', 'Lebanon',
        'Libya', 'Oman', 'Palestine', 'Qatar', 'Saudi Arabia', 'Syria',
        'United Arab Emirates', 'UAE', 'Yemen', 'Iran', 'Turkey')
# US-aligned recipients whose media counts as "partner" framing
PARTNER = ('Israel', 'Saudi Arabia', 'United Arab Emirates', 'UAE', 'Jordan', 'Egypt',
           'Bahrain', 'Kuwait', 'Qatar', 'Oman')


def build(s):
    s.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
    s.execute(text("DROP TABLE IF EXISTS analytics.us_report_base CASCADE"))
    partner_pred = " OR ".join([f"d.source_geofocus ILIKE '%{p}%'" for p in
                                ('Israel', 'Saudi Arabia', 'United Arab Emirates', 'Jordan',
                                 'Egypt', 'Bahrain', 'Kuwait', 'Qatar', 'Oman')])
    s.execute(text(f"""
        CREATE TABLE analytics.us_report_base AS
        SELECT
            d.doc_id, d.date, date_trunc('month', d.date)::date AS month,
            rc.recipient_country, c.category, d.source_name, d.source_geofocus,
            CASE
              WHEN d.source_geofocus ILIKE '%Iran%' THEN 'adversary'
              WHEN {partner_pred} THEN 'partner'
              ELSE 'neutral/other'
            END AS framing
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id = ic.doc_id
        JOIN recipient_countries  rc ON d.doc_id = rc.doc_id
        JOIN categories           c  ON d.doc_id = c.doc_id
        WHERE ic.initiating_country = 'United States'
          AND rc.recipient_country IN :m
          AND ic.initiating_country <> rc.recipient_country
          AND c.category IN ('Economic','Social','Military','Diplomacy')
          AND d.date >= '2024-08-01'
    """).bindparams(m=MENA))
    s.execute(text("CREATE INDEX ix_us_rc ON analytics.us_report_base (recipient_country, category)"))
    s.execute(text("CREATE INDEX ix_us_month ON analytics.us_report_base (month)"))
    s.commit()


def report(s):
    def q(sql): return s.execute(text(sql)).fetchall()
    print("us_report_base rows:", q("SELECT count(*) FROM analytics.us_report_base")[0][0])
    print("distinct US docs:", q("SELECT count(DISTINCT doc_id) FROM analytics.us_report_base")[0][0])
    print("\n== framing decomposition (distinct docs) ==")
    for r in q("""SELECT framing, count(DISTINCT doc_id) n,
                  round(100.0*count(DISTINCT doc_id)/sum(count(DISTINCT doc_id)) over (),1) pct
                  FROM analytics.us_report_base GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"  {r[0]:<14} {r[1]:>6,}  {r[2]}%")
    print("\n== adversary-framed share by recipient (top/bottom) ==")
    for r in q("""SELECT recipient_country,
                  count(DISTINCT doc_id) tot,
                  round(100.0*count(DISTINCT doc_id) FILTER (WHERE framing='adversary')
                        /count(DISTINCT doc_id),1) adv_pct
                  FROM analytics.us_report_base GROUP BY 1 HAVING count(DISTINCT doc_id)>300
                  ORDER BY adv_pct DESC"""):
        print(f"  {r[0]:<20} n={r[1]:>6,}  adversary-framed={r[2]}%")


if __name__ == "__main__":
    with get_session() as s:
        build(s)
        report(s)
    print("\n[done] analytics.us_report_base built.")
