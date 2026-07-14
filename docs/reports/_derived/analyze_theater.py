"""
Theater-level visual set for the MENA cross-actor assessment.
Reads analytics.* (built by build_analytics.py / build_theater.py); writes PNGs (150 dpi)
+ sibling CSVs to docs/reports/mena_theater/assets/.

Deterministic: sorted inputs, no randomness. Charts plot CORROBORATED metrics
(third-party docs / gated initiatives); raw volume appears only as contrast.
Run: python docs/reports/_derived/analyze_theater.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from sqlalchemy import text
from shared.database.database import get_session

ASSETS = Path(__file__).resolve().parents[1] / 'mena_theater' / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)

ACTORS = ['China', 'Iran', 'Russia', 'Turkey']
C = {'China': '#C8102E', 'Iran': '#1B7A3D', 'Russia': '#1F4E9C', 'Turkey': '#E08A1E'}
SURFACE, INK, MUTED = '#fcfcfb', '#222222', '#777777'
TRIGGERS = [('2024-12-01', 'Assad falls'), ('2025-06-01', 'Iran–Israel war'),
            ('2025-10-01', 'Gaza ceasefire')]

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'axes.edgecolor': '#dddddd', 'axes.linewidth': 0.8, 'axes.grid': True,
    'grid.color': '#e8e8e6', 'grid.linewidth': 0.6, 'font.size': 10,
    'axes.titlesize': 12.5, 'axes.titleweight': 'bold', 'axes.titlelocation': 'left',
    'text.color': INK, 'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'xtick.labelsize': 9, 'ytick.labelsize': 9, 'legend.frameon': False,
})


def save(fig, name, df=None, subtitle=None):
    if subtitle:
        fig.text(0.01, 0.005, subtitle, fontsize=8, color=MUTED, ha='left')
    fig.savefig(ASSETS / f'{name}.png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    if df is not None:
        df.to_csv(ASSETS / f'{name}.csv', index=False)
    print(f'  wrote {name}.png' + (' + csv' if df is not None else ''))


def despine(ax):
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)


# ---------------------------------------------------------------- data pulls
def pull(s):
    d = {}
    d['pi'] = pd.read_sql(text("""
        SELECT pi.initiating_country, coalesce(ra.canonical, pi.recipient_country) AS recipient,
               pi.category, pi.month,
               sum(pi.raw_docs) raw_docs, sum(pi.third_party_docs) third_party_docs,
               sum(pi.self_reported_docs) self_docs, sum(pi.distinct_sources) sources
        FROM analytics.provenance_intensity pi
        LEFT JOIN analytics.recipient_alias ra ON ra.alias = pi.recipient_country
        GROUP BY 1,2,3,4
    """), s.connection())
    d['ledger'] = pd.read_sql(text("""
        SELECT event_id, canonical_name, initiating_country, first_mention_date,
               last_mention_date, span_days, material_score::float AS material_score,
               mena_recipients, linked_docs, distinct_sources, third_docs,
               corroboration_share::float AS corroboration_share
        FROM analytics.initiative_ledger
    """), s.connection())
    d['blocs'] = pd.read_sql(text("SELECT * FROM analytics.recipient_blocs"), s.connection())
    d['cps'] = pd.read_sql(text("""
        SELECT * FROM analytics.relationship_changepoints WHERE metric='third_party_docs'
    """), s.connection())
    d['themes'] = pd.read_sql(text("""
        SELECT theme_id, n_events, top_terms, actors, recipients, n_actors, n_recipients,
               avg_material::float avg_material, coherence::float coherence, first_date, last_date
        FROM analytics.narrative_theme_summary
    """), s.connection())
    d['geo'] = pd.read_sql(text("""
        SELECT initiating_country, lat::float lat, lon::float lon, docs, third_party_docs, top_location
        FROM analytics.geo_intensity
    """), s.connection())
    return d


# ---------------------------------------------------------------- 01 provenance quadrant
def fig01(d):
    pair = d['pi'].groupby(['initiating_country', 'recipient'], as_index=False).agg(
        raw=('raw_docs', 'sum'), third=('third_party_docs', 'sum'))
    pair = pair[pair.raw >= 200].copy()
    pair['corr_share'] = pair.third / pair.raw
    fig, ax = plt.subplots(figsize=(9, 6.5))
    for a in ACTORS:
        g = pair[pair.initiating_country == a]
        ax.scatter(g.raw, g.corr_share, s=55, color=C[a], alpha=0.85, edgecolor=SURFACE,
                   linewidth=1.5, label=a, zorder=3)
    ax.set_xscale('log')
    ax.axhline(0.5, color='#bbbbbb', lw=1, ls='--', zorder=1)
    ax.text(ax.get_xlim()[1] * 0.9, 0.94, 'genuine traction', ha='right', fontsize=9,
            color=MUTED, style='italic')
    ax.text(ax.get_xlim()[1] * 0.9, 0.04, 'narrative projection', ha='right', fontsize=9,
            color=MUTED, style='italic')
    big = pair.sort_values('raw', ascending=False).head(14)
    placed = []   # collision-aware: stack labels of near-coincident points downward
    for _, r in big.iterrows():
        lx, dy = np.log10(r.raw), 6
        for plx, py, pdy in placed:
            if abs(lx - plx) < 0.09 and abs(r.corr_share - py) < 0.035 and dy >= pdy:
                dy = pdy - 11
        placed.append((lx, r.corr_share, dy))
        ax.annotate(r.recipient, (r.raw, r.corr_share), textcoords='offset points',
                    xytext=(6, dy), fontsize=8, color=INK)
    ax.set_xlabel('raw media volume (docs, log scale)')
    ax.set_ylabel('third-party-corroborated share')
    ax.set_ylim(-0.03, 1.03)
    ax.set_title("Iran's relationships cluster in the projection zone; Turkey, Russia and China are externally carried")
    ax.legend(loc='center left', ncol=1, fontsize=9)
    despine(ax)
    save(fig, '01_provenance_quadrant', pair.sort_values(['initiating_country', 'recipient']),
         'Each dot = one initiator→recipient relationship (raw ≥200 docs). y = share of coverage NOT from the initiator\'s own media. 2024-08→2026-06.')


# ---------------------------------------------------------------- 02 leaderboard
def fig02(d):
    ag = d['pi'].groupby('initiating_country', as_index=False).agg(
        raw=('raw_docs', 'sum'), third=('third_party_docs', 'sum'))
    ag['self_share'] = 1 - ag.third / ag.raw
    ag = ag.sort_values('third')
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    y = np.arange(len(ag))
    ax.barh(y, ag.raw, height=0.62, color='#e3e3e0', zorder=2, label='raw volume')
    ax.barh(y, ag.third, height=0.62, color=[C[a] for a in ag.initiating_country], zorder=3,
            label='third-party-corroborated')
    for i, r in enumerate(ag.itertuples()):
        ax.text(r.third + ag.raw.max() * 0.01, i, f'{r.third:,.0f}', va='center', fontsize=9,
                color=INK, fontweight='bold', zorder=4)
        ax.text(r.raw + ag.raw.max() * 0.01, i - 0.28,
                f'raw {r.raw:,.0f} · self-reported {r.self_share:.0%}', va='center',
                fontsize=7.5, color=MUTED, zorder=4)
    ax.set_yticks(y, ag.initiating_country)
    ax.set_xlabel('distinct documents, MENA scope')
    ax.set_title('Turkey leads corroborated volume; Iran posts 2× the raw volume but 85% is its own media')
    ax.legend(loc='upper right', fontsize=9)
    despine(ax)
    save(fig, '02_corroborated_leaderboard', ag,
         'Distinct docs per initiator across MENA recipients, 2024-08→2026-06. Colored bar = coverage not from the initiator\'s own media ecosystem.')


# ---------------------------------------------------------------- 03 initiative gate
def fig03(d):
    L = d['ledger']
    rows = []
    for a in ACTORS:
        g = L[L.initiating_country == a]
        gate = g[(g.corroboration_share >= 0.5) & (g.distinct_sources >= 3)]
        rows.append({'actor': a, 'total': len(g), 'corroborated': len(gate),
                     'high_material': len(gate[gate.material_score >= 6])})
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    x = np.arange(len(df))
    w = 0.27
    ax.bar(x - w, df.total, w, color='#e3e3e0', label='all extracted initiatives')
    ax.bar(x, df.corroborated, w, color=[C[a] for a in df.actor], alpha=0.55,
           label='corroborated (≥50% third-party, ≥3 outlets)')
    ax.bar(x + w, df.high_material, w, color=[C[a] for a in df.actor],
           label='corroborated + high-material (score ≥6)')
    for i, r in df.iterrows():
        ax.text(i - w, r.total + 20, f'{r.total:,}', ha='center', fontsize=8, color=MUTED)
        ax.text(i, r.corroborated + 20, f'{r.corroborated:,}', ha='center', fontsize=8, color=INK)
        ax.text(i + w, r.high_material + 20, f'{r.high_material:,}', ha='center', fontsize=8.5,
                color=INK, fontweight='bold')
    ax.set_xticks(x, df.actor)
    ax.set_ylabel('distinct canonical initiatives')
    ax.set_title('The corroboration gate: what survives when initiatives need independent, multi-outlet coverage')
    ax.legend(fontsize=8.5)
    despine(ax)
    save(fig, '03_initiative_gate', df,
         'Canonical events (named initiatives) per initiator, MENA scope 2024-08→2026-06, from analytics.initiative_ledger.')


# ---------------------------------------------------------------- 04 category signature
def fig04(d):
    cat = d['pi'].groupby(['initiating_country', 'category'], as_index=False).agg(
        third=('third_party_docs', 'sum'))
    cat['share'] = cat.third / cat.groupby('initiating_country').third.transform('sum')
    order = ['Diplomacy', 'Economic', 'Social', 'Military']
    fig, axes = plt.subplots(1, 4, figsize=(11.5, 3.4), sharex=True)
    for ax, a in zip(axes, ACTORS):
        g = cat[cat.initiating_country == a].set_index('category').reindex(order).fillna(0)
        y = np.arange(len(order))[::-1]
        ax.barh(y, g['share'], height=0.6, color=C[a])
        for yi, v in zip(y, g['share']):
            ax.text(v + 0.015, yi, f'{v:.0%}', va='center', fontsize=8.5, color=INK)
        ax.set_yticks(y, order if a == ACTORS[0] else ['', '', '', ''])
        ax.set_title(a, color=C[a], fontsize=11, loc='center')
        ax.set_xlim(0, 0.9)
        ax.xaxis.set_major_formatter(lambda v, _: f'{v:.0%}')
        despine(ax)
    fig.suptitle('Four influence signatures: everyone leads with diplomacy — the differences are in the second instrument',
                 x=0.01, ha='left', fontsize=12.5, fontweight='bold')
    fig.subplots_adjust(top=0.8)
    save(fig, '04_category_signature', cat.sort_values(['initiating_country', 'category']),
         'Share of each actor\'s third-party-corroborated docs by category, MENA scope 2024-08→2026-06.')


# ---------------------------------------------------------------- 05 competitive heatmap by bloc
def fig05(d):
    pair = d['pi'].groupby(['initiating_country', 'recipient'], as_index=False).agg(
        third=('third_party_docs', 'sum'))
    mat = pair.pivot_table(index='recipient', columns='initiating_country', values='third',
                           fill_value=0)
    blocs = d['blocs'].set_index('recipient')['bloc_id']
    mat = mat.loc[[r for r in mat.index if r in blocs.index]]
    mat['bloc'] = blocs
    mat['tot'] = mat[ACTORS].sum(axis=1)
    mat = mat.sort_values(['bloc', 'tot'], ascending=[True, False])
    fig, ax = plt.subplots(figsize=(7.4, 8.2))
    vals = mat[ACTORS].values.astype(float)
    im = ax.imshow(np.log1p(vals), cmap='Purples', aspect='auto')
    ax.set_xticks(range(4), ACTORS)
    ax.set_yticks(range(len(mat)), mat.index)
    for i in range(len(mat)):
        for j in range(4):
            v = vals[i, j]
            ax.text(j, i, f'{v:,.0f}', ha='center', va='center', fontsize=7.5,
                    color='white' if np.log1p(v) > np.log1p(vals).max() * 0.6 else INK)
    prev = None
    for i, b in enumerate(mat.bloc):
        if prev is not None and b != prev:
            ax.axhline(i - 0.5, color=INK, lw=1.4)
        prev = b
    bloc_names = {0: 'Bloc A', 1: 'Bloc B', 2: 'Bloc C'}
    for b in sorted(mat.bloc.unique()):
        rows = np.where(mat.bloc == b)[0]
        ax.text(3.65, rows.mean(), bloc_names.get(b, f'Bloc {b}'), rotation=90, va='center',
                fontsize=9, color=MUTED)
    ax.set_title('Contested vs. owned terrain: corroborated intensity by recipient,\nrows grouped by empirical engagement-profile bloc')
    ax.grid(False)
    df = mat.reset_index()[['recipient', 'bloc'] + ACTORS]
    save(fig, '05_competitive_heatmap', df,
         'Third-party-corroborated docs per initiator→recipient, 2024-08→2026-06; color = log scale; blocs from ward clustering of engagement profiles.')


# ---------------------------------------------------------------- 06 syria substitution
def fig06(d):
    g = d['pi'][d['pi'].recipient == 'Syria'].groupby(
        ['initiating_country', 'month'], as_index=False).agg(third=('third_party_docs', 'sum'))
    months = pd.date_range('2024-08-01', '2026-06-01', freq='MS').date
    fig, ax = plt.subplots(figsize=(9.6, 5))
    for a in ACTORS:
        ser = g[g.initiating_country == a].set_index('month').third.reindex(months, fill_value=0)
        ser = ser.rolling(2, min_periods=1).mean()
        ax.plot(pd.to_datetime(list(months)), ser.values, color=C[a], lw=2, label=a)
        if a == 'Turkey':   # only the separated line gets an end label; legend covers the rest
            ax.annotate(a, (pd.to_datetime(months[-1]), ser.values[-1]), xytext=(8, 0),
                        textcoords='offset points', color=C[a], fontsize=9, fontweight='bold',
                        va='center')
    ax.axvline(pd.to_datetime('2024-12-08'), color=INK, lw=1, ls='--')
    ax.text(pd.to_datetime('2024-12-15'), ax.get_ylim()[1] * 0.95, 'Assad falls (Dec 8, 2024)',
            fontsize=9, color=INK)
    ax.set_ylabel('third-party-corroborated docs / month (2-mo avg)')
    ax.set_title('The Syria handoff: Turkey inherits the file after Assad falls; Iran collapses, Russia fades')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ax.legend(fontsize=9, loc='upper left')
    despine(ax)
    save(fig, '06_syria_substitution', g.sort_values(['initiating_country', 'month']),
         'Monthly third-party-corroborated docs, recipient = Syria, 2-month rolling mean.')


# ---------------------------------------------------------------- 07 tempo + changepoints
def fig07(d):
    tot = d['pi'].groupby(['initiating_country', 'month'], as_index=False).agg(
        third=('third_party_docs', 'sum'))
    months = pd.date_range('2024-08-01', '2026-06-01', freq='MS').date
    cps = d['cps'].sort_values('z_score', ascending=False)
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 6.6), sharex=True)
    for ax, a in zip(axes.ravel(), ACTORS):
        ser = tot[tot.initiating_country == a].set_index('month').third.reindex(months, fill_value=0)
        x = pd.to_datetime(list(months))
        ax.fill_between(x, ser.values, color=C[a], alpha=0.18)
        ax.plot(x, ser.values, color=C[a], lw=2)
        for tdate, tlabel in TRIGGERS:
            ax.axvline(pd.to_datetime(tdate), color='#bbbbbb', lw=0.9, ls=':')
        top = cps[cps.initiating_country == a].head(3)
        for k, (_, r) in enumerate(top.iterrows()):
            xm = pd.to_datetime(r.cp_month)
            yv = ser.reindex([r.cp_month]).fillna(0).values[0]
            ax.plot([xm], [yv], marker='v' if r.direction == 'decline' else '^',
                    color=INK, ms=7, zorder=5)
            dx = 4 if k % 2 == 0 else -4
            ax.annotate(f'{r.recipient} {"▼" if r.direction == "decline" else "▲"}',
                        (xm, yv), xytext=(dx, 10 + 16 * k), textcoords='offset points',
                        fontsize=7.5, ha='left' if dx > 0 else 'right')
        ax.set_title(a, color=C[a], loc='center', fontsize=11)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
        despine(ax)
    for ax in axes[:, 0]:
        ax.set_ylabel('corroborated docs/mo')
    fig.suptitle('Tempo and inflections: statistically detected changepoints (▲ surge ▼ decline) against the trigger calendar',
                 x=0.01, ha='left', fontsize=12.5, fontweight='bold')
    fig.subplots_adjust(top=0.88, hspace=0.35)
    save(fig, '07_tempo_changepoints', cps,
         'Monthly third-party-corroborated docs per actor (theater total). Dotted lines: Assad falls, Iran–Israel war, Gaza ceasefire. Markers: top per-recipient changepoints (|z|≥2.5).')


# ---------------------------------------------------------------- 08 geo bubble
def fig08(d):
    g = d['geo'][(d['geo'].lat.between(12, 43)) & (d['geo'].lon.between(-10, 62))].copy()
    g = g[g.third_party_docs > 0]
    fig, ax = plt.subplots(figsize=(10.5, 7))
    for a in ACTORS:
        gg = g[g.initiating_country == a]
        ax.scatter(gg.lon, gg.lat, s=np.sqrt(gg.third_party_docs) * 6, color=C[a], alpha=0.45,
                   edgecolor=SURFACE, linewidth=0.5, label=a)
    top = g.sort_values('third_party_docs', ascending=False).drop_duplicates(
        subset=['top_location']).head(14)
    for _, r in top.iterrows():
        label = re.split(r'[;,]', str(r.top_location))[0][:22]
        ax.annotate(label, (r.lon, r.lat), xytext=(5, 4), textcoords='offset points',
                    fontsize=8, color=INK)
    ax.set_xlabel('longitude')
    ax.set_ylabel('latitude')
    ax.set_title('Where influence lands: corroborated activity by located event site (0.25° cells)')
    handles = [Line2D([], [], marker='o', ls='', color=C[a], label=a, ms=9, alpha=0.6)
               for a in ACTORS]
    ax.legend(handles=handles, fontsize=9, loc='lower left')
    despine(ax)
    save(fig, '08_geo_bubble',
         g.sort_values(['initiating_country', 'third_party_docs'], ascending=[True, False]),
         'Bubble area ∝ third-party-corroborated docs at each 0.25° cell (97.7% of docs carry lat/long). MENA extent only.')


# ---------------------------------------------------------------- 09 lorenz + hhi
def fig09(d):
    pair = d['pi'].groupby(['initiating_country', 'recipient'], as_index=False).agg(
        third=('third_party_docs', 'sum'))
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    rows = []
    for a in ACTORS:
        v = np.sort(pair[pair.initiating_country == a].third.values)
        cum = np.insert(np.cumsum(v), 0, 0) / v.sum()
        xs = np.linspace(0, 1, len(cum))
        share = v / v.sum()
        hhi = float((share ** 2).sum())
        ax.plot(xs, cum, color=C[a], lw=2, label=f'{a}  (HHI {hhi:.2f})')
        rows.append({'actor': a, 'hhi': round(hhi, 3), 'n_recipients': len(v),
                     'top_recipient_share': round(float(share.max()), 3)})
    ax.plot([0, 1], [0, 1], color='#cccccc', lw=1, ls='--')
    ax.set_xlabel('cumulative share of recipients (poorest-engaged first)')
    ax.set_ylabel('cumulative share of corroborated volume')
    ax.set_title('Doc-level concentration flatters focus: on the initiative basis all four actors are similarly spread')
    ax.legend(fontsize=9.5)
    despine(ax)
    save(fig, '09_concentration_lorenz', pd.DataFrame(rows),
         'Lorenz/HHI over third-party docs. Caveat: Russia\'s Iran spike is ~78% Iran recipient-side media; initiative-level HHI is nearly flat (~0.11–0.12) across actors.')


# ---------------------------------------------------------------- 10 initiative ledger top
def fig10(d):
    L = d['ledger']
    gate = L[(L.corroboration_share >= 0.5) & (L.distinct_sources >= 3)].copy()
    gate['rank_key'] = gate.material_score * np.log1p(gate.distinct_sources)
    top = gate.sort_values('rank_key', ascending=False).drop_duplicates(
        subset=['canonical_name']).head(18).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10.5, 7.6))
    y = np.arange(len(top))
    ax.barh(y, top.material_score, height=0.62,
            color=[C[a] for a in top.initiating_country])
    for i, r in enumerate(top.itertuples()):
        nm = (r.canonical_name[:70] + '…') if len(r.canonical_name) > 70 else r.canonical_name
        ax.text(0.15, i, nm, va='center', fontsize=8, color='white', fontweight='bold')
        ax.text(r.material_score + 0.08, i,
                f'{r.distinct_sources} outlets · {r.first_mention_date:%b %y}', va='center',
                fontsize=7.5, color=MUTED)
    ax.set_yticks([])
    ax.set_xlabel('material score (LLM-assessed, 1–10)')
    ax.set_xlim(0, 11.5)
    handles = [Line2D([], [], marker='s', ls='', color=C[a], label=a, ms=9) for a in ACTORS]
    ax.legend(handles=handles, fontsize=9, loc='lower right')
    ax.set_title('The theater\'s highest-substance corroborated initiatives (≥50% third-party, ≥3 outlets)')
    despine(ax)
    save(fig, '10_initiative_ledger',
         top.iloc[::-1][['canonical_name', 'initiating_country', 'first_mention_date',
                         'material_score', 'distinct_sources', 'corroboration_share',
                         'mena_recipients']],
         'Ranked by material_score × log(outlets), deduplicated by name. From analytics.initiative_ledger.')


# ---------------------------------------------------------------- 11 narrative themes
def fig11(d):
    t = d['themes']
    t = t[(t.n_recipients >= 4) & (t.n_events >= 10) & (t.coherence >= 0.5)].copy()

    def label(row):
        terms = [w for w in row.top_terms if not re.search(r'[؀-ۿ]', w)][:4]
        return ' · '.join(terms)

    t['label'] = t.apply(label, axis=1)
    t['dominant'] = t.actors.apply(lambda a: max(a, key=a.get))
    # rank by cluster tightness — coherent clusters are campaign-like, not generic buckets
    t = t.sort_values('coherence', ascending=False).head(14).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10.2, 6.4))
    y = np.arange(len(t))
    ax.hlines(y, 0, t.n_recipients, color='#dddddd', lw=1.2, zorder=2)
    ax.scatter(t.n_recipients, y, s=t.n_events * 12, color=[C.get(x, '#888') for x in t.dominant],
               alpha=0.85, edgecolor=SURFACE, linewidth=1.2, zorder=3)
    for i, r in enumerate(t.itertuples()):
        ax.text(r.n_recipients + 0.6, i, f'{r.n_events} events', va='center', fontsize=8,
                color=MUTED)
    ax.set_yticks(y, t.label, fontsize=8.5)
    ax.set_xlabel('distinct MENA recipients the campaign touches')
    ax.set_xlim(0, t.n_recipients.max() + 4)
    handles = [Line2D([], [], marker='o', ls='', color=C[a], label=a, ms=9) for a in ACTORS]
    ax.legend(handles=handles, fontsize=9, loc='lower right', title='dominant actor',
              title_fontsize=9)
    ax.set_title('Coordinated campaigns: the tightest semantic initiative families spanning ≥4 recipients')
    despine(ax)
    save(fig, '11_narrative_themes',
         t.iloc[::-1][['theme_id', 'label', 'dominant', 'n_events', 'n_recipients',
                       'coherence', 'avg_material', 'first_date', 'last_date']],
         'KMeans clusters over canonical-event embeddings (coherence ≥0.5, ≥10 events, ≥4 recipients; top 14 by coherence). Bubble area ∝ events.')


if __name__ == '__main__':
    with get_session() as s:
        d = pull(s)
    for fn in (fig01, fig02, fig03, fig04, fig05, fig06, fig07, fig08, fig09, fig10, fig11):
        fn(d)
    print('\n[done] theater visuals written to', ASSETS)
