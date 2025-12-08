from backend.scripts.models import RawEvent,Event,EventSources,Document,InitiatingCountry,RecipientCountry,Category,Subcategory
from backend.extensions import db
from sqlalchemy import select
import re
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import sessionmaker
import argparse
import pandas as pd
from sentence_transformers import SentenceTransformer
import hdbscan
import umap
from scipy.spatial.distance import cosine
from sklearn.metrics.pairwise import cosine_distances
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sklearn.feature_extraction.text import TfidfVectorizer

DB_HOST = "localhost"
DATABASE_URL = f"postgresql://matthew50:softpower@{DB_HOST}:5432/softpower-db" 
engine = create_engine(DATABASE_URL)

# 2) embed all names
model = SentenceTransformer("all-MiniLM-L6-v2")
from SoftPowerCLI import Config

cfg = Config.from_yaml()

def normalize(name):
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)               # strip punctuation
    name = re.sub(r"\b(cooperation|forum|meeting)\b", "", name)  # drop generic tokens
    return " ".join(name.split())

def strip_ordinals(s):
    return re.sub(r"\b\d+(?:st|nd|rd|th)\b", "", s.lower())

def fetch_events(country,recipient):
    stmt = select(RawEvent,Document.date)
    stmt = stmt.join(Document, RawEvent.doc_id == Document.doc_id)
    #filter by country
    stmt = stmt.join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
    stmt = stmt.filter(InitiatingCountry.initiating_country==country)
    stmt = stmt.join(RecipientCountry, Document.doc_id == RecipientCountry.doc_id)
    stmt = stmt.filter(RecipientCountry.recipient_country==recipient)
    # #join category
    # stmt = stmt.join(Category, Document.doc_id == Category.doc_id)
    # stmt = stmt.filter(Category.category.in_(cfg.categories))
    # #join subcategory
    # stmt = stmt.join(Subcategory, Document.doc_id == Subcategory.doc_id)
    # stmt = stmt.filter(Subcategory.subcategory.in_(cfg.subcategories))


    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)

    # 2) group by event_name & date and count rows per group
    event_df = (
        df
        .groupby(["event_name", "date"], as_index=False)
        .size()                         # count number of rows per group
        .rename(columns={"size": "article_count"})
        .sort_values("article_count", ascending=False)
        
    )

    return event_df

def embed_names(event_df, max_df=0.8, min_df=2):
    # 1. Clean & normalize
    event_df["clean_name"] = (
        event_df["event_name"]
        .apply(normalize)
        .apply(strip_ordinals)
    )

    # 2. Build TF–IDF vectorizer over the entire set
    #    to identify which tokens to keep
    vec = TfidfVectorizer(
        lowercase=True,
        token_pattern=r"(?u)\b\w+\b",
        max_df=max_df,   # drop tokens present in > max_df fraction of names
        min_df=min_df    # drop tokens present in < min_df names
    )
    vec.fit(event_df["clean_name"])
    keep_tokens = set(vec.get_feature_names_out())

    # 3. Filter each clean_name down to only those mid-frequency tokens
    def filter_tokens(text):
        return " ".join(tok for tok in text.split() if tok in keep_tokens)

    event_df["filtered_name"] = event_df["clean_name"].apply(filter_tokens)

    # 4. Embed using your model
    embs = model.encode(
        event_df["filtered_name"].tolist(),
        show_progress_bar=True
    )
    return embs

def cluster_embs(embs, eps=0.08, min_samples=2):
    # you can adjust eps/min_samples after calibration
    labels = DBSCAN(
        metric="cosine",
        eps=eps,
        min_samples=min_samples
    ).fit_predict(embs)
    return labels

def cluster_labels(event_df, **dbscan_kwargs):
    # Re-embed & cluster in one call
    embs = embed_names(event_df)
    labels = cluster_embs(embs, **dbscan_kwargs)
    event_df["cluster"] = labels
    return event_df

def consolidate_names(event_df):
    # 1. Unique per raw event
    unique = (
        event_df[["event_name", "cluster", "article_count"]]
        .drop_duplicates(subset="event_name")
    )

    # 2. Build raw→canonical for each cluster
    cluster_to_canon = {}
    for cluster_id, grp in unique.groupby("cluster"):
        if cluster_id == -1:
            for raw in grp["event_name"]:
                cluster_to_canon[raw] = raw
        else:
            canon = grp.loc[grp.article_count.idxmax(), "event_name"]
            for raw in grp["event_name"]:
                cluster_to_canon[raw] = canon

    # 3. Turn into a list of mappings
    mappings = [
        {"event_name": raw, "consolidated_name": cons}
        for raw, cons in cluster_to_canon.items()
    ]
    return mappings

from sqlalchemy.dialects.postgresql import insert

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
def insert_event(mappings, country, recipient):
    unique_events = []
    seen = set()
    for rec in mappings:
        cons = rec["consolidated_name"]
        data = {
            "event_name": cons,
            "initiating_country": country,
            "recipient_country": recipient
        }
        key = (cons, country, recipient)
        if key not in seen:
            seen.add(key)
            unique_events.append(data)

    if unique_events:
        stmt = (
            insert(Event.__table__)
            .values(unique_events)
            .on_conflict_do_nothing(
                index_elements=["event_name", "initiating_country", "recipient_country"]
            )
        )
        with Session(engine) as sess:
            sess.execute(stmt)
            sess.commit()
            
def insert_event_sources(mappings, country, recipient):
    with Session(engine) as sess:
        # 1) Preload all events for this country/recipient into a dict keyed by the same triple
        evts = {
            (e.event_name, e.initiating_country, e.recipient_country): e.id
            for e in sess.query(Event).filter_by(
                initiating_country=country,
                recipient_country=recipient
            )
        }

        unique_sources = []
        seen = set()

        for rec in mappings:
            raw  = rec["event_name"]
            cons = rec["consolidated_name"]
            # lookup by the exact triple you used as key
            event_id = evts.get((cons, country, recipient))
            if event_id is None:
                print(f"Event {cons} not found for {country}-{recipient}. Skipping.")
                continue

            # 2) fetch all doc_ids for that raw, suppress autoflush correctly
            with sess.no_autoflush:
                doc_ids = [
                    d for (d,) in sess.query(RawEvent.doc_id)
                                  .filter(RawEvent.event_name == raw)
                                  .all()
                ]

            # 3) collect + dedupe as you go
            for doc_id in doc_ids:
                key = (event_id, doc_id)
                if key in seen:
                    continue
                seen.add(key)
                unique_sources.append({
                    "event_id": event_id,
                    "doc_id":   doc_id
                })

        # 4) bulk insert
        if unique_sources:
            stmt = (
                insert(EventSources.__table__)
                .values(unique_sources)
                .on_conflict_do_nothing(constraint="uq_event_source_composite")
            )
            sess.execute(stmt)
            sess.commit()
        
def process_events(country,recipient,source_only=False):
    print(f'loading {country}-{recipient} events...')
    event_df = fetch_events(country, recipient)
    
    print('clustering...')
    event_df= cluster_labels(event_df)
    mappings = consolidate_names(event_df)
    if source_only:
        print('inserting event sources only...')
        insert_event_sources(mappings,country,recipient)
        print('done.')
        return
    print('inserting...')
    insert_event(mappings,country,recipient)
    print(f'inserting event sources for {country}-{recipient}...')
    insert_event_sources(mappings,country,recipient)
    print('done.')

def parse_args():
    parser = argparse.ArgumentParser(description="Cluster and Dedupe Extracted Events.")
    parser.add_argument('--country', type=str, required=False,default=None, help='Name of initiating country (e.g., China)')
    parser.add_argument('--recipient', type=str, required=False,default=None, help='Start date in YYYY-MM-DD format')
    # add optional argument for executing source insertion only
    parser.add_argument('--source_only', action='store_true', help='Only insert event sources without clustering')
    # parser.add_argument('--eps', type=int, required=False, help='adjust similarity threshold')
    return parser.parse_args()

if __name__ == '__main__':
    from backend.app import app
    args = parse_args()
    with app.app_context():
        if args.country and args.recipient:
            if args.source_only:
                process_events(country=args.country,recipient=args.recipient,source_only=True)
            else:
                process_events(country=args.country,recipient=args.recipient)
        else:
            for country in cfg.influencers:
                for recipient in cfg.recipients:
                    if country == recipient:
                        continue
                    if args.source_only:
                        process_events(country=country,recipient=recipient,source_only=True)
                    else:   
                        process_events(country=country,recipient=recipient)

        
        
        



