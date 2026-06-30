"""Cross-initiator RECIPIENT report. Generates 5 visuals + stats.json for one recipient.
Usage: python docs/reports/_derived/analyze_recipient.py "Saudi Arabia" """
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
import rpt

REC = sys.argv[1]
ACTORS = ["United States", "China", "Iran", "Russia", "Turkey"]
RIVALS = ["China", "Iran", "Russia", "Turkey"]
CATS = ["Economic", "Social", "Military", "Diplomacy"]
OUT = rpt.ROOT / "by_recipient" / REC.lower().replace(" ", "_"); (OUT/"assets").mkdir(parents=True, exist_ok=True)
TRIG = [("2024-09-01","Isr-Hez"),("2024-12-08","Assad falls"),("2025-06-13","Isr-Iran war")]
def J(d): return json.loads(d.to_json(orient="records"))
def sv(fig,name,data=None):
    fig.tight_layout(); fig.savefig(OUT/"assets"/f"{name}.png", bbox_inches="tight"); plt.close(fig)
    if data is not None: data.to_csv(OUT/"assets"/f"{name}.csv", index=False)


def main():
    st = {"recipient": REC}
    # per-initiator total + per category
    riv = rpt.df("""SELECT initiating_country actor, category,
        count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
        FROM analytics.report_base WHERE recipient_country=:r GROUP BY 1,2""", r=REC)
    us = rpt.df("""SELECT 'United States' actor, category, count(DISTINCT doc_id) tp
        FROM analytics.us_report_base WHERE recipient_country=:r GROUP BY 1,2""", r=REC)
    allc = pd.concat([riv, us])
    mat = allc.pivot_table(index="actor", columns="category", values="tp", fill_value=0)
    for c in CATS:
        if c not in mat: mat[c] = 0
    mat = mat.reindex(ACTORS, fill_value=0)[CATS]
    # leaderboard totals must be DISTINCT docs per initiator (NOT category-summed, which
    # double-counts multi-category docs). The matrix above stays category-level for the lane view.
    rt = rpt.df("""SELECT initiating_country actor, count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) tp
        FROM analytics.report_base WHERE recipient_country=:r GROUP BY 1""", r=REC)
    ut = rpt.df("""SELECT count(DISTINCT doc_id) tp FROM analytics.us_report_base WHERE recipient_country=:r""", r=REC)
    tser = {row.actor: int(row.tp) for row in rt.itertuples()}
    tser["United States"] = int(ut["tp"].iloc[0] or 0)
    totals = pd.Series(tser).reindex(ACTORS).fillna(0).astype(int).sort_values(ascending=False)
    st["totals"] = {a: int(totals.get(a, 0)) for a in ACTORS}
    grand = int(totals.sum()) or 1
    leader = totals.index[0]; top_share = totals.iloc[0]/grand
    second = totals.iloc[1]/grand if len(totals) > 1 else 0
    if top_share >= 0.45: hedge = f"single-patron ({leader}-dominated)"
    elif (totals.iloc[0] / max(totals.iloc[1],1)) <= 1.4: hedge = "contested"
    else: hedge = "balancing (multi-patron)"
    st["leader"] = leader; st["top_share"] = round(float(top_share),3); st["hedging"] = hedge

    # 1. suitor leaderboard
    d = totals.iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.barh(d.index, d.values, color=[rpt.PALETTE[a] for a in d.index])
    for i,(a,v) in enumerate(d.items()): ax.text(v, i, f" {int(v):,} ({100*v/grand:.0f}%)", va="center", fontsize=8)
    ax.set_xlim(0, totals.max()*1.18)
    rpt._title(ax, f"Who courts {REC}? Cross-initiator influence",
               "corroborated (rivals) / registered (U.S.) documents")
    sv(fig, "01_suitor_leaderboard", mat.reset_index())

    # 2. instrument matrix (initiator x category)
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    im = ax.imshow(mat.values, cmap="magma", aspect="auto")
    ax.set_xticks(range(4)); ax.set_xticklabels(CATS); ax.set_yticks(range(5)); ax.set_yticklabels([a.replace("United States","U.S.") for a in mat.index])
    for i in range(5):
        for j in range(4):
            ax.text(j,i,f"{mat.values[i,j]:.0f}",ha="center",va="center",fontsize=8,
                    color="w" if mat.values[i,j]<mat.values.max()*0.6 else "k")
    ax.set_title(f"{REC}: which lane each actor uses", fontsize=12, fontweight="bold", loc="left")
    fig.colorbar(im, ax=ax, shrink=0.7)
    sv(fig, "02_instrument_matrix", mat.reset_index())
    st["instrument_matrix"] = json.loads(mat.to_json(orient="index"))

    # 3. trajectory (monthly per initiator)
    rts = rpt.df("""SELECT month, initiating_country actor, count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) n
        FROM analytics.report_base WHERE recipient_country=:r GROUP BY 1,2""", r=REC)
    uts = rpt.df("""SELECT month, count(DISTINCT doc_id) n FROM analytics.us_report_base WHERE recipient_country=:r GROUP BY 1""", r=REC)
    fig, ax = plt.subplots(figsize=(9, 4.4))
    u = uts.copy(); u["month"]=pd.to_datetime(u["month"])
    ax.plot(u["month"], u["n"], color=rpt.PALETTE["United States"], lw=2.4, label="U.S.")
    for a in RIVALS:
        dd = rts[rts.actor==a].copy(); dd["month"]=pd.to_datetime(dd["month"])
        ax.plot(dd["month"], dd["n"], color=rpt.PALETTE[a], lw=1.5, label=a)
    for w,l in TRIG:
        ax.axvline(pd.Timestamp(w), color="#c33", ls=":", lw=1)
    ax.set_title(f"{REC}: who is gaining ground", fontsize=12, fontweight="bold", loc="left")
    ax.set_ylabel("docs / month"); ax.legend(fontsize=7.5, ncol=5, loc="upper center")
    sv(fig, "03_trajectory", uts)

    # 4. dominance share (single stacked bar)
    fig, ax = plt.subplots(figsize=(8, 1.8)); left=0
    for a in totals.index:
        sh = 100*totals[a]/grand
        ax.barh(0, sh, left=left, color=rpt.PALETTE[a], label=a)
        if sh > 5: ax.text(left+sh/2, 0, f"{a.replace('United States','U.S.')}\n{sh:.0f}%", ha="center", va="center", fontsize=8, color="w")
        left += sh
    ax.set_xlim(0,100); ax.set_yticks([]); ax.set_xlabel("share of external influence (%)")
    ax.set_title(f"{REC}: share of attention — {hedge}", fontsize=12, fontweight="bold", loc="left")
    sv(fig, "04_dominance_share", totals.reset_index().rename(columns={0:"docs","index":"actor"}))

    # 5. initiatives targeting this recipient — VALIDATED so the recipient is the PRIMARY
    # subject, not a peripheral mention. (Lebanon was tagged on "$17B aid to Israel" at 20% share;
    # we require recipient to be the rank-1 recipient, or hold >=40% of the event's recipient mentions.)
    cand = rpt.df("""SELECT initiating_country actor, event_name, material_score,
        first_observed_date::text d0, count_by_recipient cbr
        FROM event_summaries WHERE initiating_country IN ('China','Iran','Russia','Turkey','United States')
        AND jsonb_exists(count_by_recipient, :r) AND material_score IS NOT NULL
        ORDER BY material_score DESC, last_observed_date DESC LIMIT 120""", r=REC)
    # name aliases so a literal title match counts (strongest alignment signal)
    ALIAS = {"United Arab Emirates": ["united arab emirates", "uae"], "Saudi Arabia": ["saudi arabia", "saudi"],
             "Palestine": ["palestin", "gaza", "west bank"], "Lebanon": ["lebanon", "lebanese", "beirut"]}
    names = ALIAS.get(REC, [REC.lower()])
    def primary_aligned(cbr, event_name):
        nm = (event_name or "").lower()
        named = any(a in nm for a in names)                       # (a) recipient is in the title
        if not isinstance(cbr, dict) or not cbr:
            return named, 0.0
        vals = {k: v for k, v in cbr.items() if isinstance(v, (int, float))}
        tot = sum(vals.values()) or 1
        share = vals.get(REC, 0) / tot
        mx = max(vals.values()) if vals else 0
        strict_unique_max = vals.get(REC, 0) == mx and list(vals.values()).count(mx) == 1   # (c)
        # require REC to be an actual recipient (positive mention), then keep if titled about it,
        # OR it holds >=40% of mentions, OR it is the strict sole top recipient.
        if vals.get(REC, 0) <= 0:
            return False, round(share, 2)
        return (named or share >= 0.40 or strict_unique_max), round(share, 2)
    keep = []
    for row in cand.itertuples():
        ok, share = primary_aligned(row.cbr, row.event_name)
        if ok:
            keep.append({"actor": row.actor, "event_name": row.event_name,
                         "material_score": row.material_score, "d0": row.d0, "recipient_share": share})
    inits = pd.DataFrame(keep) if keep else pd.DataFrame(columns=["actor","event_name","material_score","d0","recipient_share"])
    inits = rpt.dedupe_events(inits).head(14)        # drop near-duplicate event names
    st["initiatives"] = J(inits)
    st["initiatives_dropped_peripheral"] = int(len(cand) - len(keep))
    if len(inits):
        dd = inits.head(12).iloc[::-1]
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(range(len(dd)), dd["material_score"].astype(float), color=[rpt.PALETTE.get(a,"#888") for a in dd["actor"]])
        ax.set_yticks(range(len(dd))); ax.set_yticklabels([rpt.wrap_label(e, 50) for e in dd["event_name"]], fontsize=7.5)
        for i,r_ in enumerate(dd.itertuples()): ax.text(float(r_.material_score), i, f" {r_.actor[:3]} ({r_.d0[:7]})", va="center", fontsize=7)
        ax.set_xlabel("material score (1-10)"); ax.set_xlim(0, 10.6)
        rpt._title(ax, f"Top initiatives targeting {REC} (primary-recipient validated)",
                   "events where this recipient is the subject — not peripheral mentions")
        sv(fig, "05_initiatives", inits)

    # adversarial framing (US vs Iran both present)
    if st["totals"]["United States"] > 100 and st["totals"]["Iran"] > 50:
        af = rpt.df("""SELECT round(100.0*count(DISTINCT doc_id) FILTER (WHERE framing='adversary')
            /NULLIF(count(DISTINCT doc_id),0),1) adv FROM analytics.us_report_base WHERE recipient_country=:r""", r=REC)
        st["us_adversary_framed_pct"] = float(af["adv"].iloc[0] or 0)

    st["top_entities"] = J(rpt.df("""SELECT canonical_name name, initiating_country actor, total_documents docs
        FROM canonical_entities WHERE :r = ANY(string_to_array(array_to_string(coalesce(country_affiliations,'{}'),','),','))
        ORDER BY total_documents DESC LIMIT 1""", r=REC)) if False else []
    (OUT/"stats.json").write_text(json.dumps(st, indent=2, default=str), encoding="utf-8")
    print(f"[{REC}] leader={leader} ({100*top_share:.0f}%) | {hedge}")
    print("   totals:", st["totals"])


if __name__ == "__main__":
    main()
