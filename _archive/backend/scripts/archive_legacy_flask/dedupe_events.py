import os
import json
import ast
import boto3
import pandas as pd
import time
from functools import wraps
from dotenv import load_dotenv
from datetime import timedelta

from sqlalchemy import (
    create_engine, select, UniqueConstraint
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert

from openai import AzureOpenAI

from backend.extensions import db
from backend.scripts.models import (
    RawEvent, Event, EventSources,EventSummary
)
from SoftPowerCLI import Config

# —————— Configuration ——————

load_dotenv()
cfg = Config.from_yaml()

DB_HOST      = "localhost"
DATABASE_URL = f"postgresql://matthew50:softpower@{DB_HOST}:5432/softpower-db"

engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# —————— Data Fetching & Counting ——————
def ensure_events_exist(df: pd.DataFrame, country: str, recipient: str):
    names_needed = set(df["consolidated_name"])
    with SessionLocal() as sess:
        # load what's already in DB
        existing = {
            e.event_name 
            for e in sess.query(Event.event_name)
                     .filter_by(
                         initiating_country=country,
                         recipient_country=recipient
                     )
        }
        missing = names_needed - existing
        if not missing:
            return

        # bulk-insert missing names
        to_ins = [
            {
                "event_name": name,
                "initiating_country": country,
                "recipient_country": recipient
            }
            for name in missing
        ]
        stmt = (
            insert(Event.__table__)
            .values(to_ins)
            .on_conflict_do_nothing(constraint="uq_events_name_countries")
        )
        sess.execute(stmt)
        sess.commit()

def fetch_events(country,recipient):
    stmt =  (select(Event,EventSources.doc_id)
            .join(EventSources,EventSources.event_id==Event.id)
            .filter(Event.initiating_country==country,
                    Event.recipient_country==recipient))
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df

def event_records(df: pd.DataFrame) -> dict[int, dict]:
    """
    Build an ephemeral ID -> { event_name, count } map
    for events having >2 records, sorted by count descending.
    """
    cnt = (
        df.groupby("event_name", as_index=False)
          .doc_id.count()
          .rename(columns={"doc_id":"count"})
          .query("count > 2")
          .sort_values("count", ascending=False)
    )
    records = cnt.to_dict(orient="records")
    return {i+1: rec for i, rec in enumerate(records)}

# —————— GPT Consolidation ——————

def get_db_secret(secret_name: str, region: str = "us-east-1") -> dict:
    boto3_session = boto3.Session()
    client = boto3_session.client("secretsmanager", region_name=region)
    secret = client.get_secret_value(SecretId=secret_name)
    return json.loads(secret["SecretString"])

def initialize_client() -> AzureOpenAI:
    creds = get_db_secret("azure-open-ai-credentials")
    return AzureOpenAI(
        azure_endpoint=creds["GPT_4_1_ENDPOINT"],
        api_key=creds["GPT_4_1_KEY"],
        api_version="2024-10-21",
        timeout=60,
    )

def rate_limit(min_interval):
    """
    Decorator to enforce a minimum time between calls to a function.
    """
    def decorator(func):
        last_time = [0]
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_time[0]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            result = func(*args, **kwargs)
            last_time[0] = time.time()
            return result
        return wrapper
    return decorator

def fetch_event_records(country,recipient):
    df = fetch_events(country=country,recipient=recipient)
    id_dct = event_records(df)
    return id_dct

@rate_limit(min_interval=10.0)
def fetch_gai_response(id_dct):
    import re
    gpt_client = initialize_client()
    secret_name = "azure-open-ai-credentials"
    secret_dict = get_db_secret(secret_name)
    deployment = secret_dict['GPT_4_1_DEPLOYMENT_NAME']
    sys_prompt = '''
    You are an expert data analyst and consolidator of event lists. Review the following list of event names and consolidate duplicative or near duplicative events by returning a list of ids with the old id on the left and the consolidated id on the right. for example :

    In: 
    {'event_name': "China's Strategic Engagement in the Middle East",
    'count': 319,
    'id': 4},
    {'event_name': 'BRICS Summit 2024 in Kazan', 'count': 178, 'id': 5},
    {'event_name': "China's Diplomatic and Technological Influence in the Middle East",
    'count': 173,
    'id': 6},
    {'event_name': 'BRICS Summit in Kazan', 'count': 128, 'id': 7},
    {'event_name': 'China-Iran Economic and Diplomatic Engagement',
    'count': 123,
    'id': 8},
    {'event_name': 'BRICS Summit and BRICS Plus Meeting in Kazan',
    'count': 113,
    'id': 10}...

    Since 'BRICS Summit 2024 in Kazan' and 'BRICS Summit in Kazan' are referencing the same summit, they should be consolidated, the consolidated name is the one with the highest 'count', so the consolidated output for these events would  be [[7,5],[10,5],...]

    Look across the provided list and identify similar instances of near duplicative event names and output a consolidated list of their ids.
    Not every event_name needs to be condolidated, only consolidate the events that are clearly referencing the same event or are near duplicates.

    IMPORTANT: ONLY output the list of consolidated  ids
    '''
    user_prompt = str(id_dct)


    response = gpt_client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": sys_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        max_completion_tokens=5000,
        temperature=1.0,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        model=deployment
    )
    raw = response.choices[0].message.content
    m = re.search(r"(\[.*\])", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Couldn't parse list from model response:\n{raw!r}")
    list_literal = m.group(1)
    return ast.literal_eval(list_literal)


# —————— 3) Build a DataFrame of name-pairs ——————

def build_consolidated_df(consolidated_list: list[list[int]],
                          id_dct: dict[int, dict]) -> pd.DataFrame:
    """
    Returns a DataFrame with columns ['original_name','consolidated_name'].
    """
    rows = [
        [id_dct[a]["event_name"], id_dct[b]["event_name"]]
        for a, b in consolidated_list
        if a in id_dct and b in id_dct
    ]
    return pd.DataFrame(rows, columns=["original_name","consolidated_name"])

# —————— 4) Update existing rows ——————

def update_events(df: pd.DataFrame, country: str, recipient: str):
    from backend.scripts.models import Commitments  # adjust if needed
    with SessionLocal() as sess:
        # 1) Build name → id map
        name_map = {
            e.event_name: e.id
            for e in sess.query(Event)
                         .filter_by(
                             initiating_country=country,
                             recipient_country=recipient
                         )
        }

        orig_ids_to_delete = set()

        for _, row in df.iterrows():
            orig_id = name_map.get(row["original_name"])
            cons_id = name_map.get(row["consolidated_name"])
            if not orig_id or not cons_id:
                print("Skipping missing mapping:", row.to_dict())
                continue

            # Remove any conflicting event_sources as before
            sess.query(EventSources).filter(
                EventSources.event_id == cons_id,
                EventSources.doc_id.in_(
                    sess.query(EventSources.doc_id).filter(EventSources.event_id == orig_id)
                )
            ).delete(synchronize_session=False)

            # Update all event_sources rows to new canonical event_id
            sess.query(EventSources) \
                .filter(EventSources.event_id == orig_id) \
                .update({ EventSources.event_id: cons_id }, synchronize_session=False)

            # Gather event_summaries ids for this orig_id
            summary_ids = [
                s.id for s in sess.query(EventSummary.id)
                                 .filter(EventSummary.event_id == orig_id)
                                 .all()
            ]

            # --- (NEW) Delete all commitments referencing these summaries
            if summary_ids:
                sess.query(Commitments) \
                    .filter(Commitments.event_summary_id.in_(summary_ids)) \
                    .delete(synchronize_session=False)

            # Delete all event_summaries attached to the soon-to-be-deleted orig_id
            sess.query(EventSummary) \
                .filter(EventSummary.event_id == orig_id) \
                .delete(synchronize_session=False)

            orig_ids_to_delete.add(orig_id)

        # Delete the deduped events now that nothing references them
        if orig_ids_to_delete:
            sess.query(EventSources) \
                .filter(EventSources.event_id.in_(orig_ids_to_delete)) \
                .delete(synchronize_session=False)
            sess.query(Event) \
                .filter(Event.id.in_(orig_ids_to_delete)) \
                .delete(synchronize_session=False)

        sess.commit()
def dedupe(country: str, recipient: str):
    print(f"Dedupe {country} → {recipient}")
    id_dct = fetch_event_records(country, recipient)
    if not id_dct:
        print("No event groups with >2 records. Skipping.")
        return

    pairs = fetch_gai_response(id_dct)
    if not pairs:
        print("No duplicates found. Skipping.")
        return

    cdf = build_consolidated_df(pairs, id_dct)
    if cdf.empty:
        print("Consolidation yielded no valid rows. Skipping.")
        return
    ensure_events_exist(cdf, country, recipient)
    update_events(cdf, country, recipient)
    print("Update complete.")

CHECKPOINT_FILE = "checkpoints/checkpoints.json"

def load_checkpoints():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    else:
        return {"completed": [], "failed": []}

def save_checkpoints(checkpoints):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoints, f, indent=2)

def mark_checkpoint(checkpoints, ctry, recip, status):
    key = f"{ctry}→{recip}"
    if status == "completed":
        if key not in checkpoints["completed"]:
            checkpoints["completed"].append(key)
        if key in checkpoints["failed"]:
            checkpoints["failed"].remove(key)
    elif status == "failed":
        if key not in checkpoints["failed"]:
            checkpoints["failed"].append(key)
    save_checkpoints(checkpoints)

def already_processed(checkpoints, ctry, recip):
    key = f"{ctry}→{recip}"
    return key in checkpoints["completed"]

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

    checkpoints = load_checkpoints()

    for ctry, recip in targets:
        if ctry == recip or already_processed(checkpoints, ctry, recip):
            print(f"Skipping {ctry}→{recip} (already done or same country)")
            continue
        try:
            dedupe(ctry, recip)
            mark_checkpoint(checkpoints, ctry, recip, "completed")
            print(f"✔️  Completed: {ctry}→{recip}")
        except Exception as e:
            print(f"❌ Error processing {ctry}→{recip}: {e}")
            mark_checkpoint(checkpoints, ctry, recip, "failed")