"""US relational analysis vs China/Iran/Russia/Turkey. Generates 8 comparative visuals + stats.json.
Run: python docs/reports/_derived/analyze_us.py"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
import rpt

I = "United States"
OUT = rpt.ROOT / "united_states"; (OUT/"assets").mkdir(parents=True, exist_ok=True)
RIVALS = ["China", "Iran", "Russia", "Turkey"]
TRIG = [("2024-09-01","Isr-Hez esc."),("2024-12-08","Assad falls"),("2025-06-13","Isr-Iran war")]
def J(d): return json.loads(d.to_json(orient="records"))


def main():
    stats = {"initiator": I}

    # signature: US vs 4-actor avg (US from us_report_base; rivals from report_base)
    us_sig = rpt.df("""SELECT category, count(DISTINCT doc_id) docs FROM analytics.us_report_base GROUP BY 1""")
    us_tot = us_sig["docs"].sum()
    us_sig["share"] = (100*us_sig["docs"]/us_tot).round(1)
    riv = rpt.df("""WITH per AS (SELECT initiating_country, category, count(DISTINCT doc_id) docs
                    FROM analytics.report_base GROUP BY 1,2),
                    tot AS (SELECT initiating_country, sum(docs) t FROM per GROUP BY 1)
                    SELECT category, round(avg(100.0*docs/t),1) avg_share
                    FROM per JOIN tot USING(initiating_country) GROUP BY 1""")
    sig = us_sig.merge(riv, on="category", how="outer").fillna(0)
    stats["signature"] = J(sig[["category","share","avg_share"]])
    rpt.signature_radar(I, sig, "U.S. registers as almost pure diplomacy/security",
                        "category share (%) — U.S. vs 4-actor average (selection-shaped)")

    # per-recipient: US registered vs each rival third_party
    us_rec = rpt.df("""SELECT recipient_country recipient, count(DISTINCT doc_id) us
                       FROM analytics.us_report_base GROUP BY 1""")
    riv_rec = rpt.df("""SELECT recipient_country recipient, initiating_country actor,
                        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
                        FROM analytics.report_base GROUP BY 1,2""")
    piv = riv_rec.pivot_table(index="recipient", columns="actor", values="tp", fill_value=0)
    for a in RIVALS:
        if a not in piv: piv[a] = 0
    piv = piv[RIVALS]
    m = us_rec.set_index("recipient").join(piv, how="outer").fillna(0)
    m["rivals_sum"] = m[RIVALS].sum(axis=1)
    m["rival"] = m[RIVALS].max(axis=1)
    m["rival_name"] = m[RIVALS].idxmax(axis=1)
    m = m.reset_index()
    stats["recipients"] = J(m)

    tug = m[m["us"] > 100][["recipient","us","rival","rival_name"]].copy()
    rpt.tug_of_war(I, tug, "U.S. vs. its leading rival, by recipient",
                   "U.S. registered coverage vs. the strongest rival's corroborated coverage")
    rpt.hedging_scatter(I, m[m["us"]>50][["recipient","us","rivals_sum"]].copy(),
                        "Alignment geometry: U.S.-anchored vs. hedging vs. rival-leaning",
                        "U.S. registered coverage vs. combined rival coverage, per recipient")

    # framing decomposition by recipient
    fr = rpt.df("""SELECT recipient_country recipient,
        count(DISTINCT doc_id) FILTER (WHERE framing='adversary') adversary,
        count(DISTINCT doc_id) FILTER (WHERE framing='partner') partner,
        count(DISTINCT doc_id) FILTER (WHERE framing='neutral/other') neutral
        FROM analytics.us_report_base GROUP BY 1
        HAVING count(DISTINCT doc_id)>300""")
    stats["framing_by_recipient"] = J(fr)
    rpt.framing_stack(I, fr, "Whose lens? The U.S.'s image by who is reporting it",
                      "share of U.S. coverage: adversary (Iran) / partner (Gulf-Israel) / neutral")

    # US as target
    tgt = rpt.df("""SELECT ic.initiating_country actor, count(DISTINCT d.doc_id) docs
        FROM documents d JOIN initiating_countries ic ON d.doc_id=ic.doc_id
        JOIN recipient_countries rc ON d.doc_id=rc.doc_id
        WHERE rc.recipient_country='United States' AND ic.initiating_country IN ('China','Iran','Russia','Turkey')
        AND d.date>='2024-08-01' GROUP BY 1""")
    stats["us_as_target"] = J(tgt)
    rpt.target_bar(I, tgt, "The U.S. as object: who aims influence AT Washington",
                   "Iran's anti-U.S. messaging dominates inbound coverage")

    # head-to-head heatmap (recipient x 5 actors)
    mat = m.set_index("recipient")[["us"]+RIVALS].rename(columns={"us":"United States"})
    mat = mat.loc[mat.sum(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(7, max(4,0.42*len(mat))))
    im = ax.imshow(mat.values, cmap="magma", aspect="auto")
    ax.set_xticks(range(len(mat.columns))); ax.set_xticklabels(["U.S.","China","Iran","Russia","Turkey"])
    ax.set_yticks(range(len(mat.index))); ax.set_yticklabels(mat.index, fontsize=8)
    for i in range(len(mat.index)):
        for j in range(len(mat.columns)):
            ax.text(j,i,f"{mat.values[i,j]:.0f}",ha="center",va="center",fontsize=6.5,
                    color="w" if mat.values[i,j]<mat.values.max()*0.6 else "k")
    ax.set_title("Five-actor contest for MENA: registered coverage by recipient", fontsize=12, fontweight="bold", loc="left")
    fig.colorbar(im, ax=ax, label="registered / corroborated docs", shrink=0.7)
    rpt.save(fig, I, "06_head_to_head", mat.reset_index())

    # timeline vs rivals
    us_ts = rpt.df("""SELECT month, count(DISTINCT doc_id) n FROM analytics.us_report_base GROUP BY 1 ORDER BY 1""")
    riv_ts = rpt.df("""SELECT month, initiating_country actor,
        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) n FROM analytics.report_base GROUP BY 1,2 ORDER BY 1""")
    fig, ax = plt.subplots(figsize=(9,4.6))
    us_ts["month"]=pd.to_datetime(us_ts["month"])
    ax.plot(us_ts["month"], us_ts["n"], color=rpt.PALETTE[I], lw=2.6, label="United States")
    for a in RIVALS:
        d=riv_ts[riv_ts.actor==a].copy(); d["month"]=pd.to_datetime(d["month"])
        ax.plot(d["month"], d["n"], color=rpt.PALETTE[a], lw=1.4, alpha=0.8, label=a)
    for w,l in TRIG:
        ax.axvline(pd.Timestamp(w), color="#c33", ls=":", lw=1)
        ax.text(pd.Timestamp(w), ax.get_ylim()[1]*0.97, l, rotation=90, fontsize=7, color="#c33", va="top", ha="right")
    ax.set_title("U.S. tempo tracks the conflict files, on a different rhythm than rivals", fontsize=12, fontweight="bold", loc="left")
    ax.set_ylabel("documents / month"); ax.legend(fontsize=7.5, ncol=5, loc="upper center")
    rpt.save(fig, I, "07_timeline_vs_rivals", us_ts)

    # entity network
    rpt.entity_network(I, top_n=40, finding="U.S. MENA actor network (as it registers in coverage)",
                       sub="top 40 entities by weighted degree; size = betweenness; color = community")

    # prose stats
    stats["framing_overall"] = J(rpt.df("""SELECT framing, count(DISTINCT doc_id) n,
        round(100.0*count(DISTINCT doc_id)/sum(count(DISTINCT doc_id)) over(),1) pct
        FROM analytics.us_report_base GROUP BY 1 ORDER BY 2 DESC"""))
    stats["top_entities"] = J(rpt.df("""SELECT ce.canonical_name name, ce.entity_type etype, ce.primary_role role,
        ce.total_documents docs FROM canonical_entities ce WHERE ce.initiating_country=:i
        ORDER BY ce.total_documents DESC LIMIT 12""", i=I))
    stats["top_events"] = J(rpt.df("""SELECT event_name, material_score, first_observed_date::text d0,
        (narrative_summary->>'overview') overview FROM event_summaries
        WHERE initiating_country=:i AND material_score IS NOT NULL
        ORDER BY material_score DESC, last_observed_date DESC LIMIT 12""", i=I))
    (OUT/"stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print("[US] stats.json + 8 charts written")
    print("  framing:", [(r["framing"],r["pct"]) for r in stats["framing_overall"]])
    print("  US-anchored vs rival-leaning recipients:")
    for r in sorted(stats["recipients"], key=lambda x:-x["us"])[:8]:
        lead = "US" if r["us"]>r["rival"] else r["rival_name"]
        print(f"    {r['recipient']:<20} US={int(r['us']):>6,} topRival={r['rival_name']}={int(r['rival']):>6,}  -> {lead}")


if __name__ == "__main__":
    main()
