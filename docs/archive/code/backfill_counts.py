import sys
from datetime import datetime
import pandas as pd
from sqlalchemy import select, func
from backend.app import app
from backend.extensions import db
from sqlalchemy import create_engine
from backend.scripts.models import (
    DailySummary, Document, InitiatingCountry, RecipientCountry,
    Category, Subcategory
)
from backend.scripts.utils import Config


def recompute_counts_for_date(date, country, cfg):
    """
    Returns 3 dicts: category_counter, subcategory_counter, recipient_counter
    for the given date & country.
    """
    # 1) pull raw rows: one per (doc_id, category, subcategory, recipient)
    
    stmt = (
        select(
            Document.doc_id,
            Category.category,
            Subcategory.subcategory,
            RecipientCountry.recipient_country
        )
        .join(Category,          Category.doc_id == Document.doc_id)
        .join(Subcategory,       Subcategory.doc_id == Document.doc_id)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
        .join(RecipientCountry,  RecipientCountry.doc_id  == Document.doc_id)
        .filter(
            Document.date == date,
            InitiatingCountry.initiating_country == country,
            RecipientCountry.recipient_country.in_(cfg.recipients)
        )
    )
    engine = db.get_engine()
    with engine.connect() as conn:
        result = conn.execute(stmt)
   
        rows = result.fetchall()
    cols = result.keys()
    if not rows:
        return {}, {}, {}

    df = pd.DataFrame(rows, columns=cols)

    # 2) dedupe per document
    df = df.drop_duplicates(subset=['doc_id', 'category', 'subcategory', 'recipient_country'])

    # 3) group per doc_id to collect sets
    grouped = (
        df.groupby('doc_id')
          .agg(
              cats=('category', lambda x: set(x)),
              subs=('subcategory', lambda x: set(x)),
              recs=('recipient_country', lambda x: set(x))
          )
          .reset_index()
    )

    # init counters
    category_counter    = {c: 0 for c in cfg.categories}
    subcategory_counter = {s: 0 for s in cfg.subcategories}
    recipient_counter   = {r: 0 for r in cfg.recipients}

    # 4) tally
    for row in grouped.itertuples():
        for c in row.cats:
            if c in category_counter:
                category_counter[c] += 1
        for s in row.subs:
            if s in subcategory_counter:
                subcategory_counter[s] += 1
        for r in row.recs:
            if r in recipient_counter:
                recipient_counter[r] += 1

    return category_counter, subcategory_counter, recipient_counter


def backfill_all(start_date_str):
    cfg = Config.from_yaml()
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    with app.app_context():
        summaries = (
            DailySummary.query
                        .filter(DailySummary.date >= start_date)
                        .all()
        )
        for ds in summaries:
            cats, subs, recs = recompute_counts_for_date(ds.date, ds.initiating_country, cfg)
            ds.count_by_category    = str(cats)
            ds.count_by_subcategory = str(subs)
            ds.count_by_recipient   = str(recs)

        db.session.commit()
        print(f"Backfilled {len(summaries)} DailySummary rows from {start_date}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python backfill_counts.py YYYY-MM-DD")
        sys.exit(1)
    backfill_all(sys.argv[1])
