"""
Derived entity/event/source artifacts in the `analytics` schema (public stays read-only).

Builds:
  analytics.source_provenance_map   per source_name: geofocus + provenance class vs each initiator
  analytics.event_entities          fills the empty event_summaries.entities_mentioned gap
  analytics.entity_graph_metrics    degree, weighted_degree, component_id, cross_recipient_reach

Network betweenness is computed on small per-actor subgraphs at chart time (no networkx here).
Run: python docs/reports/_derived/build_entities.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from collections import defaultdict
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shared.database.database import get_session
from sqlalchemy import text

INITIATORS = ('China', 'Iran', 'Russia', 'Turkey')


def build_source_map(s):
    s.execute(text("DROP TABLE IF EXISTS analytics.source_provenance_map CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.source_provenance_map AS
        SELECT source_name,
               mode() WITHIN GROUP (ORDER BY source_geofocus) AS dominant_geofocus,
               count(*) AS docs
        FROM documents
        WHERE source_name IS NOT NULL
        GROUP BY source_name
    """))
    s.commit()


def build_event_entities(s):
    # associated_event_ids is empty; link entities -> event_summaries via shared doc_ids
    # (daily_entity_mentions.doc_ids  <->  event_source_links.doc_id).
    s.execute(text("DROP TABLE IF EXISTS analytics.event_entities CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.event_entities AS
        SELECT DISTINCT
            esl.event_summary_id     AS event_id,
            dem.canonical_entity_id  AS entity_id,
            ce.canonical_name,
            ce.entity_type,
            ce.primary_role,
            ce.initiating_country
        FROM daily_entity_mentions dem
        CROSS JOIN LATERAL unnest(dem.doc_ids) AS d(doc_id)
        JOIN event_source_links esl ON esl.doc_id = d.doc_id
        JOIN canonical_entities ce  ON ce.id = dem.canonical_entity_id
    """))
    s.execute(text("CREATE INDEX ix_ee_event ON analytics.event_entities (event_id)"))
    s.execute(text("CREATE INDEX ix_ee_entity ON analytics.event_entities (entity_id)"))
    s.commit()


def build_graph_metrics(s):
    rows = s.execute(text("""
        SELECT entity_from_id::text, entity_to_id::text, co_occurrence_count
        FROM entity_relationships
    """)).fetchall()
    ids = sorted({r[0] for r in rows} | {r[1] for r in rows})
    idx = {e: i for i, e in enumerate(ids)}
    n = len(ids)
    deg = defaultdict(int)
    wdeg = defaultdict(float)
    I, J = [], []
    for a, b, w in rows:
        deg[a] += 1; deg[b] += 1
        wdeg[a] += (w or 1); wdeg[b] += (w or 1)
        I += [idx[a], idx[b]]; J += [idx[b], idx[a]]
    if n:
        adj = coo_matrix((np.ones(len(I)), (I, J)), shape=(n, n))
        ncomp, labels = connected_components(adj, directed=False)
    else:
        ncomp, labels = 0, []
    # cross-recipient reach from canonical_entities.primary_recipients JSONB
    reach = dict(s.execute(text("""
        SELECT id::text, coalesce(jsonb_object_keys_count(primary_recipients),0)
        FROM (SELECT id, primary_recipients FROM canonical_entities) z
    """)).fetchall()) if False else {}
    # simpler: count keys in primary_recipients
    rr = s.execute(text("""
        SELECT id::text,
               (SELECT count(*) FROM jsonb_object_keys(primary_recipients)) AS k
        FROM canonical_entities WHERE primary_recipients IS NOT NULL
    """)).fetchall()
    reach = {r[0]: int(r[1]) for r in rr}

    s.execute(text("DROP TABLE IF EXISTS analytics.entity_graph_metrics CASCADE"))
    s.execute(text("""
        CREATE TABLE analytics.entity_graph_metrics (
            entity_id uuid PRIMARY KEY,
            degree int, weighted_degree double precision,
            component_id int, cross_recipient_reach int
        )
    """))
    comp = {ids[i]: int(labels[i]) for i in range(n)}
    payload = [{"e": e, "d": deg[e], "w": float(wdeg[e]),
                "c": comp.get(e, -1), "r": reach.get(e, 0)} for e in ids]
    s.execute(text("""
        INSERT INTO analytics.entity_graph_metrics
        VALUES (CAST(:e AS uuid), :d, :w, :c, :r)
    """), payload)
    s.commit()
    return n, len(rows), ncomp


def report(s):
    def q(sql): return s.execute(text(sql)).fetchall()
    print("source_provenance_map rows:", q("SELECT count(*) FROM analytics.source_provenance_map")[0][0])
    print("event_entities rows:", q("SELECT count(*) FROM analytics.event_entities")[0][0],
          "| distinct events:", q("SELECT count(DISTINCT event_id) FROM analytics.event_entities")[0][0])
    print("entity_graph_metrics rows:", q("SELECT count(*) FROM analytics.entity_graph_metrics")[0][0])
    print("\n== top hub entities by weighted degree ==")
    for r in q("""SELECT ce.canonical_name, ce.initiating_country, m.degree, round(m.weighted_degree::numeric,0)
                  FROM analytics.entity_graph_metrics m JOIN canonical_entities ce ON ce.id=m.entity_id
                  WHERE ce.initiating_country IN ('China','Iran','Russia','Turkey')
                  ORDER BY m.weighted_degree DESC LIMIT 8"""):
        print("  ", r)


if __name__ == "__main__":
    with get_session() as s:
        build_source_map(s)
        build_event_entities(s)
        n, e, c = build_graph_metrics(s)
        print(f"graph: {n} nodes, {e} edges, {c} components")
        report(s)
    print("\n[done] entity/event/source artifacts built.")
