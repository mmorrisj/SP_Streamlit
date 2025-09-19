import sqlite3
import re
import json
import os
import boto3
from botocore.exceptions import ClientError
from openai import AzureOpenAI
from backend.scripts.utils import Config, gai, fetch_gai_content
from backend.scripts.utils import find_json_objects,concatenate_files
from collections import defaultdict
import pandas as pd
from datetime import datetime

def load_sql(command):
    sql_file = os.path.join('./kuwait/sql', f'{command}.sql')
    with open(sql_file, "r") as f:
        sql_command = f.read()
    return sql_command

def sql(conn,command,data=None):
    cursor = conn.cursor()
    if data:
        cursor.execute(command,check_tuple(data))
    else:
        cursor.execute(command) 

def load_schema():
    cmd = load_sql('schema')
    cursor.executescript(cmd)
    conn.commit()

def parse_date(date_str):
        # Parse the date string and convert it to the desired format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime('%Y-%m-%d')

def fetch_atom_files(directory="./backend/atom/processed"):
    df = concatenate_files(directory)
    if len(df)<1:
        print("No data loaded")
        return
    df = df.drop_duplicates()
    df.reset_index(inplace=True,drop=True)
    df['date'] = df['Source Date, Start'].apply(parse_date)
    return df

def get_secret():
 
    secret_name = "AZURE_OPENAI_API_KEY_NORTHCENTRALUS"
    region_name = "us-east-1"
 
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
 
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e
 
    secret = get_secret_value_response['SecretString']
    return secret
 

secret_string = get_secret()

credentials = json.loads(secret_string)
client = AzureOpenAI(
    azure_endpoint=credentials["endpoint"],
    api_key=credentials["key"],
    api_version="2024-08-01-preview",
)

def fetch_gai_content(response):
    import ast
    try:
        # Attempt to evaluate the content of the response as a Python literal structure
        gai_output = ast.literal_eval(response['choices'][0]['message']['content'])
    except:
        # If evaluation fails, find JSON objects within the content
        gai_output = find_json_objects(response['choices'][0]['message']['content'])
    return gai_output

def gai(sys_prompt, user_prompt, model="gpt-4o-mini"):
    # Create a chat completion using the specified model and prompts
    completion = client.chat.completions.create(
        model=model, 
        messages=[
            {
                "role": "system",
                "content": sys_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )
    # Return the completion as a JSON object
    return json.loads(completion.model_dump_json())

def process_output(output):
    if isinstance(output,dict):
        return output
    if isinstance(output,list):
        return output[0]
    
def process_salience(gai_output):
    gai_output = process_output(gai_output)
    if str(gai_output['salience']).lower() == 'false':
        return False
    if str(gai_output['salience']).lower() == 'true':
        return True

def run_salience(conn,df):
    salience_prompt = '''You are an international relations expert on the use of Soft Power influence from one country towards another country. Soft power is the ability of a country to shape the preferences and behaviors of other nations through appeal and attraction rather than coercion or payment. This influence is exerted through cultural diplomacy, values, policies, political ideals, educational exchanges, and media, fostering goodwill and fostering mutual understanding. Soft power aims to build positive relationships and international cooperation by enhancing a country's reputation and credibility globally.

    Please execute the following steps,

    1. Assess whether the given text is an example of the use of soft power influence as defined above.
    2. Output the result in json, for example {"salience": true } or {"salience": false}
    IMPORTANT: ONLY OUTPUT THE JSON RESULT.'''
    total = 0
    count = 0
    atoms = [dict(x)['atom_id'] for x in cursor.execute('''SELECT atom_id FROM atom''').fetchall()]
    df = df[~df['ATOM ID'].isin(atoms)]
    df.reset_index(inplace=True,drop=True)
    for i in range(len(df)):
        row = df.iloc[i]
        atom_id = row['ATOM ID']
        title = row['Title']
        body = row['BODY']
        source_name = row['Source Name']
        date = row['date']
        user_prompt = f'{title}: {body}'
        sys_prompt = salience_prompt
        try:
            response = gai(sys_prompt,user_prompt,model="gpt-4o-mini")
            gai_output = fetch_gai_content(response)
            salience = process_salience(gai_output)
        except:
            print(f"error processing {atom_id}")
            sql_command = load_sql('insert_error')
            data = (atom_id,'salience')
            cursor.execute(sql_command,data)
            continue
        sql_command = load_sql('insert_atom')
        data = (atom_id,date,title,source_name)
        cursor.execute(sql_command,data)
        sql_command = load_sql('insert_salience')
        data = (atom_id,salience)
        print(f"processed {atom_id}: {salience}")
        cursor.execute(sql_command,data)
        count += 1
        total += 1
        if count == 50:
            conn.commit()
            print(f"committed {total} files...")
            count = 0
    conn.commit()

if __name__ == "__main__":
    conn = sqlite3.connect('./kuwait/kuwait_sp.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode = WAL;')
    cursor = conn.cursor()
    df = fetch_atom_files()
    if len(df) > 0:
        run_salience(conn,df)
    else:
        print("no data")
    