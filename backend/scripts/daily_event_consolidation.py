import argparse
import json
import re
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity

from backend.scripts.models import DailyEvent, DailyEventSource, Document, InitiatingCountry, RecipientCountry, Category, Subcategory
from dotenv import load_dotenv
from backend.extensions import db
import requests
from backend.scripts.utils import Config
from langchain_huggingface import HuggingFaceEmbeddings

# ---------------------------------------
# Embedding setup
# ---------------------------------------
embedding_function = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts (for event-level deduplication)."""
    if not texts:
        return np.array([])
    return np.array(embedding_function.embed_documents(texts))

import numpy as np

def fetch_embeddings_for_docs(doc_ids: list[str]):
    """Fetch precomputed embeddings from pgvector for given doc_ids."""
    if not doc_ids:
        return {}
    placeholders = ",".join([f":id{i}" for i in range(len(doc_ids))])
    sql = text(f"""
        SELECT cmetadata->>'doc_id' AS doc_id, embedding
        FROM langchain_pg_embedding
        WHERE cmetadata->>'doc_id' IN ({placeholders})
    """)
    params = {f"id{i}": str(doc_id) for i, doc_id in enumerate(doc_ids)}
    with db.engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()

    emb_map = {}
    for row in rows:
        emb = row["embedding"]

        # pgvector may return memoryview, list, or string. Normalize:
        if isinstance(emb, memoryview):
            emb = np.frombuffer(emb, dtype=np.float32)
        elif isinstance(emb, str):
            emb = np.fromstring(emb.strip("[]"), sep=",")
        else:
            emb = np.array(emb, dtype=np.float32)

        emb_map[row["doc_id"]] = emb
    return emb_map



# ---------------------------------------
# Config / DB
# ---------------------------------------
load_dotenv()
db_host = "localhost"
DATABASE_URL = f"postgresql://matthew50:softpower@{db_host}:5432/softpower-db"
engine = create_engine(DATABASE_URL)

cfg = Config.from_yaml()
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:5001/material_query")


# ---------------------------------------
# Utilities
# ---------------------------------------
def safe_json_parse(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r',\s*([\]}])', r'\1', raw)
        cleaned = re.sub(r'(?<!")([0-9a-f]{8}-[0-9a-f\-]{4,})(?!")', r'"\1"', cleaned)
        cleaned = cleaned.replace("'", '"')
        try:
            return json.loads(cleaned)
        except Exception as e:
            print(f"❌ Still could not parse JSON after cleanup: {e}")
            return []


def query_gai_via_gateway(sys_prompt: str, user_prompt: str, model: str):
    payload = {"sys_prompt": sys_prompt, "prompt": user_prompt, "model": model}
    try:
        res = requests.post(FASTAPI_URL, json=payload)
        res.raise_for_status()
        data = res.json()
        resp_content = data["response"] if isinstance(data, dict) and "response" in data else data
        if isinstance(resp_content, (dict, list)):
            return resp_content
        if isinstance(resp_content, str):
            try:
                return json.loads(resp_content)
            except json.JSONDecodeError:
                match = re.search(r'(\[.*\]|\{.*\})', resp_content, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
                return [{"raw_response": resp_content}]
    except Exception as e:
        return f"[Error from Gateway]: {e}"


def gather_articles(date, country, recipients=None, categories=None, subcategories=None, snippet_len=2000):
    recs = recipients or cfg.recipients
    cats = set(categories or cfg.categories)
    subs = set(subcategories or cfg.subcategories)
    q = (db.session.query(
            Document.doc_id,
            Document.title,
            Document.distilled_text,
            Document.source_name,
            Document.date,
            Category.category,
            Subcategory.subcategory,
            InitiatingCountry.initiating_country,
            RecipientCountry.recipient_country,
            Document.event_name,
        )
        .join(Category, Category.doc_id == Document.doc_id)
        .join(Subcategory, Subcategory.doc_id == Document.doc_id)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
        .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
        .filter(
            Document.date == date,
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(recs),
            RecipientCountry.recipient_country != InitiatingCountry.initiating_country,
        ))
    df = pd.DataFrame([r._asdict() for r in q.all()])
    if df.empty:
        return df
    df = df[(df["category"].isin(cats)) & (df["subcategory"].isin(subs))]
    df["doc_id"] = df["doc_id"].astype(str)
    for col in ["title", "distilled_text", "source_name", "recipient_country", "category", "subcategory"]:
        df[col] = df[col].fillna("")
    df["snippet"] = (df["title"].str.strip() + " — " + df["distilled_text"].str.strip()).str[:snippet_len]
    df = df[df["snippet"].str.strip().ne("")]
    df = (
    df.groupby("doc_id", as_index=False)
      .agg({
          "title": "first",
          "distilled_text": "first",
          "snippet": "first",
          "source_name": "first",
          "date": "first",
          "event_name": lambda s: sorted(set(s)),
          "recipient_country": lambda s: sorted(set(s)),
          "category": lambda s: sorted(set(s)),
          "subcategory": lambda s: sorted(set(s)),
      })
        )

    return df


# ---------------------------------------
# Clustering
# ---------------------------------------
def cluster_articles(df, max_cluster_size=50, min_cluster_threshold=50):
    emb_map = fetch_embeddings_for_docs(df["doc_id"].tolist())
    available_doc_ids = [doc_id for doc_id in df["doc_id"] if doc_id in emb_map]

    if not available_doc_ids:
        df["cluster_id"] = -1
        return df, np.array([])

    embeddings = np.array([emb_map[doc_id] for doc_id in available_doc_ids])

    n_docs = len(available_doc_ids)
    if n_docs <= min_cluster_threshold:
        df["cluster_id"] = 0
        return df, embeddings

    k = max(1, n_docs // max_cluster_size + (1 if n_docs % max_cluster_size else 0))
    kmeans = KMeans(n_clusters=k, random_state=42).fit(embeddings)

    # Map cluster labels only to docs with embeddings
    cluster_assignments = dict(zip(available_doc_ids, kmeans.labels_))
    df["cluster_id"] = df["doc_id"].map(cluster_assignments).fillna(-1).astype(int)

    return df, embeddings


# ---------------------------------------
# GPT Prompts
# ---------------------------------------
unique_event_sys_prompt = """
You are creating a consolidated list of {country}’s soft power activities. 

Using the provided HIGHLIGHTS, identify unique, specific soft power related events that occurred on this date. 
If multiple highlights reference the same event, consolidate them into a single entry with all associated "mini_ids".

Your output MUST follow these rules:
- Output ONLY valid JSON (no explanations, no text outside JSON).
- Return an array of event objects.
- Each object MUST contain:
  - "event_name": a string (concise event title).
  - "mini_ids": an array of integers
- Do not include a trailing comma after the last item.
- Do not include comments or additional fields.

Format exactly like this:

[
  {{
    "event_name": "Example Event Name",
    "event_desc": "event description",
    "mini_ids": [1, 2, 3]
  }},
  {{
    "event_name": "Another Example",
    "event_desc": "event description",
    "mini_ids": [4, 5]
  }}
]
"""

event_user_prompt = """HIGHLIGHTS: {documents}"""


# ---------------------------------------
# Main Processing
# ---------------------------------------
def process_events(country, start_date, end_date, skip=True, replace=False, batch_size=50, dry_run=False):
    
    current = start_date
    while current <= end_date:
        print(f"Processing {country} on {current}")

        # --- Skip / replace check ---
        existing = db.session.query(DailyEvent).filter_by(
            initiating_country=country,
            report_date=current
        ).first()

        if existing and skip and not replace:
            print(f"⏭️ Skipping {country} on {current} (already processed)")
            current += timedelta(days=1)
            continue

        if replace and existing:
            print(f"🔁 Replacing existing {country} on {current}")
            db.session.query(DailyEvent).filter_by(
                initiating_country=country,
                report_date=current
            ).delete(synchronize_session=False)
            db.session.commit()

        # --- Gather articles ---
        df = gather_articles(date=current, country=country)
        if df.empty or len(df) <= 1:
            print(f"No docs found for {country} on {current}, skipping")
            current += timedelta(days=1)
            continue

        # Cluster articles
        df, _ = cluster_articles(df, max_cluster_size=50, min_cluster_threshold=50)

        # Map doc_ids to mini_ids for GPT
        doc_map = {i + 1: did for i, did in enumerate(df["doc_id"].unique())}
        df["mini_id"] = df["doc_id"].map({v: k for k, v in doc_map.items()})

        # Correct: mini_id → doc_id
        mini_to_doc = {mini: doc for mini, doc in doc_map.items()}

        all_events = []

        # ---- Run GPT per cluster ----
        for cluster_id, group in df.groupby("cluster_id"):
            docs = group.to_dict(orient="records")
            sys_prompt = unique_event_sys_prompt.format(country=country, date=current)
            user_prompt = event_user_prompt.format(documents=str(docs))

            r = query_gai_via_gateway(sys_prompt=sys_prompt, user_prompt=user_prompt, model="gpt-4.1")

            for event in r:
                if "raw_response" in event:
                    parsed = safe_json_parse(event["raw_response"])
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                    for pe in parsed:
                        if "event_name" in pe:
                            all_events.append(pe)
                elif "event_name" in event:
                    all_events.append(event)

        # ---- Cross-cluster consolidation using embeddings ----
        event_strings = [f"{e['event_name']}: {e.get('event_desc','')}" for e in all_events]
        event_embeddings = embed_texts(event_strings)

        merged_events, used = [], set()
        if event_embeddings.size > 0:
            sim = cosine_similarity(event_embeddings)
            for i, e in enumerate(all_events):
                if i in used:
                    continue
                cluster = [i]
                for j in range(i + 1, len(all_events)):
                    if sim[i, j] > 0.8:  # similarity threshold
                        cluster.append(j)
                        used.add(j)
                merged_event = {
                    "event_name": e["event_name"],
                    "event_desc": e.get("event_desc", ""),
                    "mini_ids": sorted({id_ for j in cluster for id_ in all_events[j]["mini_ids"]}),
                }
                merged_events.append(merged_event)

        if dry_run:
            OUTPUT_DIR = os.getenv("OUTPUT_DIR", "dry_runs")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            out_path = os.path.join(OUTPUT_DIR, f"events_{country}_{current}_dryrun.json")

            cluster_events = []
            for cluster_id, group in df.groupby("cluster_id"):
                docs = group.to_dict(orient="records")
                mini_to_title = {d["mini_id"]: d["title"] for d in docs}

                sys_prompt = unique_event_sys_prompt.format(country=country, date=current)
                user_prompt = event_user_prompt.format(documents=str(docs))

                r = query_gai_via_gateway(sys_prompt=sys_prompt, user_prompt=user_prompt, model="gpt-4.1")

                for event in r:
                    ev = None
                    if "raw_response" in event:
                        parsed = safe_json_parse(event["raw_response"])
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                        for pe in parsed:
                            if "event_name" in pe:
                                ev = pe
                    elif "event_name" in event:
                        ev = event

                    if ev:
                        ev["cluster_id"] = int(cluster_id)
                        event_titles = [mini_to_title[m] for m in ev.get("mini_ids", []) if m in mini_to_title]
                        ev["titles"] = sorted(set(event_titles))
                        ev["n_titles"] = len(ev["titles"])
                        cluster_events.append(ev)

            # Sort cluster events for readability
            cluster_events = sorted(cluster_events, key=lambda e: e.get("n_titles", 0), reverse=True)

            # Flatten GPT outputs across clusters
            before_merge = [
                {k: v for k, v in ev.items() if k in ["event_name", "event_desc", "mini_ids", "cluster_id", "titles", "n_titles"]}
                for ev in cluster_events
            ]

            # Already computed earlier in pipeline → merged_events
            after_merge = merged_events

            audit_output = {
                "date": str(current),
                "country": country,
                "n_docs": len(df),
                "cluster_assignments": df[
                    ["doc_id", "mini_id", "cluster_id", "recipient_country", "category", "subcategory"]
                ].to_dict(orient="records"),
                "cluster_events": cluster_events,   # GPT consolidation by cluster
                "merge_pass": {
                    "before_merge": before_merge,   # GPT outputs across all clusters
                    "after_merge": after_merge      # cosine similarity merged outputs
                }
            }

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(audit_output, f, indent=2, ensure_ascii=False)

            print(f"📝 Dry-run: wrote audit results for {len(df)} docs and {len(after_merge)} merged events to {out_path}")


        else:
            # ---- Save to DB ----
                    
            # ---- Save to DB ----
            daily_events = []
            for ev in merged_events:
                e = DailyEvent(
                    event_name=ev.get("event_name", "Unnamed Event"),
                    initiating_country=country,
                    report_date=current
                )
                db.session.add(e)
                db.session.flush()  # ensures e.id is available

                seen_doc_ids = set()
                for id_ in ev.get("mini_ids", []):
                    doc_id = mini_to_doc.get(id_)
                    if not doc_id:
                        print(f"⚠️ No doc_id found for mini_id={id_}")
                        continue
                    if doc_id not in seen_doc_ids:
                        if db.session.query(Document).filter_by(doc_id=doc_id).first():
                            des = DailyEventSource(event_id=e.id, doc_id=doc_id)
                            db.session.add(des)
                            seen_doc_ids.add(doc_id)
                        else:
                            print(f"⚠️ Skipping missing doc_id={doc_id} (not in documents table)")
                daily_events.append(e)

            try:
                db.session.commit()
                print(f"✅ Committed {len(daily_events)} events for {country} on {current}")
            except Exception as ex:
                db.session.rollback()
                print(f"❌ Commit failed: {ex}")



        current += timedelta(days=1)


# ---------------------------------------
# CLI
# ---------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process daily events into database")
    parser.add_argument("--country", required=True, help="Country name")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--skip", action="store_true", help="Skip already-processed dates")
    parser.add_argument("--replace", action="store_true", help="Replace already-processed dates")
    parser.add_argument("--dry-run", action="store_true", help="Output to JSON instead of writing to DB")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    from backend.app import create_app

    # build the app
    app = create_app()
    with app.app_context():
        process_events(
            country=args.country,
            start_date=start_date,
            end_date=end_date,
            skip=args.skip,
            replace=args.replace,
            dry_run=args.dry_run
        )


