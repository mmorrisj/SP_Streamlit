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
                                    RecipientDaily)
from backend.extensions import db

# Load configuration
cfg = Config.from_yaml()
current_date = datetime.now()
date_string = current_date.strftime("%Y-%m-%d")
# Initialize database connection
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://matthew50:softpower@localhost:5432/softpower-db"

def generate_date_range(start_date_str, end_date_str):
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    
    delta = end_date - start_date
    date_list = [start_date + timedelta(days=i) for i in range(delta.days + 1)]
    
    return date_list

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


rec_daily_prompt = """
    You are creating a structured daily summary of {country}’s soft power activities towards {recipient}. 
    Use the following JSON schema to identify and consolidate specific soft power related events on {date}. Out put a list of activities based on HIGHLIGHTS below in the following format:
    {{
    "date": "{date}",
    "initiating_country": "{country}",
    "recipient_country": "{recipient}",
    "aggregate_summary": "<AGGREGATE SUMMARY TEXT>",
    "soft_power_events": [{{
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
    Summarize the specifics of {country}'s soft power activities towards {recipient} in an aggregate summary.
    List identitified soft power event using the above format and append it to the "soft_power_events" list in the json output:
    For each event: 
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


def process_event(e):
    name = e['event_name']
    category = e['category']
    subcategory = e['subcategory']
    latlong = e['lat_long']
    description = e['description']
    significance= e['significance']
    entities = e['entities']
    sources = e['sources']
    return name,category,subcategory,latlong,description,significance,entities,sources



def recipient_summaries(country,recipient,start_date,end_date):

    date_range = generate_date_range(start_date,end_date)
    processed_dates = [(x[0],x[1]) for x in db.session.query(DailySummary.date,DailySummary.initiating_country).all()]
    from openai import BadRequestError
    import random
    skip = True
    errors = []
    
    for date in date_range:
        if skip:
            if (date,country) in processed_dates:
                print(f'skipping {country}-{date}, already processed... ')
                continue
        print(f'processing {country}-{date}...')
        #reset counters
        category_counter = {cat: 0 for cat in cfg.categories}
        subcategory_counter = {cat: 0 for cat in cfg.subcategories}
        recipient_counter = {rec: 0 for rec in cfg.recipients}
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
                RecipientCountry.recipient_country==recipient)).all()

        df = pd.DataFrame([row._asdict() for row in documents])
        if len(df)<1:
            print(f"{country}-{date} returned no records")
            continue

        #find unique key values
     
        categories = [x for x in df['category'].unique() if x in cfg.categories]
        subcategories = [x for x in df['subcategory'].unique() if x in cfg.subcategories]

        category_article_count = {cat: len(df[df['category']==cat]) for cat in categories}
        subcategory_article_count = {cat: len(df[df['subcategory']==cat]) for cat in subcategories}

        #update counters
        for k,v in category_article_count.items():
            category_counter[k] = v
        for k,v in subcategory_article_count.items():
            subcategory_counter[k] = v 

        condensed_df = df.groupby('doc_id').agg(lambda x: list(set(x))).reset_index()
        total_articles = len(condensed_df)
        daily = {}
        daily['TOTAL_ARTICLES'] = total_articles
        daily['SOFTPOWER_CATEGORIES'] = categories
        daily['CATEGORY_COUNTS'] = category_counter
        daily['SUBCATEGORY_COUNTS'] = subcategory_counter
        daily['HIGHLIGHTS'] = condensed_df.to_dict(orient='records')

        rec_daily_prompt.format(country=country,recipient=recipient,date=date,categories=cfg.categories,subcategories=cfg.subcategories)
        highlight_text = f"HIGHLIGHTS: {daily}"
        try:
            response = gai(sys_prompt=rec_daily_prompt,user_prompt=highlight_text)
        except BadRequestError as e:
            # Get error message
            err_msg = str(e)
            print(e)
            print(f'sampling reports for {date}')
            sample_keys = random.sample(list(daily.keys()), k=round(len(daily)*.7))
            sample = {k: daily[k] for k in sample_keys}
            # Fallback sample of text if df_sample is provided
            
            highlight_text = f"HIGHLIGHTS: {sample}"
            response = gai(sys_prompt=daily_prompt,user_prompt=highlight_text)
        gai_output = fetch_gai_content(response)
        
        if not gai_output:
            print(f'error processing {country}-{date} output...')
            errors.append(response)
            continue
        # try:
        events,aggregate_summary = process_output(gai_output)
        for event in events:
            name,category,subcategory,latlong,description,significance,entities,sources = process_event(event)
            
            softpower_activity = SoftPowerActivity(
                date=date,
                initiating_country = country,
                recipient_country = recipient,
                category = category,
                subcategory = subcategory,
                description = description,
                significance = significance,
                entities = str(entities),
                sources = str(sources),
                event_name = name,
                lat_long = latlong
            )
            exists = db.session.query(SoftPowerActivity).filter(
                SoftPowerActivity.date == softpower_activity.date,
                SoftPowerActivity.initiating_country == softpower_activity.initiating_country,
                SoftPowerActivity.recipient_country == softpower_activity.recipient_country,
                SoftPowerActivity.event_name == softpower_activity.event_name,
            ).first()
            if not exists:
                db.session.add(softpower_activity)
                db.session.flush()  # Pushes to DB so .id is populated
            else:
                 print("Activity already exists, skipping insert.")

            event_id = softpower_activity.id
            
            existing_entities = {
                    e.entity for e in SoftPowerEntity.query.filter_by(sp_id=event_id).all()
                }
            if isinstance(sources, list) and sources:
                for source in sources:
                    stmt = insert(SoftPowerActivitySource).values(sp_id=event_id, doc_id=source)
                    stmt = stmt.on_conflict_do_nothing()
                    db.session.execute(stmt)
            
            if isinstance(entities,list):
                if entities:
                    for entity in entities:
                        if entity not in existing_entities:
                            stmt = insert(SoftPowerEntity).values(sp_id=event_id, entity = entity)
                            stmt = stmt.on_conflict_do_nothing()
                            db.session.execute(stmt)
            
            db.session.commit()

        daily_summary = RecipientDaily(
            date=date,
            initiating_country=country,
            recipient_countries = recipient,
            categories = str(categories),
            subcategories = str(subcategories),
            total_articles = total_articles,
            count_by_category = str(category_counter),
            count_by_subcategory = str(subcategory_counter),
            aggregate_summary = aggregate_summary
        )
        db.session.add(daily_summary)

        db.session.commit()
        print(f'inserted {country}-{date} daily, total_articles:{total_articles}')

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Generate daily soft power summaries.")
    parser.add_argument('--country', type=str, required=True, help='Name of initiating country (e.g., China)')
    parser.add_argument('--start_date', type=str, required=True, help='Start date in YYYY-MM-DD format')
    parser.add_argument('--end_date', type=str, required=True, help='End date in YYYY-MM-DD format')
    return parser.parse_args()

if __name__ == '__main__':
    from backend.app import app
    with app.app_context():
        args = parse_args()
        daily_summaries(args.country, args.start_date, args.end_date)