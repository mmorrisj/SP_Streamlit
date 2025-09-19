from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from backend.extensions import db
from dotenv import load_dotenv
import os
import re
load_dotenv()
DB_HOST = "localhost"
DATABASE_URL = f"postgresql://matthew50:softpower@{DB_HOST}:5432/softpower-db"  # adjust if needed
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
from datetime import timedelta
from backend.scripts.models import RawEvent, EventSources,InitiatingCountry,RecipientCountry
import boto3
from openai import AzureOpenAI
from streamlit import cache_data
import json
# from sp_streamlit.db import engine,get_session
# from backend.extensions import db
from sqlalchemy import func, desc
from SoftPowerCLI import Config
import ast
from backend.scripts.models import Document, InitiatingCountry, RecipientCountry,Category,Subcategory,DailySummary
from backend.scripts.models import RawEvent, Event,EventSources,EventSummary,EventEntities,Commitments,InitiatingCountry,RecipientCountry
import numpy as np
import pandas as pd

cfg = Config.from_yaml()


import os
os.environ["DB_HOST"] = "localhost"
os.environ["POSTGRES_USER"] = "matthew50"
os.environ["POSTGRES_PASSWORD"] = "softpower"
os.environ["POSTGRES_DB"] = "softpower-db"


  
secret_name = "azure-open-ai-credentials"
current_date = pd.to_datetime('today').strftime('%Y-%m-%d')
def get_db_secret(secret_name: str, region: str = "us-east-1") -> dict[str,str]:
    boto3_session = boto3.Session()
    client = boto3_session.client(service_name="secretsmanager", region_name=region)
    secret_value = client.get_secret_value(SecretId=secret_name)
    return json.loads(secret_value['SecretString'])


secret_dict = get_db_secret(secret_name)

deployment = secret_dict['GPT_4_1_MINI_DEPLOYMENT_NAME']
gpt_client = AzureOpenAI(
    azure_endpoint=secret_dict["GPT_4_1_MINI_ENDPOINT"],
    api_key=secret_dict["GPT_4_1_MINI_KEY"],
    api_version="2024-10-21",
    timeout=60,
)
print("ready")
def get_event_summary_id(event_id, event_name):
    with Session(engine) as sess:
        event_summary = sess.query(EventSummary).filter_by(event_id=event_id, event_name=event_name).first()
        if event_summary:
            return event_summary.id
        else:
            return None

def parse_llm_dict(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON/dict found in LLM output:\n{raw!r}")
    body = m.group(0)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return ast.literal_eval(body)
        
def insert_event_entities(event_id: int, summary_id: int, data: dict):
    raw = data.get("entities")

    # 1) Normalize to a real Python list
    if isinstance(raw, str):
        try:
            entities_list = json.loads(raw)
        except json.JSONDecodeError:
            entities_list = ast.literal_eval(raw)
    else:
        entities_list = raw

    # 2) Build rows
    rows = [
        {
            "event_id": int(event_id),
            "event_summary_id": int(summary_id),
            "entity": ent
        }
        for ent in entities_list
        if isinstance(ent, str)
    ]
    if not rows:
        return

    # 3) Bulk insert with DO NOTHING on conflict
    stmt = (
        insert(EventEntities.__table__)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_event_entity_composite")
    )
    with SessionLocal() as sess:
        sess.execute(stmt)
        sess.commit()

def insert_commitments(event_id: int, summary_id: int, commits):
    """
    commits should be a Python list of dicts, e.g.
    [
      {
        'commitment_name': 'Tariff Reduction …',
        'commitment_description': '…',
        'commitment_amount': 123,
        'commitment_status': '2024-11-05'
      },
      …
    ]
    """
    # 1) If somehow they come in as a JSON/Python string, parse them:
    if isinstance(commits, str):
        try:
            commits = json.loads(commits)
        except json.JSONDecodeError:
            commits = ast.literal_eval(commits)

    if not isinstance(commits, list):
        return

    # 2) Build rows
    rows = []
    for rec in commits:
        if not isinstance(rec, dict):
            continue
        name   = rec.get("commitment_name")
        desc   = rec.get("commitment_description")
        amount = rec.get("commitment_amount")
        status = rec.get("commitment_status")

        if not name:
            continue

        rows.append({
            "event_id":                int(event_id),
            "event_summary_id":        int(summary_id),
            "commitment_purpose":      name,
            "commitment_description":  desc,
            "commitment_amount":       int(amount) if amount is not None else None,
            "commitment_status":       status,  # will be cast to DATE
        })

    if not rows:
        return

    # 3) Bulk insert
    stmt = (
        insert(Commitments.__table__)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_commitment_composite")
    )

    with SessionLocal() as sess:
        sess.execute(stmt)
        sess.commit()
def normalize_for_psycopg(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        # 1) if it’s a numpy scalar, cast it
        if isinstance(v, np.generic):
            out[k] = v.item()
        # 2) if it’s a list / dict that needs to go into a TEXT/JSON column,
        #    json-serialize it (and make sure nested numbers get cast too)
        elif isinstance(v, (list, dict)):
            out[k] = json.dumps(v, default=lambda x: x.item() if isinstance(x, np.generic) else x)
        else:
            out[k] = v
    return out

def fetch_filtered_events(country,recipient):
    stmt =  (select(Event,EventSources.doc_id,Document.date,Document.source_name,Document.distilled_text)
            # .join(Document,Document.doc_id==RawEvent.doc_id)
            # .join(InitiatingCountry,InitiatingCountry.doc_id==RawEvent.doc_id)
            # .join(RecipientCountry,RecipientCountry.doc_id==RawEvent.doc_id)
            .join(EventSources,EventSources.event_id==Event.id)
            .join(Document,EventSources.doc_id==Document.doc_id)
            .filter(Event.initiating_country==country,
                    Event.recipient_country==recipient))
    with engine.connect() as conn: 
        edf = pd.read_sql(stmt, conn)
        
        event_cnt = edf.groupby('event_name',as_index=False).count().sort_values(by='doc_id',ascending=False)
        event_cnt['count'] = event_cnt['doc_id']
        event_cnt=event_cnt[['event_name','count']]
        event_cnt = event_cnt[event_cnt['count']>5]
        events =list(set(event_cnt['event_name']))

    return events,edf

event_sys_prompt = '''You are an expert at tracking {country}'s soft power initiatives and a professional news editor for a journal that writes on soft power activities in the middle east. You have won awards for accurate, insightful, detailed, and memorable copy. Your readers are policy makers looking to stay up to speed on {country}'s soft power efforts. You are tasked with writing a summary paragraph of the following soft power activity as presented by media outlets listed. Please do the following:

Todays Date: {current_date}

Soft Power Event: {event_name}

Event recipient: {recipient}

Event Date range: {start} through {end}

Total reports written from {start} to {end}: {total_records}

Number of Records by Date:

{event_daily_metrics}

Comparison with other {country} - {recipient} events:

{event_comparison}

INSTRUCTIONS:
1. Write a title that encapsulates the main takeaway from the {event_name}. 
2. Provide a summary of the {event_name} based on the text in the combined texts. Focus on {country} and {recipient}'s role in the event. The summary should be specific and detailed discussing the status of the event, outcomes, personnel and countries involved, and implications of the event in regards to {country}'s use of soft power towards {recipient}. 
2. Using the list of latitude and longitudes, provide a consolidated latitude and longitude, if more than one location is represented, separate the lat long with semicolons. 
3. Using the list of locations, provide a consolidated list of locations where the {event_name} occured, if multiple locations are represented, separate each location with a semicolon.
4. If referenced, provide a list of monetary values provisioned, promised, or estimated relevant to the event between {country} and {recipient} and describe what the money is intended for, also specify  if the money has been given, promised, or estimated. Provide a list in the format [{{"amount": <US DOLLAR AMOUNT AS A NUMBER (i.e 2 million should be 2000000)>,"purpose":<PURPOSE OF THE FUNDS>,"status": "<disbursed|committed|estimated|pending>"}},...]
5. If referenced, provide a list of key persons, organizations, or government entities from {country} or {recipient} involved in the event. 
6. If referenced, list any specific commitments, signed agreements, status updates, that specifically resulted from the event between {country} and {recipient}. Provide as a list [{{"commitment_name":<PROVIDE A DESCRIPTIVE NAME FOR THE COMMITMENT>,"commitment_purpose": "<disbursed|committed|estimated|pending>","commitment_amount": <US DOLLAR AMOUNT AS A NUMBER (i.e 2 million should be 2000000)>, "commitment_status":"<completed|ongoing|scheduled>","commitment_description": <DESCRIPTION OF COMMITMENT BETWEEN {country} and {recipient}>}},...]
7. Determine the status of the event, whether it has COMPLETED, ONGOING, or SCHEDULED, if occured, provide the date it occured, if ongoing, provide the date of the latest update, if upcoming, provide the scheduled date. This should be provided as {{"status": "<completed|ongoing|scheduled>", "status_date": "<STATUS DATE>"}}
8. Review the number of records by date and provide an insight based on the metrics over time. 
9. Output the result in json, for example: {{"title": "<TITLE>", "event_summary": "<SUMMARY_TEXT>","event_latlong": "<LAT_LONG>","event_location": "<EVENT_LOCATION>", "monetary_value": "<LIST OF MONETARY VALUES AND THEIR INTENDED USE IN USD IF PROVIDED>", "entities": [<LIST OF KEY PERSONS,ORGANIZATION,OR GOVERNMENT ENTITIES>],"commitments":[LIST OF COMMITMENTS,SIGNED AGREEMENTS RESULTING FROM THE EVENT],"metrics": "<METRICS INSIGHT>","status": "<completed|ongoing|scheduled>"}}

IMPORTANT: ONLY return the json results. ONLY use the json format.

KEY STYLE RULES:
-Use the Associated Press Style guide and the inverted pyramid writing style.
- The report should only express facts regarding the soft power activity, not opinions or language that qualifies the soft power activity.

-DO NOT provide a concluding sentence that attempts to underscore, highlight, or sum up the soft power activities, just report the activities. 
- Write in the active voice.
- Write in the past tense.
- Always render references to {country} as a state actor as "PRC." DO NOT ever refer to it as "{country}." Again, output "PRC" not "{country}."
- Frame the summary as "Media coverage of..."
_ Reference the time period of media coverage up front.  
- Render dates ONLY in the format of numeric day and then name of month, e.g. 9 May, 15 June, 16 September, etc.
- Render references to the United States as United States when the subject or object of a sentence but as "US" (no periods) when used as an adjective, e.g. "US President," "US Senate," etc.
- Do NOT attempt to discern, infer, or convey the political implications of the media coverage or government rhetoric.
'''
def process_event(country,recipient,events,edf):    
    with Session(engine) as sess:
        for e in events:
            # print(e)
            e_df = edf[edf['event_name']==e]
            e_df.reset_index(inplace=True,drop=True)
            event_id = int(e_df['id'][0])
            print(event_id)
            start_date  = e_df['date'].min().strftime('%Y-%m-%d')
            end_date = e_df['date'].max().strftime('%Y-%m-%d')
            e_df = e_df[['doc_id','date','source_name','distilled_text']]
            doc_ids = e_df['doc_id'].tolist()
            combined_texts = str(e_df.to_dict(orient='records'))
            total_records = len(e_df)
            daily_counts = (
                e_df
                .groupby('date')       # group by that date
                .size()               # count rows in each group
                .reset_index(name='count')
            )
            event_daily_metrics = f'{e.upper()} article count by date: \n\n{str(daily_counts.to_markdown())}'

            print(e)
            event_comparison = f'Compare {e} to other event article counts:\n\n{edf.to_markdown()}'
            sys_prompt = event_sys_prompt.format(country=country,recipient=recipient,current_date=current_date,start=start_date,end=end_date,total_records=total_records,event_daily_metrics=event_daily_metrics,event_name=e,event_comparison=event_comparison)
            event_response = gpt_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": sys_prompt,
                },
                {
                    "role": "user",
                    "content": combined_texts,
                }
            ],
            max_completion_tokens=5000,
            temperature=1.0,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            model=deployment
            )

            response = event_response.choices[0].message.content
            rec = parse_llm_dict(response)
            commit_list = rec.get("commitments") or []
            
            data = {
                'event_id':         event_id,
                'doc_ids':          json.dumps(doc_ids),                  # list → JSON string
                'event_name':       e,
                'event_title':      rec.get('title'),
                'atom_start_date':  start_date,
                'atom_end_date':    end_date,
                'event_summary':    rec.get('event_summary'),
                'event_latlong':    rec.get('event_latlong'),
                'event_location':   rec.get('event_location'),
                'monetary_value':   json.dumps(rec.get('monetary_value')),   # list → JSON
                'entities':         json.dumps(rec.get('entities')),         # list → JSON
                'commitments':      json.dumps(rec.get('commitments')),      # list of dicts → JSON
                'metrics':          rec.get('metrics'),
                'status':           json.dumps(rec.get('status')),          # dict → JSON
                'status_date':      rec.get('status_date'),
            }
            # data = normalize_for_psycopg(data)
            stmt = insert(EventSummary.__table__).values(data)
            stmt = stmt.on_conflict_do_nothing(constraint="uq_event_summary_composite")
            sess.execute(stmt)
            sess.commit()
            try:
                print(f'inserting {event_id} summary ...')
                event_summary_id = get_event_summary_id(event_id,e)
                print(event_summary_id)
                print('inserting entities')
                insert_event_entities(event_id, event_summary_id, data)
                print(data['commitments'])
                print('inserting commitments...')
                insert_commitments(event_id=event_id,summary_id=event_summary_id,commits=commit_list)
            except:
                print(f'error processing {e}...')
                continue

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("Dedupe SoftPower Events")
    parser.add_argument("--country",   type=str, help="Initiating country")
    parser.add_argument("--recipient", type=str, help="Recipient country")
    args = parser.parse_args()
    
    targets = (
        [(args.country, args.recipient)]
        if args.country and args.recipient
        else [(c, r) for c in cfg.influencers for r in cfg.recipients]
    )

    for ctry, recip in targets:
        if ctry != recip:
            events,edf = fetch_filtered_events(ctry,recip)
            process_event(ctry,recip,events=events,edf=edf)
