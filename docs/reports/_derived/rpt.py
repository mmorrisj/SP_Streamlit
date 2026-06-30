"""
Reporting engine: palette, DB->DataFrame, and chart builders for the MENA influence reports.
Pure matplotlib/numpy/scipy (no networkx/plotly/geopandas). Each chart writes a PNG (>=150dpi)
and a sibling CSV of its underlying numbers for traceability.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from shared.database.database import get_session
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]            # docs/reports
PALETTE = {"China": "#C8102E", "Iran": "#1B7A3D", "Russia": "#1F4E9C", "Turkey": "#E08A1E",
           "United States": "#2B3A67"}
FRAMING_COL = {"adversary": "#B22222", "partner": "#2E7D32", "neutral/other": "#9e9e9e"}
PILLARS = ["Economic", "Social", "Military", "Diplomacy"]
plt.rcParams.update({"figure.dpi": 150, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.25, "axes.spines.top": False, "axes.spines.right": False})

# recipient centroids (approx lon, lat) for the bubble map
CENTROID = {
    "Egypt": (30.0, 26.8), "Iraq": (43.7, 33.2), "Israel": (34.9, 31.5), "Jordan": (36.2, 31.2),
    "Lebanon": (35.9, 33.9), "Syria": (38.0, 35.0), "Saudi Arabia": (45.1, 23.9),
    "United Arab Emirates": (54.0, 24.0), "Qatar": (51.2, 25.3), "Kuwait": (47.6, 29.3),
    "Bahrain": (50.6, 26.1), "Oman": (56.0, 21.5), "Yemen": (47.6, 15.6), "Libya": (17.2, 26.3),
    "Palestine": (35.2, 31.9), "Cyprus": (33.4, 35.1), "Iran": (53.7, 32.4), "Turkey": (35.2, 39.0),
}


def df(sql, **params):
    with get_session() as s:
        rows = s.execute(text(sql), params)
        return pd.DataFrame(rows.fetchall(), columns=list(rows.keys()))


def _assets(initiator):
    p = ROOT / initiator.lower().replace(" ", "_") / "assets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save(fig, initiator, name, data: pd.DataFrame = None):
    a = _assets(initiator)
    fig.tight_layout()
    fig.savefig(a / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    if data is not None:
        data.to_csv(a / f"{name}.csv", index=False)
    return f"assets/{name}.png"


def _title(ax, finding, sub=""):
    # stack finding (top) above subtitle (below) — both above the axes, never overlapping
    ax.set_title("")  # clear any default
    ax.text(0, 1.09, finding, transform=ax.transAxes, fontsize=12, fontweight="bold", va="bottom")
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=8, color="#555", va="bottom")

# public alias for the analyzers
titled = _title

from difflib import SequenceMatcher
def dedupe_events(df, name_col="event_name", thresh=0.78):
    """Drop near-duplicate event names (e.g. the same Hormoz nuclear deal spelled 4 ways)."""
    if df is None or len(df) == 0:
        return df
    kept, names = [], []
    for i, row in df.iterrows():
        nm = str(row[name_col]).lower().strip()
        if any(SequenceMatcher(None, nm, k).ratio() > thresh for k in names):
            continue
        names.append(nm); kept.append(i)
    return df.loc[kept]


def wrap_label(s, width=46):
    """Trim to a word boundary near width with an ellipsis (no mid-word cuts)."""
    s = str(s)
    if len(s) <= width:
        return s
    cut = s[:width].rsplit(" ", 1)[0]
    return cut + "…"

ETYPE_COLOR = {"PERSON": "#4C78A8", "ORGANIZATION": "#E45756", "COMPANY": "#F58518",
               "LOCATION": "#54A24B", "IMPLEMENTING_ORGANIZATION": "#E45756"}


# ---------------------------------------------------------------- 1. signature radar
def signature_radar(initiator, sig: pd.DataFrame, finding, sub):
    # sig: columns category, share (this actor), avg_share (all actors)
    cats = PILLARS
    vals = [float(sig.loc[sig.category == c, "share"].squeeze() or 0) for c in cats]
    avg = [float(sig.loc[sig.category == c, "avg_share"].squeeze() or 0) for c in cats]
    ang = np.linspace(0, 2*np.pi, len(cats), endpoint=False).tolist(); ang += ang[:1]
    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    for series, color, lab in [(vals, PALETTE[initiator], initiator), (avg, "#999", "4-actor avg")]:
        d = series + series[:1]
        ax.plot(ang, d, color=color, lw=2, label=lab); ax.fill(ang, d, color=color, alpha=0.12)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(cats); ax.set_yticklabels([])
    ax.set_title(finding, fontsize=12, fontweight="bold", pad=24)
    ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1), fontsize=8)
    return save(fig, initiator, "01_signature_radar", sig)


# ---------------------------------------------------------------- 2. subcategory pareto
def subcategory_pareto(initiator, sub_df: pd.DataFrame, finding, sub):
    d = sub_df.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(d["subcategory"], d["docs"], color=PALETTE[initiator])
    _title(ax, finding, sub); ax.set_xlabel("third-party-corroborated documents")
    return save(fig, initiator, "02_subcategory_pareto", sub_df)


# ---------------------------------------------------------------- 3. concentration lorenz
def concentration_lorenz(initiator, rec_df: pd.DataFrame, finding, sub):
    v = np.sort(rec_df["intensity"].values.astype(float))
    if v.sum() == 0: v = np.ones_like(v)
    cum = np.cumsum(v) / v.sum(); cum = np.insert(cum, 0, 0)
    x = np.linspace(0, 1, len(cum))
    hhi = float(((v / v.sum())**2).sum())
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="#bbb", label="perfect equality")
    ax.plot(x, cum, color=PALETTE[initiator], lw=2.5, label="recipient distribution")
    ax.fill_between(x, cum, x, color=PALETTE[initiator], alpha=0.1)
    _title(ax, finding, sub + f"  |  HHI={hhi:.3f}")
    ax.set_xlabel("share of recipients (cumulative)"); ax.set_ylabel("share of effort (cumulative)")
    ax.legend(loc="upper left", fontsize=8)
    out = rec_df.copy(); out["hhi"] = hhi
    return save(fig, initiator, "03_concentration_lorenz", out)


# ---------------------------------------------------------------- 4. provenance quadrant
def provenance_quadrant(initiator, rec_df: pd.DataFrame, finding, sub):
    # rec_df: recipient, raw, third_party_share
    d = rec_df[rec_df["raw"] > 0].copy()
    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.scatter(d["raw"], d["third_party_share"], s=70, color=PALETTE[initiator], alpha=0.8, zorder=3)
    for _, r in d.iterrows():
        ax.annotate(r["recipient"], (r["raw"], r["third_party_share"]), fontsize=7.5,
                    xytext=(4, 3), textcoords="offset points")
    ax.axhline(0.5, color="#bbb", ls="--", lw=1)
    med = d["raw"].median(); ax.axvline(med, color="#bbb", ls="--", lw=1)
    ax.set_xscale("log")
    ax.text(0.98, 0.02, "high volume,\nlow corroboration\n(narrative projection)", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=7.5, color="#a33")
    ax.text(0.98, 0.98, "high volume,\nhigh corroboration\n(genuine traction)", transform=ax.transAxes,
            ha="right", va="top", fontsize=7.5, color="#284")
    _title(ax, finding, sub)
    ax.set_xlabel("raw documents (log)"); ax.set_ylabel("third-party-corroborated share")
    ax.set_ylim(-0.05, 1.05)
    return save(fig, initiator, "04_provenance_quadrant", rec_df)


# ---------------------------------------------------------------- 5. competitive heatmap
def competitive_heatmap(initiator, mat: pd.DataFrame, finding, sub):
    # mat: index=recipient, columns=4 actors, values=normalized intensity (share within recipient)
    fig, ax = plt.subplots(figsize=(6.5, max(4, 0.42*len(mat))))
    im = ax.imshow(mat.values, cmap="magma", aspect="auto")
    ax.set_xticks(range(len(mat.columns))); ax.set_xticklabels(mat.columns)
    ax.set_yticks(range(len(mat.index))); ax.set_yticklabels(mat.index, fontsize=8)
    for i in range(len(mat.index)):
        for j in range(len(mat.columns)):
            ax.text(j, i, f"{mat.values[i,j]:.0f}", ha="center", va="center",
                    fontsize=7, color="w" if mat.values[i,j] < mat.values.max()*0.6 else "k")
    ax.set_title(finding, fontsize=12, fontweight="bold", loc="left")
    fig.colorbar(im, ax=ax, label="third-party-corroborated docs", shrink=0.7)
    return save(fig, initiator, "05_competitive_heatmap", mat.reset_index())


# ---------------------------------------------------------------- 6. geographic bubble map
def geo_bubble(initiator, rec_df: pd.DataFrame, finding, sub):
    d = rec_df[rec_df["intensity"] > 0].copy()
    d["lon"] = d["recipient"].map(lambda r: CENTROID.get(r, (np.nan, np.nan))[0])
    d["lat"] = d["recipient"].map(lambda r: CENTROID.get(r, (np.nan, np.nan))[1])
    d = d.dropna(subset=["lon", "lat"]).sort_values("intensity", ascending=False).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 6.5))
    sizes = 80 + 2200 * d["intensity"] / d["intensity"].max()
    ax.scatter(d["lon"], d["lat"], s=sizes, color=PALETTE[initiator], alpha=0.5, edgecolor="k", lw=0.5, zorder=2)
    # greedy label declutter: nudge labels that land too close to an already-placed one
    placed = []
    for i, r in d.iterrows():
        x, y = r["lon"], r["lat"]
        ly = y - 0.9 - 0.0016*sizes[i]**0.5   # default: just below the bubble
        for px, py in placed:
            if abs(px - x) < 4 and abs(py - ly) < 1.6:
                ly = py - 1.7                  # bump down to avoid the collision
        placed.append((x, ly))
        t = ax.annotate(f"{r['recipient']} {int(r['intensity']):,}", (x, ly), fontsize=6.8,
                        ha="center", va="top", zorder=4)
        t.set_path_effects([pe.withStroke(linewidth=2.2, foreground="white")])
    _title(ax, finding, sub); ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_xlim(14, 60); ax.set_ylim(10, 44)
    return save(fig, initiator, "06_geo_bubble", rec_df)


# ---------------------------------------------------------------- 7. activity timeline
def activity_timeline(initiator, ts: pd.DataFrame, finding, sub, triggers=None):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(ts["month"], ts["raw"], color="#bbb", lw=1.6, label="raw volume")
    ax.plot(ts["month"], ts["third_party"], color=PALETTE[initiator], lw=2.4, label="third-party corroborated")
    for when, lab in (triggers or []):
        ax.axvline(pd.Timestamp(when), color="#c33", ls=":", lw=1)
        ax.text(pd.Timestamp(when), ax.get_ylim()[1]*0.96, lab, rotation=90, fontsize=7,
                color="#c33", va="top", ha="right")
    _title(ax, finding, sub); ax.set_ylabel("documents / month"); ax.legend(fontsize=8)
    return save(fig, initiator, "07_activity_timeline", ts)


# ---------------------------------------------------------------- 8. entity network
def _betweenness(nodes, edges):
    # Brandes' algorithm (unweighted) on a small subgraph
    from collections import defaultdict, deque
    g = defaultdict(set)
    for a, b in edges:
        g[a].add(b); g[b].add(a)
    bc = {n: 0.0 for n in nodes}
    for s in nodes:
        S, P, sigma, d = [], defaultdict(list), defaultdict(float), defaultdict(lambda: -1)
        sigma[s] = 1.0; d[s] = 0; Q = deque([s])
        while Q:
            v = Q.popleft(); S.append(v)
            for w in g[v]:
                if d[w] < 0:
                    d[w] = d[v] + 1; Q.append(w)
                if d[w] == d[v] + 1:
                    sigma[w] += sigma[v]; P[w].append(v)
        delta = defaultdict(float)
        while S:
            w = S.pop()
            for v in P[w]:
                delta[v] += (sigma[v]/sigma[w]) * (1 + delta[w])
            if w != s:
                bc[w] += delta[w]
    return bc


def entity_network(initiator, top_n=40, finding="", sub=""):
    nodes_df = df("""
        SELECT ce.id::text id, ce.canonical_name name, ce.entity_type etype,
               m.weighted_degree wdeg, m.component_id comp
        FROM analytics.entity_graph_metrics m
        JOIN canonical_entities ce ON ce.id = m.entity_id
        WHERE ce.initiating_country = :i
        ORDER BY m.weighted_degree DESC LIMIT :n
    """, i=initiator, n=top_n)
    keep = set(nodes_df["id"])
    edges_df = df("""
        SELECT entity_from_id::text a, entity_to_id::text b, co_occurrence_count w
        FROM entity_relationships
        WHERE entity_from_id::text IN :k AND entity_to_id::text IN :k
    """, k=tuple(keep) or ("",))
    edges = [(r.a, r.b) for r in edges_df.itertuples()]
    bc = _betweenness(list(keep), edges)
    nodes_df["betweenness"] = nodes_df["id"].map(bc).fillna(0)

    # Fruchterman-Reingold layout (numpy)
    ids = list(nodes_df["id"]); idx = {e: i for i, e in enumerate(ids)}; n = len(ids)
    rng = np.random.default_rng(42); pos = rng.random((n, 2))
    A = np.zeros((n, n))
    for a, b in edges:
        if a in idx and b in idx: A[idx[a], idx[b]] = A[idx[b], idx[a]] = 1
    k = 1/np.sqrt(max(n, 1))
    for _ in range(220):
        disp = np.zeros((n, 2))
        for i in range(n):
            d = pos[i] - pos; dist = np.linalg.norm(d, axis=1); dist[i] = 1
            rep = (k*k)/dist
            disp[i] += (d.T/dist * rep).T.sum(0)
            con = A[i] > 0; dd = np.linalg.norm(pos[i]-pos[con], axis=1)+1e-6
            disp[i] -= ((pos[i]-pos[con]).T/dd * (dd*dd/k)).T.sum(0)
        ln = np.linalg.norm(disp, axis=1); ln[ln == 0] = 1
        pos += (disp.T/ln*np.minimum(ln, 0.05)).T
        pos = np.clip(pos, 0, 1)

    import matplotlib.patches as mpatches
    fig, ax = plt.subplots(figsize=(9, 8))
    for a, b in edges:
        if a in idx and b in idx:
            ax.plot(*zip(pos[idx[a]], pos[idx[b]]), color="#ddd", lw=0.6, zorder=1)
    bcv = nodes_df["betweenness"].values
    sizes = 60 + 1200*(bcv/ (bcv.max() or 1))
    for i, row in enumerate(nodes_df.itertuples()):
        ax.scatter(*pos[i], s=sizes[i], color=ETYPE_COLOR.get(row.etype, "#888"),
                   alpha=0.9, edgecolor="k", lw=0.4, zorder=2)
    # label the top brokers/hubs (offset, with white halo for legibility)
    top = nodes_df.sort_values("betweenness", ascending=False).head(14)
    for row in top.itertuples():
        i = idx[row.id]
        t = ax.annotate(row.name, pos[i], fontsize=7.5, fontweight="bold", zorder=3,
                        xytext=(4, 4), textcoords="offset points")
        t.set_path_effects([pe.withStroke(linewidth=2.2, foreground="white")])
    types = [t for t in ["PERSON", "ORGANIZATION", "COMPANY", "LOCATION"] if (nodes_df["etype"] == t).any()]
    ax.legend(handles=[mpatches.Patch(color=ETYPE_COLOR[t], label=t.title()) for t in types],
              fontsize=8, loc="lower right", title="entity type")
    _title(ax, finding, "top 40 entities by weighted degree; node size = betweenness (brokers); color = entity type")
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    return save(fig, initiator, "08_entity_network",
                nodes_df[["name", "etype", "wdeg", "betweenness", "comp"]])


# ============================ US RELATIONAL CHARTS ============================
def tug_of_war(initiator, d, finding, sub):
    # d: recipient, us, rival, rival_name  -> diverging bar (US left, leading rival right)
    d = d.sort_values("us", ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(4, 0.42*len(d))))
    y = range(len(d))
    ax.barh(y, -d["us"], color=PALETTE["United States"], label="United States")
    colors = [PALETTE.get(rn, "#888") for rn in d["rival_name"]]
    ax.barh(y, d["rival"], color=colors)
    ax.set_yticks(list(y)); ax.set_yticklabels(d["recipient"], fontsize=8)
    for i, (_, r) in enumerate(d.iterrows()):
        ax.text(-r["us"]-max(d["us"])*0.01, i, f"{int(r['us']):,}", ha="right", va="center", fontsize=7)
        ax.text(r["rival"]+max(d["rival"])*0.01, i, f"{r['rival_name'][:3]} {int(r['rival']):,}",
                ha="left", va="center", fontsize=7)
    ax.axvline(0, color="k", lw=0.8)
    xmax = max(d["us"].max(), d["rival"].max())*1.25
    ax.set_xlim(-xmax, xmax); ax.set_xticks([])
    _title(ax, finding, sub)
    ax.text(0.01, 0.01, "◄ U.S.", transform=ax.transAxes, color=PALETTE["United States"], fontsize=9, fontweight="bold")
    ax.text(0.99, 0.01, "leading rival ►", transform=ax.transAxes, ha="right", color="#888", fontsize=9, fontweight="bold")
    return save(fig, initiator, "02_tug_of_war", d)


def hedging_scatter(initiator, d, finding, sub):
    # d: recipient, us, rivals_sum
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    ax.scatter(d["us"], d["rivals_sum"], s=70, color=PALETTE["United States"], alpha=0.85, zorder=3)
    for _, r in d.iterrows():
        ax.annotate(r["recipient"], (r["us"], r["rivals_sum"]), fontsize=7.5, xytext=(4, 3), textcoords="offset points")
    lim = max(d["us"].max(), d["rivals_sum"].max())*1.1
    ax.plot([0, lim], [0, lim], "--", color="#bbb", lw=1)
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.text(0.98, 0.02, "U.S.-anchored", transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color=PALETTE["United States"])
    ax.text(0.02, 0.98, "rival-leaning", transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#a33")
    ax.text(0.62, 0.6, "hedging\n(engages both)", transform=ax.transAxes, fontsize=8, color="#666", rotation=45)
    _title(ax, finding, sub)
    ax.set_xlabel("U.S. registered coverage"); ax.set_ylabel("combined rival corroborated coverage")
    return save(fig, initiator, "03_hedging_scatter", d)


def framing_stack(initiator, d, finding, sub):
    # d: recipient, adversary, partner, neutral  (counts) ; sorted by adversary share
    d = d.copy(); tot = d[["adversary", "partner", "neutral"]].sum(axis=1).replace(0, 1)
    for c in ["adversary", "partner", "neutral"]:
        d[c+"_p"] = 100*d[c]/tot
    d = d.sort_values("adversary_p", ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(4, 0.42*len(d))))
    y = range(len(d)); left = [0]*len(d)
    for c, lab, col in [("adversary_p", "adversary (Iran media)", FRAMING_COL["adversary"]),
                        ("partner_p", "partner (Gulf/Israel media)", FRAMING_COL["partner"]),
                        ("neutral_p", "neutral/other", FRAMING_COL["neutral/other"])]:
        ax.barh(list(y), d[c], left=left, color=col, label=lab)
        left = [l+v for l, v in zip(left, d[c])]
    ax.set_yticks(list(y)); ax.set_yticklabels(d["recipient"], fontsize=8)
    ax.set_xlim(0, 100); ax.set_xlabel("share of U.S. coverage (%)")
    _title(ax, finding, sub)
    ax.legend(fontsize=7.5, loc="lower right", ncol=1)
    return save(fig, initiator, "04_framing_stack", d)


def target_bar(initiator, d, finding, sub):
    # d: actor, docs  -> who targets the US
    d = d.sort_values("docs", ascending=True)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.barh(d["actor"], d["docs"], color=[PALETTE.get(a, "#888") for a in d["actor"]])
    for i, (_, r) in enumerate(d.iterrows()):
        ax.text(r["docs"], i, f" {int(r['docs']):,}", va="center", fontsize=8)
    _title(ax, finding, sub); ax.set_xlabel("documents directed at the U.S. as recipient")
    return save(fig, initiator, "05_target_bar", d)
