"""Cross-actor CATEGORY report (5 actors). Generates 5 visuals + stats.json.
Usage: python docs/reports/_derived/analyze_category.py Economic"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
import rpt

CAT = sys.argv[1] if len(sys.argv) > 1 else "Economic"
ACTORS = ["China", "Iran", "Russia", "Turkey", "United States"]
RIVALS = ["China", "Iran", "Russia", "Turkey"]
OUT = rpt.ROOT / "by_category" / CAT.lower(); (OUT/"assets").mkdir(parents=True, exist_ok=True)
SUBS_BY_CAT = {
    "Economic": ('Trade','Infrastructure','Finance','Energy','Technology','Industrial',
                 'Raw Materials','Transportation','Tourism','Aid/Donation','Housing'),
    "Military": ('Sales','Joint Exercises','Training','Conferences','Support','Defense',
                 'Deployment','Cooperation','Aid/Donation'),
    "Social": ('Cultural','Education','Healthcare','Housing','Media','Politics','Religious',
               'Aid/Donation','Diaspora Engagement'),
    "Diplomacy": ('Multilateral/Bilateral Commitments','International Negotiations',
                  'Conflict Resolution','Global Governance Participation','Diaspora Engagement'),
}
ECON_SUBS = SUBS_BY_CAT.get(CAT, SUBS_BY_CAT["Economic"])
def J(d): return json.loads(d.to_json(orient="records"))
def save_local(fig, name, data=None):
    OUT_a = OUT/"assets"; fig.tight_layout(); fig.savefig(OUT_a/f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    if data is not None: data.to_csv(OUT_a/f"{name}.csv", index=False)


def main():
    stats = {"category": CAT}

    # --- 1. leaderboard: raw vs corroborated/registered per actor ---
    riv = rpt.df("""SELECT initiating_country actor, count(DISTINCT doc_id) raw,
        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) corroborated
        FROM analytics.report_base WHERE category=:c GROUP BY 1""", c=CAT)
    us = rpt.df("""SELECT 'United States' actor, count(DISTINCT doc_id) raw,
        count(DISTINCT doc_id) corroborated FROM analytics.us_report_base WHERE category=:c""", c=CAT)
    lb = pd.concat([riv, us]).set_index("actor").reindex(ACTORS).reset_index()
    stats["leaderboard"] = J(lb)
    d = lb.iloc[::-1]; y = np.arange(len(d)); h = 0.38
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(y+h/2, d["raw"], h, color="#ccc", label="raw")
    ax.barh(y-h/2, d["corroborated"], h, color=[rpt.PALETTE[a] for a in d["actor"]], label="corroborated/registered")
    for i, r in enumerate(d.itertuples()):
        ax.text(r.raw, y[i]+h/2, f" {int(r.raw):,}", va="center", fontsize=7.5, color="#777")
        ax.text(r.corroborated, y[i]-h/2, f" {int(r.corroborated):,}", va="center", fontsize=8, fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(d["actor"])
    rpt._title(ax, f"{CAT} influence leaderboard: raw vs. provenance-corrected",
               "corroborated = coverage excluding the actor's own state media (U.S.=registered, no self-media)")
    ax.set_xlabel("documents"); ax.legend(fontsize=8, loc="lower right")
    save_local(fig, "01_leaderboard", lb)

    # --- 2. instrument-mix stacked bar (cleaned econ subcats, corroborated/registered) ---
    def mix(actor, us=False):
        if us:
            sql = """SELECT scc.clean_label inst, count(DISTINCT d.doc_id) n
                FROM documents d JOIN initiating_countries ic ON d.doc_id=ic.doc_id
                JOIN recipient_countries rc ON d.doc_id=rc.doc_id JOIN categories c ON d.doc_id=c.doc_id
                JOIN subcategories sc ON d.doc_id=sc.doc_id JOIN analytics.subcat_clean scc ON scc.raw_label=sc.subcategory
                WHERE ic.initiating_country=:a AND c.category=:c AND ic.initiating_country<>rc.recipient_country
                AND d.date>='2024-08-01' AND scc.clean_label IN :subs
                GROUP BY 1"""
        else:
            sql = """SELECT scc.clean_label inst, count(DISTINCT d.doc_id) n
                FROM documents d JOIN initiating_countries ic ON d.doc_id=ic.doc_id
                JOIN recipient_countries rc ON d.doc_id=rc.doc_id JOIN categories c ON d.doc_id=c.doc_id
                JOIN subcategories sc ON d.doc_id=sc.doc_id JOIN analytics.subcat_clean scc ON scc.raw_label=sc.subcategory
                WHERE ic.initiating_country=:a AND c.category=:c AND ic.initiating_country<>rc.recipient_country
                AND d.date>='2024-08-01' AND scc.clean_label IN :subs
                AND NOT (d.source_geofocus ILIKE '%'||:a||'%') GROUP BY 1"""
        df = rpt.df(sql, a=actor, c=CAT, subs=ECON_SUBS)
        return df.set_index("inst")["n"]
    mixes = {a: mix(a, us=(a == "United States")) for a in ACTORS}
    mdf = pd.DataFrame(mixes).fillna(0)
    mdf = mdf.loc[mdf.sum(axis=1).sort_values(ascending=False).index]   # instruments by total
    share = mdf.div(mdf.sum(axis=0), axis=1) * 100
    stats["instrument_mix"] = json.loads(mdf.T.to_json(orient="index"))
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = np.zeros(len(ACTORS)); cmap = plt.get_cmap("tab20")
    for i, inst in enumerate(share.index):
        ax.bar(ACTORS, share.loc[inst], 0.6, bottom=bottom, label=inst, color=cmap(i % 20))
        bottom += share.loc[inst].values
    ax.set_ylabel("share of economic instruments (%)"); ax.set_ylim(0, 100)
    ax.set_title(f"{CAT} instrument mix: who builds what", fontsize=12, fontweight="bold", loc="left")
    ax.legend(fontsize=7.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    save_local(fig, "02_instrument_mix", mdf.reset_index())

    # --- 3. recipient heatmap (recipient x 5 actors) ---
    rr = rpt.df("""SELECT recipient_country recipient, initiating_country actor,
        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
        FROM analytics.report_base WHERE category=:c GROUP BY 1,2""", c=CAT)
    ru = rpt.df("""SELECT recipient_country recipient, count(DISTINCT doc_id) tp
        FROM analytics.us_report_base WHERE category=:c GROUP BY 1""", c=CAT)
    piv = rr.pivot_table(index="recipient", columns="actor", values="tp", fill_value=0)
    for a in RIVALS:
        if a not in piv: piv[a] = 0
    piv["United States"] = ru.set_index("recipient")["tp"]
    piv = piv.fillna(0)[["United States"]+RIVALS]
    piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).index].head(16)
    fig, ax = plt.subplots(figsize=(7, max(4, 0.42*len(piv))))
    im = ax.imshow(piv.values, cmap="magma", aspect="auto")
    ax.set_xticks(range(5)); ax.set_xticklabels(["U.S.","China","Iran","Russia","Turkey"])
    ax.set_yticks(range(len(piv))); ax.set_yticklabels(piv.index, fontsize=8)
    for i in range(len(piv)):
        for j in range(5):
            ax.text(j,i,f"{piv.values[i,j]:.0f}",ha="center",va="center",fontsize=6.5,
                    color="w" if piv.values[i,j]<piv.values.max()*0.6 else "k")
    ax.set_title(f"{CAT} contest by recipient (corroborated/registered docs)", fontsize=12, fontweight="bold", loc="left")
    fig.colorbar(im, ax=ax, shrink=0.7)
    save_local(fig, "03_recipient_heatmap", piv.reset_index())
    stats["recipient_leaders"] = J(rpt.df("""SELECT recipient_country recipient,
        (array_agg(initiating_country ORDER BY tp DESC))[1] leader, max(tp) n
        FROM (SELECT recipient_country, initiating_country, count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
        FROM analytics.report_base WHERE category=:c GROUP BY 1,2) z GROUP BY 1 ORDER BY n DESC""", c=CAT))

    # --- 4. megadeals: top material econ events with $ ---
    deals = rpt.df("""SELECT initiating_country actor, event_name, material_score,
        first_observed_date::text d0
        FROM event_summaries
        WHERE initiating_country IN ('China','Iran','Russia','Turkey','United States')
        AND jsonb_exists(count_by_category, :c) AND material_score IS NOT NULL
        AND (event_name ~ '\\$|[Bb]illion|[Mm]illion')
        ORDER BY material_score DESC, last_observed_date DESC LIMIT 60""", c=CAT)
    deals = rpt.dedupe_events(deals)            # drop near-duplicate event names
    stats["megadeals"] = J(deals.head(14))
    dd = deals.head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(range(len(dd)), dd["material_score"].astype(float), color=[rpt.PALETTE.get(a,"#888") for a in dd["actor"]])
    ax.set_yticks(range(len(dd)))
    ax.set_yticklabels([rpt.wrap_label(r.event_name, 50) for r in dd.itertuples()], fontsize=7.5)
    for i, r in enumerate(dd.itertuples()):
        ax.text(float(r.material_score), i, f" {r.actor[:3]} ({r.d0[:7]})", va="center", fontsize=7)
    ax.set_xlabel("material score (1-10)"); ax.set_xlim(0, 10.6)
    rpt._title(ax, f"Top {CAT} 'megadeals' by materiality (deduplicated)",
               "all top events score ~9/10 — read as a ranked list, not bar magnitude")
    save_local(fig, "04_megadeals", deals.head(14))

    # --- 5. Iran sanctions-mirage panel: raw vs corroborated econ by recipient ---
    im_df = rpt.df("""SELECT recipient_country recipient, count(DISTINCT doc_id) raw,
        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) corroborated
        FROM analytics.report_base WHERE initiating_country='Iran' AND category=:c
        GROUP BY 1 ORDER BY raw DESC""", c=CAT)
    im_df = im_df[im_df["raw"] > 30].head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 5)); y = np.arange(len(im_df)); h = 0.38
    ax.barh(y+h/2, im_df["raw"], h, color="#ccc", label="raw (Iranian-media-inflated)")
    ax.barh(y-h/2, im_df["corroborated"], h, color=rpt.PALETTE["Iran"], label="third-party corroborated")
    ax.set_yticks(y); ax.set_yticklabels(im_df["recipient"], fontsize=8)
    ax.set_title(f"Iran's {CAT.lower()} self-inflation: raw vs. corroborated, by recipient", fontsize=12, fontweight="bold", loc="left")
    ax.set_xlabel("documents"); ax.legend(fontsize=8)
    save_local(fig, "05_iran_mirage", im_df)

    (OUT/"stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print(f"[{CAT}] stats.json + 5 charts -> {OUT}")
    print("  leaderboard:", [(r["actor"], r["corroborated"]) for r in stats["leaderboard"]])
    print("  recipient leaders:", [(r["recipient"], r["leader"], r["n"]) for r in stats["recipient_leaders"][:8]])


if __name__ == "__main__":
    main()
