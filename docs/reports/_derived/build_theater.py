"""
Theater-level derived artifacts for the MENA cross-actor assessment.
Writes ONLY to the `analytics` schema; `public` stays read-only.

Builds (in dependency order):
  analytics.recipient_alias           alias -> canonical MENA recipient mapping
  analytics.initiative_ledger         canonical events at named-initiative grain w/ provenance
  analytics.recipient_blocs           empirical clustering of recipients by engagement profile
  analytics.relationship_changepoints binary-segmentation changepoints on monthly series
  analytics.narrative_themes          HDBSCAN clusters over canonical-event embeddings
  analytics.narrative_theme_summary   per-theme rollup (actors, recipients, top terms)
  analytics.geo_intensity             lat/long-gridded intensity (0.25 deg) per initiator

Deterministic: fixed seeds, sorted inputs. Requires: numpy, pandas, scikit-learn>=1.3.
Run: python docs/reports/_derived/build_theater.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json
import math
import numpy as np
import pandas as pd
from sqlalchemy import text
from shared.database.database import get_session

INITIATORS = ('China', 'Iran', 'Russia', 'Turkey')
MENA_CANON = ['Bahrain', 'Cyprus', 'Egypt', 'Iraq', 'Israel', 'Jordan', 'Kuwait', 'Lebanon',
              'Libya', 'Oman', 'Palestine', 'Qatar', 'Saudi Arabia', 'Syria',
              'United Arab Emirates', 'Yemen', 'Iran', 'Turkey']
ALIASES = {c: c for c in MENA_CANON}
ALIASES.update({
    'UAE': 'United Arab Emirates',
    'Palestinian Territories': 'Palestine',
    'Palestinian Authority': 'Palestine',
    'Gaza': 'Palestine',
    'Gaza Strip': 'Palestine',
    'West Bank': 'Palestine',
})
START, END = '2024-08-01', '2026-07-01'


# --------------------------------------------------------------------------- helpers
def canon_recipient(name: str):
    return ALIASES.get(name)


def binseg_changepoints(y, min_seg=3, max_cp=3, z_thresh=2.5):
    """Binary segmentation on a 1-D series; returns [(idx, pre_mean, post_mean, z)]."""
    y = np.asarray(y, dtype=float)
    found = []
    segments = [(0, len(y))]
    while len(found) < max_cp:
        best = None  # (z, t, a, b)
        for a, b in segments:
            if b - a < 2 * min_seg:
                continue
            for t in range(a + min_seg, b - min_seg + 1):
                left, right = y[a:t], y[t:b]
                n1, n2 = len(left), len(right)
                v1 = left.var(ddof=1) if n1 > 1 else 0.0
                v2 = right.var(ddof=1) if n2 > 1 else 0.0
                sp = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / max(n1 + n2 - 2, 1))
                if sp == 0:
                    continue
                z = abs(left.mean() - right.mean()) / (sp * math.sqrt(1 / n1 + 1 / n2))
                if best is None or z > best[0]:
                    best = (z, t, a, b)
        if best is None or best[0] < z_thresh:
            break
        z, t, a, b = best
        found.append((t, float(y[a:t].mean()), float(y[t:b].mean()), float(z)))
        segments.remove((a, b))
        segments += [(a, t), (t, b)]
    return sorted(found)


# --------------------------------------------------------------------------- 0. alias map
def build_alias(s):
    s.execute(text("DROP TABLE IF EXISTS analytics.recipient_alias CASCADE"))
    s.execute(text("CREATE TABLE analytics.recipient_alias (alias text PRIMARY KEY, canonical text NOT NULL)"))
    s.execute(text("INSERT INTO analytics.recipient_alias VALUES (:a, :c)"),
              [{"a": a, "c": c} for a, c in sorted(ALIASES.items())])
    s.commit()


# --------------------------------------------------------------------------- 1. initiative ledger
def build_initiative_ledger(s):
    """One row per canonical event (named initiative), MENA-scoped, with per-event provenance."""
    s.execute(text("DROP TABLE IF EXISTS analytics.initiative_ledger CASCADE"))
    s.execute(text(f"""
        CREATE TABLE analytics.initiative_ledger AS
        WITH event_docs AS (
            SELECT dem.canonical_event_id,
                   u.doc_id,
                   d.source_name,
                   d.source_geofocus,
                   ce.initiating_country
            FROM daily_event_mentions dem
            CROSS JOIN LATERAL unnest(dem.doc_ids) AS u(doc_id)
            JOIN documents d          ON d.doc_id = u.doc_id
            JOIN canonical_events ce  ON ce.id = dem.canonical_event_id
            WHERE ce.initiating_country IN :inits
        ),
        prov AS (
            SELECT canonical_event_id,
                   count(DISTINCT doc_id)                 AS linked_docs,
                   count(DISTINCT source_name)            AS distinct_sources,
                   count(DISTINCT doc_id) FILTER
                     (WHERE source_geofocus ILIKE '%' || initiating_country || '%') AS self_docs,
                   count(DISTINCT doc_id) FILTER
                     (WHERE source_geofocus IS NULL
                        OR source_geofocus NOT ILIKE '%' || initiating_country || '%') AS third_docs
            FROM event_docs
            GROUP BY canonical_event_id
        ),
        mena AS (
            SELECT ce.id AS canonical_event_id,
                   array_agg(DISTINCT ra.canonical ORDER BY ra.canonical) AS mena_recipients,
                   sum((ce.primary_recipients ->> k.key)::int)            AS mena_recipient_mentions
            FROM canonical_events ce
            CROSS JOIN LATERAL jsonb_object_keys(ce.primary_recipients) AS k(key)
            JOIN analytics.recipient_alias ra ON ra.alias = k.key
            WHERE ra.canonical <> ce.initiating_country
            GROUP BY ce.id
        )
        SELECT ce.id                                  AS event_id,
               ce.canonical_name,
               ce.initiating_country,
               ce.first_mention_date,
               ce.last_mention_date,
               (ce.last_mention_date - ce.first_mention_date + 1) AS span_days,
               ce.total_mention_days,
               ce.material_score,
               ce.total_articles,
               ce.primary_categories,
               m.mena_recipients,
               m.mena_recipient_mentions,
               coalesce(p.linked_docs, 0)             AS linked_docs,
               coalesce(p.distinct_sources, 0)        AS distinct_sources,
               coalesce(p.self_docs, 0)               AS self_docs,
               coalesce(p.third_docs, 0)              AS third_docs,
               round(coalesce(p.third_docs, 0)::numeric
                     / NULLIF(coalesce(p.linked_docs, 0), 0), 3) AS corroboration_share
        FROM canonical_events ce
        JOIN mena m  ON m.canonical_event_id = ce.id
        LEFT JOIN prov p ON p.canonical_event_id = ce.id
        WHERE ce.initiating_country IN :inits
          AND ce.first_mention_date >= :start
          AND ce.first_mention_date <  :end
    """).bindparams(inits=INITIATORS, start=START, end=END))
    s.execute(text("CREATE INDEX ix_il_actor ON analytics.initiative_ledger (initiating_country)"))
    s.execute(text("CREATE INDEX ix_il_score ON analytics.initiative_ledger (material_score DESC)"))
    s.commit()


# --------------------------------------------------------------------------- 2. recipient blocs
def build_recipient_blocs(s):
    """Cluster recipients by their who-engages-them-on-what profile (third-party volume)."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    df = pd.read_sql(text("""
        SELECT coalesce(ra.canonical, pi.recipient_country) AS recipient,
               pi.initiating_country, pi.category,
               sum(pi.third_party_docs) AS third_party_docs,
               sum(pi.raw_docs)         AS raw_docs
        FROM analytics.provenance_intensity pi
        LEFT JOIN analytics.recipient_alias ra ON ra.alias = pi.recipient_country
        GROUP BY 1, 2, 3
    """), s.connection())
    df['dim'] = df['initiating_country'] + ':' + df['category']
    mat = df.pivot_table(index='recipient', columns='dim',
                         values='third_party_docs', aggfunc='sum', fill_value=0)
    mat = mat.sort_index()
    totals = mat.sum(axis=1)
    profile = mat.div(totals.replace(0, 1), axis=0)   # share-of-profile, scale-free

    best = None
    X = profile.values
    for k in range(3, 7):
        model = AgglomerativeClustering(n_clusters=k, linkage='ward')
        labels = model.fit_predict(X)
        score = silhouette_score(X, labels)
        if best is None or score > best[0]:
            best = (score, k, labels)
    sil, k, labels = best

    rows = []
    for i, recip in enumerate(profile.index):
        prof = profile.iloc[i]
        top3 = prof.sort_values(ascending=False).head(3)
        rows.append({
            "recipient": recip,
            "bloc_id": int(labels[i]),
            "total_third_party_docs": int(totals.loc[recip]),
            "profile_top": json.dumps({d: round(float(v), 3) for d, v in top3.items()}),
            "profile_full": json.dumps({d: round(float(v), 4) for d, v in prof.items() if v > 0}),
        })

    s.execute(text("DROP TABLE IF EXISTS analytics.recipient_blocs CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.recipient_blocs (
            recipient text PRIMARY KEY,
            bloc_id int,
            total_third_party_docs int,
            profile_top jsonb,
            profile_full jsonb
        )
    """))
    s.execute(text("""
        INSERT INTO analytics.recipient_blocs
        VALUES (:recipient, :bloc_id, :total_third_party_docs,
                CAST(:profile_top AS jsonb), CAST(:profile_full AS jsonb))
    """), rows)
    s.execute(text(f"COMMENT ON TABLE analytics.recipient_blocs IS "
                   f"'Ward clustering on actor:category share-of-profile vectors; "
                   f"k={k} chosen by silhouette ({sil:.3f})'"))
    s.commit()
    return k, sil


# --------------------------------------------------------------------------- 3. changepoints
def build_changepoints(s):
    """Binary-segmentation changepoints per (initiator, recipient) monthly series."""
    df = pd.read_sql(text("""
        SELECT pi.initiating_country,
               coalesce(ra.canonical, pi.recipient_country) AS recipient,
               pi.month,
               sum(pi.third_party_docs) AS third_party_docs,
               sum(pi.raw_docs)         AS raw_docs
        FROM analytics.provenance_intensity pi
        LEFT JOIN analytics.recipient_alias ra ON ra.alias = pi.recipient_country
        GROUP BY 1, 2, 3
    """), s.connection())
    months = pd.date_range(START, '2026-06-01', freq='MS').date
    out = []
    for (init, recip), g in sorted(df.groupby(['initiating_country', 'recipient'])):
        for metric in ('third_party_docs', 'raw_docs'):
            series = g.set_index('month')[metric].reindex(months, fill_value=0).astype(float)
            if series.sum() < 50:      # too thin to segment meaningfully
                continue
            for idx, pre, post, z in binseg_changepoints(series.values):
                out.append({
                    "initiating_country": init, "recipient": recip, "metric": metric,
                    "cp_month": months[idx], "pre_mean": round(pre, 1),
                    "post_mean": round(post, 1),
                    "direction": 'surge' if post > pre else 'decline',
                    "magnitude": round(post / pre, 2) if pre > 0 else None,
                    "z_score": round(z, 2),
                })
    s.execute(text("DROP TABLE IF EXISTS analytics.relationship_changepoints CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.relationship_changepoints (
            initiating_country text, recipient text, metric text,
            cp_month date, pre_mean numeric, post_mean numeric,
            direction text, magnitude numeric, z_score numeric
        )
    """))
    if out:
        s.execute(text("""
            INSERT INTO analytics.relationship_changepoints
            VALUES (:initiating_country, :recipient, :metric, :cp_month,
                    :pre_mean, :post_mean, :direction, :magnitude, :z_score)
        """), out)
    s.commit()
    return len(out)


# --------------------------------------------------------------------------- 4. narrative themes
def build_narrative_themes(s):
    """Fine-grained KMeans over canonical-event embeddings -> latent campaign clusters.

    HDBSCAN collapses this corpus into one mega-cluster (news embeddings are a
    continuum); PCA(50) + KMeans(k ~ n/25) with a per-theme coherence score gives
    tight, deterministic campaign clusters instead.
    """
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.feature_extraction.text import TfidfVectorizer

    rows = s.execute(text("""
        SELECT il.event_id, ce.canonical_name, il.initiating_country,
               il.mena_recipients, il.material_score, il.first_mention_date,
               ce.embedding_vector
        FROM analytics.initiative_ledger il
        JOIN canonical_events ce ON ce.id = il.event_id
        WHERE ce.embedding_vector IS NOT NULL
        ORDER BY il.event_id
    """)).fetchall()
    if not rows:
        return 0, 0
    X = np.array([r[6] for r in rows], dtype=np.float32)
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)   # cosine geometry

    Xp = PCA(n_components=50, random_state=42).fit_transform(X)
    k = max(20, len(rows) // 25)
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(Xp)
    # coherence: mean cosine sim of members to their centroid (in PCA space)
    coherence = {}
    for t in range(k):
        members = Xp[labels == t]
        if len(members) == 0:
            continue
        c = km.cluster_centers_[t]
        sims = (members @ c) / (np.linalg.norm(members, axis=1) * np.linalg.norm(c) + 1e-9)
        coherence[t] = float(sims.mean())

    s.execute(text("DROP TABLE IF EXISTS analytics.narrative_themes CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.narrative_themes (
            event_id uuid PRIMARY KEY, theme_id int,
            canonical_name text, initiating_country text,
            mena_recipients text[], material_score numeric, first_mention_date date
        )
    """))
    s.execute(text("""
        INSERT INTO analytics.narrative_themes
        VALUES (CAST(:e AS uuid), :t, :n, :i, :r, :m, :d)
    """), [{"e": str(r[0]), "t": int(l), "n": r[1], "i": r[2],
            "r": r[3], "m": r[4], "d": r[5]} for r, l in zip(rows, labels)])

    # per-theme rollup with TF-IDF top terms from event names
    themes = {}
    for r, l in zip(rows, labels):
        themes.setdefault(int(l), []).append(r)
    stop = ['2024', '2025', '2026', 'new', 'meeting', 'visit', 'agreement', 'signing',
            'announcement', 'international', 'summit']
    summary_rows = []
    all_names = {t: [r[1] for r in rs] for t, rs in themes.items()}
    vec = TfidfVectorizer(stop_words='english', max_features=5000)
    corpus_keys = sorted(all_names)
    tf = vec.fit_transform([' '.join(all_names[t]) for t in corpus_keys])
    vocab = np.array(vec.get_feature_names_out())
    for row_i, t in enumerate(corpus_keys):
        rs = themes[t]
        scores = tf[row_i].toarray().ravel()
        order = np.argsort(-scores)
        terms = [w for w in vocab[order] if w not in stop][:6]
        actors, recips = {}, {}
        for r in rs:
            actors[r[2]] = actors.get(r[2], 0) + 1
            for rec in (r[3] or []):
                recips[rec] = recips.get(rec, 0) + 1
        summary_rows.append({
            "theme_id": t, "n_events": len(rs),
            "top_terms": json.dumps(terms),
            "actors": json.dumps(dict(sorted(actors.items(), key=lambda x: -x[1]))),
            "recipients": json.dumps(dict(sorted(recips.items(), key=lambda x: -x[1]))),
            "n_actors": len(actors), "n_recipients": len(recips),
            "avg_material": round(float(np.mean([float(r[4] or 0) for r in rs])), 2),
            "coherence": round(coherence.get(t, 0.0), 3),
            "first_date": min(r[5] for r in rs), "last_date": max(r[5] for r in rs),
        })
    s.execute(text("DROP TABLE IF EXISTS analytics.narrative_theme_summary CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.narrative_theme_summary (
            theme_id int PRIMARY KEY, n_events int, top_terms jsonb,
            actors jsonb, recipients jsonb, n_actors int, n_recipients int,
            avg_material numeric, coherence numeric, first_date date, last_date date
        )
    """))
    if summary_rows:
        s.execute(text("""
            INSERT INTO analytics.narrative_theme_summary
            VALUES (:theme_id, :n_events, CAST(:top_terms AS jsonb), CAST(:actors AS jsonb),
                    CAST(:recipients AS jsonb), :n_actors, :n_recipients,
                    :avg_material, :coherence, :first_date, :last_date)
        """), summary_rows)
    s.commit()
    return len(themes), 0


# --------------------------------------------------------------------------- 5. geo intensity
def build_geo_intensity(s):
    """Grid documents to 0.25 deg cells per initiator, with provenance split."""
    s.execute(text("DROP TABLE IF EXISTS analytics.geo_intensity CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.geo_intensity AS
        WITH pts AS (
            SELECT DISTINCT rb.doc_id, rb.initiating_country, rb.self_reported,
                   round((split_part(d.lat_long, ',', 1))::numeric * 4) / 4 AS lat,
                   round((split_part(d.lat_long, ',', 2))::numeric * 4) / 4 AS lon,
                   d.location
            FROM analytics.report_base rb
            JOIN documents d ON d.doc_id = rb.doc_id
            WHERE d.lat_long ~ '^-?[0-9]+(\\.[0-9]+)?,\\s*-?[0-9]+(\\.[0-9]+)?$'
        )
        SELECT initiating_country, lat, lon,
               count(DISTINCT doc_id)                                AS docs,
               count(DISTINCT doc_id) FILTER (WHERE NOT self_reported) AS third_party_docs,
               mode() WITHIN GROUP (ORDER BY location)               AS top_location
        FROM pts
        WHERE lat BETWEEN -60 AND 75 AND lon BETWEEN -180 AND 180
        GROUP BY 1, 2, 3
    """))
    s.execute(text("CREATE INDEX ix_geo_actor ON analytics.geo_intensity (initiating_country)"))
    s.commit()


# --------------------------------------------------------------------------- run
def report(s):
    q = lambda sql: s.execute(text(sql)).fetchall()
    print("initiative_ledger:", q("SELECT count(*) FROM analytics.initiative_ledger")[0][0],
          "| corroborated (share>=0.5, sources>=3):",
          q("SELECT count(*) FROM analytics.initiative_ledger WHERE corroboration_share>=0.5 AND distinct_sources>=3")[0][0])
    print("recipient_blocs:")
    for r in q("""SELECT bloc_id, array_agg(recipient ORDER BY total_third_party_docs DESC)
                  FROM analytics.recipient_blocs GROUP BY 1 ORDER BY 1"""):
        print("  bloc", r[0], "->", r[1])
    print("changepoints:", q("SELECT count(*) FROM analytics.relationship_changepoints")[0][0])
    print("top changepoints (third-party):")
    for r in q("""SELECT initiating_country, recipient, cp_month, direction, pre_mean, post_mean, z_score
                  FROM analytics.relationship_changepoints WHERE metric='third_party_docs'
                  ORDER BY z_score DESC LIMIT 8"""):
        print("  ", r)
    print("themes:", q("SELECT count(*) FROM analytics.narrative_theme_summary")[0][0],
          "| noise events:", q("SELECT count(*) FROM analytics.narrative_themes WHERE theme_id=-1")[0][0])
    print("cross-recipient themes (>=3 recipients):")
    for r in q("""SELECT theme_id, n_events, top_terms, actors, n_recipients
                  FROM analytics.narrative_theme_summary WHERE n_recipients>=3
                  ORDER BY n_events DESC LIMIT 8"""):
        print("  ", r)
    print("geo_intensity cells:", q("SELECT count(*) FROM analytics.geo_intensity")[0][0])


if __name__ == "__main__":
    with get_session() as s:
        build_alias(s);                 print("[1/6] recipient_alias built")
        build_initiative_ledger(s);     print("[2/6] initiative_ledger built")
        k, sil = build_recipient_blocs(s); print(f"[3/6] recipient_blocs built (k={k}, silhouette={sil:.3f})")
        n_cp = build_changepoints(s);   print(f"[4/6] relationship_changepoints built ({n_cp} changepoints)")
        n_t, n_noise = build_narrative_themes(s); print(f"[5/6] narrative_themes built ({n_t} themes, {n_noise} noise)")
        build_geo_intensity(s);         print("[6/6] geo_intensity built")
        report(s)
    print("\n[done] theater artifacts built.")
