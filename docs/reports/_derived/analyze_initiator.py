"""
Compute all stats + generate the 8 core charts for one initiator, dump stats.json.
Usage: python docs/reports/_derived/analyze_initiator.py China
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import pandas as pd
import rpt  # noqa  (same dir)

INITIATOR = sys.argv[1]
OUT = rpt.ROOT / INITIATOR.lower().replace(" ", "_")
OUT.mkdir(parents=True, exist_ok=True)
TRIGGERS = [("2024-09-01", "Israel-Hezbollah esc."), ("2024-12-08", "Assad falls"),
            ("2025-06-13", "Israel-Iran war")]


def J(df):  # dataframe -> records with native types
    return json.loads(df.to_json(orient="records"))


def main():
    i = INITIATOR
    stats = {"initiator": i}

    # --- signature: category share, this actor vs 4-actor avg ---------------
    sig = rpt.df("""
        WITH per AS (
          SELECT initiating_country, category, count(DISTINCT doc_id) docs
          FROM analytics.report_base GROUP BY 1,2),
        tot AS (SELECT initiating_country, sum(docs) t FROM per GROUP BY 1)
        SELECT p.category,
               max(CASE WHEN p.initiating_country=:i THEN round(100.0*p.docs/t.t,1) END) share,
               round(avg(100.0*p.docs/t.t),1) avg_share
        FROM per p JOIN tot t USING(initiating_country)
        GROUP BY p.category ORDER BY 2 DESC NULLS LAST
    """, i=i).fillna(0)
    stats["signature"] = J(sig)
    rpt.signature_radar(i, sig, f"{i}'s MENA influence signature", "category share of effort (%), vs 4-actor average")

    # --- subcategory pareto (corroborated docs) ----------------------------
    sub = rpt.df("""
        SELECT sc.subcategory,
               count(DISTINCT d.doc_id) FILTER (WHERE NOT (d.source_geofocus ILIKE '%'||:i||'%')) docs
        FROM documents d
        JOIN initiating_countries ic ON d.doc_id=ic.doc_id
        JOIN recipient_countries rc ON d.doc_id=rc.doc_id
        JOIN subcategories sc ON d.doc_id=sc.doc_id
        WHERE ic.initiating_country=:i
          AND rc.recipient_country IN ('Bahrain','Cyprus','Egypt','Iraq','Israel','Jordan','Kuwait','Lebanon','Libya','Oman','Palestine','Qatar','Saudi Arabia','Syria','United Arab Emirates','UAE','Yemen','Iran','Turkey')
          AND ic.initiating_country<>rc.recipient_country AND d.date>='2024-08-01'
          AND sc.subcategory NOT IN ('Economic','Social','Military','Diplomacy')
        GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 15
    """, i=i)
    stats["subcategories"] = J(sub)
    rpt.subcategory_pareto(i, sub, f"{i}: leading soft-power instruments", "top subcategories by third-party-corroborated documents")

    # --- recipient-level raw / third-party / share -------------------------
    rec = rpt.df("""
        SELECT recipient_country recipient,
               count(DISTINCT doc_id) raw,
               count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) third_party,
               round(count(DISTINCT doc_id) FILTER (WHERE NOT self_reported)::numeric
                     / NULLIF(count(DISTINCT doc_id),0),3) third_party_share
        FROM analytics.report_base WHERE initiating_country=:i
        GROUP BY 1 ORDER BY third_party DESC NULLS LAST
    """, i=i)
    rec["intensity"] = rec["third_party"]
    stats["recipients"] = J(rec)
    rpt.concentration_lorenz(i, rec, f"{i}: how concentrated is the MENA effort?",
                             "Lorenz curve of corroborated effort across recipients")
    rpt.provenance_quadrant(i, rec, f"{i}: narrative projection vs. genuine traction by recipient",
                            "raw volume vs. third-party-corroborated share")
    rpt.geo_bubble(i, rec, f"{i}: where the corroborated influence lands in MENA",
                   "bubble size = third-party-corroborated documents")

    # --- competitive heatmap (recipient x 4 actors, corroborated) ----------
    comp = rpt.df("""
        SELECT recipient_country recipient, initiating_country actor,
               count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
        FROM analytics.report_base GROUP BY 1,2
    """)
    mat = comp.pivot_table(index="recipient", columns="actor", values="tp", fill_value=0)
    mat = mat.reindex(columns=["China", "Iran", "Russia", "Turkey"], fill_value=0)
    mat = mat.loc[mat.sum(axis=1).sort_values(ascending=False).index]
    rpt.competitive_heatmap(i, mat, "Contested MENA terrain: corroborated effort by actor",
                            "third-party-corroborated documents (all four initiators)")
    stats["competition_matrix"] = J(mat.reset_index())

    # --- monthly timeline --------------------------------------------------
    ts = rpt.df("""
        SELECT month, count(DISTINCT doc_id) raw,
               count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) third_party
        FROM analytics.report_base WHERE initiating_country=:i GROUP BY 1 ORDER BY 1
    """, i=i)
    ts["month"] = pd.to_datetime(ts["month"])
    stats["timeline"] = json.loads(ts.assign(month=ts["month"].astype(str)).to_json(orient="records"))
    rpt.activity_timeline(i, ts, f"{i}: monthly MENA influence tempo", "raw vs. corroborated, with regional triggers", TRIGGERS)

    # --- entity network ----------------------------------------------------
    rpt.entity_network(i, top_n=40, finding=f"{i}: MENA influence actor network",
                       sub="top 40 entities by weighted degree; size = betweenness (brokers); color = community")

    # --- top entities, events, relationships (for prose) -------------------
    stats["top_entities"] = J(rpt.df("""
        SELECT ce.canonical_name name, ce.entity_type etype, ce.primary_role role,
               ce.total_documents docs, round(m.weighted_degree::numeric,0) wdeg
        FROM canonical_entities ce LEFT JOIN analytics.entity_graph_metrics m ON m.entity_id=ce.id
        WHERE ce.initiating_country=:i ORDER BY ce.total_documents DESC LIMIT 12
    """, i=i))
    stats["top_events"] = J(rpt.df("""
        SELECT event_name, period_type::text ptype, material_score,
               first_observed_date::text d0, last_observed_date::text d1,
               (narrative_summary->>'overview') overview
        FROM event_summaries
        WHERE initiating_country=:i AND material_score IS NOT NULL
        ORDER BY material_score DESC, last_observed_date DESC LIMIT 12
    """, i=i))
    stats["top_relationships"] = J(rpt.df("""
        SELECT ef.canonical_name a, et.canonical_name b, r.relationship_type rtype,
               r.co_occurrence_count w, left(r.relationship_description,200) descr
        FROM entity_relationships r
        JOIN canonical_entities ef ON ef.id=r.entity_from_id
        JOIN canonical_entities et ON et.id=r.entity_to_id
        WHERE ef.initiating_country=:i
        ORDER BY r.co_occurrence_count DESC LIMIT 10
    """, i=i))

    # provenance headline — distinct-document basis (summing the per-recipient
    # rows would count a multi-recipient doc once per recipient and inflate it)
    pr = rpt.df("""
        SELECT count(DISTINCT doc_id) raw,
               count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) third_party
        FROM analytics.report_base WHERE initiating_country=:i
    """, i=i).iloc[0]
    stats["provenance_headline"] = {
        "raw": int(pr["raw"]), "third_party": int(pr["third_party"]),
        "self_report_share": round(1 - pr["third_party"]/max(pr["raw"], 1), 3)}

    (OUT / "stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print(f"[{i}] stats.json + 8 charts written to {OUT}")
    print("  provenance:", stats["provenance_headline"])
    print("  top recipients (corroborated):", [f"{r['recipient']}={r['third_party']}" for r in stats['recipients'][:5]])


if __name__ == "__main__":
    main()
