import sqlite3
import re
import json
import os
from backend.scripts.utils import Config
from backend.scripts.utils import find_json_objects
from backend.scripts.utils import gai,fetch_gai_content
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import numpy as np
import re 
from openai import BadRequestError
os.environ["DB_HOST"] = "localhost"
os.environ["POSTGRES_USER"] = "matthew50"
os.environ["POSTGRES_PASSWORD"] = "softpower"
os.environ["POSTGRES_DB"] = "softpower-db"

# STEP 2: Now import Flask app and SQLAlchemy
from backend.app import app
from backend.extensions import db
from backend.scripts.models import (Document, 
                                    InitiatingCountry,
                                    RecipientCountry,
                                    Category,
                                    Subcategory,
                                    DailySummary, 
                                    # DailyRecipient, 
                                    SoftPowerActivity,
                                    SoftPowerActivitySource,
                                    SoftPowerEntity,
                                    DailyCategory,
                                    DailyRecipient,
                                    DailySubCategory,
                                    )
from backend.extensions import db

# Load configuration
cfg = Config.from_yaml()
current_date = datetime.now()
date_string = current_date.strftime("%Y-%m-%d")
# Initialize database connection
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://matthew50:softpower@localhost:5432/softpower-db"
def sql_list(_list):
        return ','.join('?' for _ in _list)

def process_str_output(output):
    if isinstance(output,list):
        output = output[0]
    events = str(output['soft_power_events'])
    aggregate_summary = str(output['aggregate_summary'])
    return events,aggregate_summary

def process_output(output):
    if isinstance(output,list):
        output = output[0]
    events = output['soft_power_events']
    aggregate_summary = output['aggregate_summary']
    return events,aggregate_summary

def insert_highlight(daily_id,country,date,highlight):
    action = '''INSERT OR REPLACE INTO recipient_daily (daily_id,date,initiating_country,recipient_country,highlight) VALUES (?,?,?,?,?)'''
    for k,v in highlight.items():
        recipient = k
        rec_highlight = v
        data = (daily_id,date,country,recipient,rec_highlight)
        cursor.execute(action,data)


daily_prompt = """
    You are creating a structured daily summary of {country}’s soft power activities. 
    Use the following JSON schema to identify and consolidate specific soft power related events on {date}. Out put a list of activities based on HIGHLIGHTS below in the following format:
    {{
    "date": "{date}",
    "initiating_country": "{country}",
    "aggregate_summary": "<AGGREGATE SUMMARY TEXT>",
    "soft_power_events": [{{
            "recipient_country": "<RECIPIENT COUNTRY>",
            "event_date": "{date}",
            "event_name": "<EVENT NAME>",
            "category": "<EVENT CATEGORY>",
            "subcategory": "<EVENT SUBCATEGORY>",
            "lat_long": "<EVENT LATITUDE AND LONGITUDE>",
            "description": "<EVENT DESCRIPTION>",
            "significance": "<EVENT SIGNIFICANCE>",
            "entities": [<LIST OF EVENT ENTITIES>],
            "sources": [<LIST OF EVENT RELEVANT ATOM IDs>]
        }}, ...]
    }}
    Instructions:
    Summarize the specifics of {country}'s soft power activities in an aggregate summary.
    List identitified soft power event using the above format and append it to the "soft_power_events" list in the json output:
    For each event: 
    identify the recipient country
    provide an event name
    determine which of the following categories the event falls in: {categories}
    determine which of the following subcategories the event falls in: {subcategories}
    determine if possible, the approximate latitude and longitude of the event, if not possible, return "N/A"
    describe the specifics of the soft power related event. 
                    describe the significance of the activity in a broader strategic context.
                    list notable_entities (organizations, persons, companies, projects, etc.) playing a role in the event.
                    list up to 5 atom ids that cite or discuss the identified soft power event. 

    IMPORTANT: ONLY OUTPUT THE JSON RESULT
    """
def generate_date_range(start_date_str, end_date_str):
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    delta = end_date - start_date
    return [start_date + timedelta(days=i) for i in range(delta.days + 1)]


def sql_list(_list):
    return ','.join('?' for _ in _list)


def process_str_output(output):
    if isinstance(output, list):
        output = output[0]
    events = str(output['soft_power_events'])
    aggregate_summary = str(output['aggregate_summary'])
    return events, aggregate_summary


def process_output(output):
    if isinstance(output, list):
        output = output[0]
    events = output['soft_power_events']
    aggregate_summary = output['aggregate_summary']
    return events, aggregate_summary


def insert_highlight(daily_id, country, date, highlight):
    action = '''INSERT OR REPLACE INTO recipient_daily \
        (daily_id, date, initiating_country, recipient_country, highlight) \
        VALUES (?,?,?,?,?)'''
    cursor = db.session.bind.raw_connection().cursor()
    for k, v in highlight.items():
        recipient = k
        rec_highlight = v
        data = (daily_id, date, country, recipient, rec_highlight)
        cursor.execute(action, data)
    db.session.bind.raw_connection().commit()


def process_event(e):
    return (
        e['recipient_country'],
        e['event_name'],
        e['category'],
        e['subcategory'],
        e['lat_long'],
        e['description'],
        e['significance'],
        e['entities'],
        e['sources'],
    )


def daily_summaries(country, start_date, end_date, skip=True):
    cfg = Config.from_yaml()
    date_range = generate_date_range(start_date, end_date)
    processed = db.session.query(
        DailySummary.date,
        DailySummary.initiating_country
    ).all()
    processed_dates = {(d, c) for d, c in processed}

    for date in date_range:
        already = (date, country) in processed_dates
        if skip and already:
            print(f"Skipping {country}-{date}, already processed.")
            continue

        print(f"Processing {country}-{date}...")
        # Query and assemble documents
        documents = (
            db.session.query(
                Document.doc_id,
                Document.title,
                Document.distilled_text,
                Document.date,
                Category.category,
                Subcategory.subcategory,
                InitiatingCountry.initiating_country,
                RecipientCountry.recipient_country
            )
            .join(Category, Category.doc_id == Document.doc_id)
            .join(Subcategory, Subcategory.doc_id == Document.doc_id)
            .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
            .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
            .filter(
                Document.date == date,
                InitiatingCountry.initiating_country == country,
                RecipientCountry.recipient_country.in_(cfg.recipients)
            )
            .all()
        )
        df = pd.DataFrame([row._asdict() for row in documents])
        if df.empty:
            print(f"{country}-{date} returned no records")
            continue

        recipients = list(set(df['recipient_country']))
        categories = [x for x in df['category'].unique() if x in cfg.categories]
        subcategories = [x for x in df['subcategory'].unique() if x in cfg.subcategories]

        category_counter = {cat: 0 for cat in cfg.categories}
        subcategory_counter = {sub: 0 for sub in cfg.subcategories}
        recipient_counter = {rec: 0 for rec in cfg.recipients}

        # for k, v in {cat: len(df[df['category'] == cat]) for cat in categories}.items():
        #     category_counter[k] = v
        # for k, v in {sub: len(df[df['subcategory'] == sub]) for sub in subcategories}.items():
        #     subcategory_counter[k] = v
        # for k, v in {rec: len(df[df['recipient_country'] == rec]) for rec in recipients}.items():
        #     recipient_counter[k] = v

        total_articles = len(df['doc_id'].unique())

        # Build prompt for GAI
        condensed = df.groupby('doc_id').agg(lambda x: list(set(x))).reset_index()

        for row in condensed.itertuples():
            # row.category, row.subcategory, row.recipient_country are lists
            for cat in row.category:
                if cat in category_counter:
                    category_counter[cat] += 1
            for sub in row.subcategory:
                if sub in subcategory_counter:
                    subcategory_counter[sub] += 1
            for rec in row.recipient_country:
                if rec in recipient_counter:
                    recipient_counter[rec] += 1
        daily = {
            'TOTAL_ARTICLES': total_articles,
            'RECIPIENT_COUNTRIES': recipients,
            'SOFTPOWER_CATEGORIES': categories,
            'RECIPIENT_COUNTS': recipient_counter,
            'CATEGORY_COUNTS': category_counter,
            'SUBCATEGORY_COUNTS': subcategory_counter,
            'HIGHLIGHTS': condensed.to_dict(orient='records'),
        }
        prompt_text = f"HIGHLIGHTS: {daily}"
        try:
            response = gai(sys_prompt=daily_prompt, user_prompt=prompt_text)
        except BadRequestError:
            print(f"Error on {country}-{date}, sampling fallback.")
            sample = {k: daily[k] for k in random.sample(list(daily), k=max(1, len(daily)//2))}
            response = gai(sys_prompt=daily_prompt, user_prompt=f"HIGHLIGHTS: {sample}")

        gai_output = fetch_gai_content(response)
        if not gai_output:
            print(f"No GAI output for {country}-{date}")
            continue

        events, aggregate_summary = process_output(gai_output)
        for e in events:
            try:
                recipient, name, cat, sub, latlong, desc, signif, ents, srcs = process_event(e)
            except KeyError as ke:
                print("Skipping malformed event (missing key):", e)
                continue
            sp = SoftPowerActivity(
                date=date,
                initiating_country=country,
                recipient_country=recipient,
                category=cat,
                subcategory=sub,
                description=desc,
                significance=signif,
                entities=str(ents),
                sources=str(srcs),
                event_name=name,
                lat_long=latlong
            )
            exists = db.session.query(SoftPowerActivity).filter_by(
                date=date,
                initiating_country=country,
                recipient_country=recipient,
                event_name=name
            ).first()
            if not exists:
                db.session.add(sp)
                db.session.flush()

                # upsert sources
                for raw in srcs:
                    # normalize to a plain string
                    if isinstance(raw, dict):
                        real_doc_id = raw.get("doc_id")
                    else:
                        real_doc_id = raw

                    sstmt = insert(SoftPowerActivitySource).values(
                        sp_id  = sp.id,
                        doc_id = real_doc_id
                    ).on_conflict_do_nothing(
                        index_elements=['sp_id', 'doc_id']
                    )
                    db.session.execute(sstmt)

                # upsert entities
                for ent in ents:
                    estmt = insert(SoftPowerEntity).values(
                        sp_id=sp.id,
                        entity=ent
                    ).on_conflict_do_nothing(
                        index_elements=['sp_id', 'entity']
                    )
                    db.session.execute(estmt)

        db.session.commit()

        # Upsert DailySummary
        values = {
            'date': date,
            'initiating_country': country,
            'recipient_countries': str(recipients),
            'categories': str(categories),
            'subcategories': str(subcategories),
            'total_articles': total_articles,
            'count_by_category': str(category_counter),
            'count_by_subcategory': str(subcategory_counter),
            'count_by_recipient': str(recipient_counter),
            'aggregate_summary': aggregate_summary,
        }
        stmt = insert(DailySummary).values(**values)
        if skip:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['date', 'initiating_country']
            )
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=['date', 'initiating_country'],
                set_={k: stmt.excluded[k] for k in values if k not in ('date', 'initiating_country')}
            )
        db.session.execute(stmt)
        db.session.commit()
        print(f"Upserted DailySummary for {country}-{date} (skip={skip})")

        summary = DailySummary.query.filter_by(
            date=date,
            initiating_country=country
        ).one()
        daily_id = summary.id

        # Upsert recipients, categories, subcategories
        for rec in recipients:
            rstmt = insert(DailyRecipient).values(
                daily_id=daily_id,
                recipient_country=rec,
                rec_article_count=recipient_counter[rec]
            ).on_conflict_do_nothing(
                index_elements=['daily_id', 'recipient_country']
            )
            db.session.execute(rstmt)
        for cat in categories:
            cstmt = insert(DailyCategory).values(
                daily_id=daily_id,
                category=cat,
                cat_article_count=category_counter[cat]
            ).on_conflict_do_nothing(
                index_elements=['daily_id', 'category']
            )
            db.session.execute(cstmt)
        for sub in subcategories:
            sstmt = insert(DailySubCategory).values(
                daily_id=daily_id,
                subcategory=sub,
                subcat_article_count=subcategory_counter[sub]
            ).on_conflict_do_nothing(
                index_elements=['daily_id', 'subcategory']
            )
            db.session.execute(sstmt)
        db.session.commit()
        print(f"Upserted recipients, categories, subcategories for {country}-{date}")

import argparse
def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate daily soft power summaries with upsert behavior."
    )
    parser.add_argument(
        '--country',
        type=str,
        required=True,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--start_date',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD'
    )
    parser.add_argument(
        '--end_date',
        type=str,
        required=True,
        help='End date in YYYY-MM-DD'
    )
    parser.add_argument(
        '--skip',
        dest='skip',
        action='store_true',
        help='Skip existing summaries (default)'
    )
    parser.add_argument(
        '--no-skip',
        dest='skip',
        action='store_false',
        help='Overwrite existing summaries'
    )
    parser.set_defaults(skip=True)
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    with app.app_context():
        daily_summaries(
            country=args.country,
            start_date=args.start_date,
            end_date=args.end_date,
            skip=args.skip
        )