import sqlite3
import re
import json
import os
import boto3
from botocore.exceptions import ClientError
from openai import AzureOpenAI
from shared.utils.utils import Config, gai, fetch_gai_content
from shared.utils.utils import find_json_objects,concatenate_files
from collections import defaultdict
import pandas as pd
from datetime import datetime
current_date = datetime.now()
date_string = current_date.strftime("%Y-%m-%d")

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

def parse_date(date_str):
        # Parse the date string and convert it to the desired format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime('%Y-%m-%d')

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

def fetch_atom_files(directory="./backend/atom/processed"):
    df = concatenate_files(directory)
    if len(df)<1:
        print("No data loaded")
        return
    df = df.drop_duplicates()
    df.reset_index(inplace=True,drop=True)
    df['date'] = df['Source Date, Start'].apply(parse_date)
    return df

def insert_extract(atom_id,output):
    sql_command = load_sql('insert_extract')
    salience = process_salience(output)
    data = (atom_id,
            salience,
            output['salience-justification'],
            output['category'],
            output['category-justification'],
            output['subcategory'],
            output['initiating-country'],
            output['recipient-country'],
            output['projects'],
            output['LAT_LONG'],
            output['location'],
            output['monetary-commitment'],
            output['distilled-text'],
            output['event-name'])
    cursor.execute(sql_command,data)

def run_extraction(conn,df):
    extraction_prompt = '''You are an expert in tracking and identifying inter-country 'soft power' engagements, where one country through economic, social, cultural, or political means, fosters influence over another country.

Please execute the following steps and output the results using the provided json template.
1. Determine if the focus of the following text is a soft power-related event or influence activity of one country towards another. Ensure that the context in which soft power is discussed is significant and substantial, not merely a passing reference. Avoid flagging articles that only broadly mention a soft power relevant event without focusing on specific events or initiatives. Exclude articles that primarily focus on unrelated topics with only a tangential mention of a soft power relevant event.
2. If it is, in 200 words or less, explain why the text was determined to be either an example of soft power or not an example of soft power. 
3. If the text is an example of soft power, identify the nature of the activity and output one or more of the following categories, if more than one topic is relevant, separate them by semicolons.
          1)  "Economic":  Characterized by the use of economic tools and policies to influence other countries' behaviors and attitudes. Articles should be classified as Economic only if a specific deal, exchange, or market is referenced, otherwise general non-specific discussions of economic ties should be binned under "Diplomacy".   
          2)  "Social":  Characterized by the use of cultural, ideological, and social tools to influence other countries' behaviors and attitudes, fostering admiration, respect, and alignment with a country's values and way of life. This category includes financial and material donations or aid.
          3)  “Diplomacy":  Characterized by the use of diplomatic channels, negotiations, and international relations to shape the preferences, attitudes, and behaviors of other nations in a way that aligns with a country’s interests. 
          4)  “Military": Characterized by the strategic use of military resources and capabilities to build goodwill, foster international cooperation, and project a positive image without engaging in direct military conflict or coercion.
4. In 200 words or less, explain why the specific category or categories was selected.
5. Next, from the provided text, determine which of the following subcategories aligns best to the context of the provided text as a whole. Each category MUST have a sub-category.

    If the overall category is "Economic", determine which of the following sub-categories aligns best to the context of the text:
    A. Trade
    B. Food
    C. Finance
    D. Technology
    E. Transportation
    F. Tourism
    G. Industrial
    H. Raw Materials
    I. Infrastructure
    J. If the economic activity doesn't fall within any of the above categories, return "Other-" with a one word label of the activity.

    If the overall category is "Social", determine which of the following sub-categories aligns best to the context of the text:
    A. Cultural
    B. Education
    C. Healthcare
    D. Housing
    E. Media
    F. Politics
    G. Religious
    H. Aid/Donation
    I. If the social activity doesn't fit any of the above categories, return "Other-"with a one word label of the activity. 

    If the nature of the activity is "Diplomacy", determine which of the following diplomacy subcategories the activity falls under:
    A. Multilateral/Bilateral Commitments
    B. International Negotiations
    C. Conflict Resolution
    D. Global Governance Participation
    E. Diaspora Engagement
    F. If the Diplomacy activity doesn't fit any of the above categories, return "Other-"with a one word label of the activity.

    If the overall category is "Military", determine which of the following sub-categories aligns best to the context of the text:
    A. Sales
    B. Joint Exercises
    C. Training
    D. Conferences
    E. If the military activity doesn't fall under any of these, return "Other-" with a one word label of the activity. 
6. Determine the country initiating the softpower exchange from the provided text.  If more than one initiating country is identified, separate them with semicolons. 

7. Determine the recipient country of the softpower exchange from the provided text. If more than one recipient country is identified, separate them with semicolons. The initiating and recipient country should never be the same. 

8. Identify specific projects, conferences, or initiative names, for example, "Maputo Central Hospital," "National Theater Renovation Project," or "Tengchong-Myitkyina Road Construction Project;Opium Alternative Planting Project." If more than one is found, separate them with semicolons.

9. Provide the approximate latitude and longitude of the activity, if unavailable, provide the Latitude and longitude of the nearest locality or recipient country.  

10. Provide the nearest locality of the event, for example "Tehran, Iran".

11. Identify and output the monetary commitment of the activity of commitment in USD, for example "$100,000,000."

12. Distill the content of the text to only the context relevant to a soft power exchange. All locations, persons, projects, and monetary values should remain in the distilled output. Provide this output in english.

13. Produce an event name that capture the soft power interaction and key actors or entities involved.

14. Output the result in json, for example {"salience-justification": "Reason the text is an example of soft power.", "salience-bool": <BOOLEAN>, "category": "<CATEGORY TEXT>", "category-justification": "<JUSTIFICATION TEXT>", "subcategory": "<SUBCATEGORY TEXT>", "initiating-country": "<COUNTRY TEXT>", "recipient-country": "<COUNTRY TEXT>", "projects": "<REFERENCED PROJECTS LIST>", "LAT_LONG": "<LATITUDE AND LONGITUDE>","location": "<LOCATION TEXT>", "monetary-commitment": "<REFERENCED MONETARY VALUES>", "distilled-text": "<DISTILLED TEXT>","event-name": "<EVENT NAME>"}, {"salience-justification": "<JUSTIFICATION TEXT>", "salience-bool": false}.

IMPORTANT: ONLY output the json. ONLY use the json format. ALL output values should ONLY be in English.
'''
    results_file = f"./backend/atom/extraction_results_{date_string}.json"
    os.makedirs(os.path.dirname(results_file), exist_ok=True)
    if os.path.exists(results_file):
        with open(results_file, 'r') as f:
            previous_results = json.load(f)
        processed_atoms = set()
        for r in previous_results:
            processed_atoms.update(r.keys())
    else:
        previous_results = []
        processed_atoms = set()
    salient_atoms = [dict(x)['atom_id'] for x in cursor.execute('''SELECT atom_id FROM salience WHERE salience==1''').fetchall()]
    salient_df = df[df['ATOM ID'].isin(salient_atoms)]
    salient_df.reset_index(inplace=True,drop=True)
    atom_extracts = [dict(x)['atom_id'] for x in cursor.execute('''SELECT atom_id FROM extract''').fetchall()]
    salient_df = salient_df[~salient_df['ATOM ID'].isin(atom_extracts)]
    salient_df = salient_df[~salient_df['ATOM ID'].isin(processed_atoms)]
    salient_df.reset_index(inplace=True,drop=True)
    errors = []
    count = 0
    results = previous_results.copy()
    for i in range(len(salient_df)):
        result = {}
        row = salient_df.iloc[i]
        atom_id = row['ATOM ID']
        title = row['Title']
        body = row['BODY']
        user_prompt = f'{title}: {body}'
        sys_prompt = extraction_prompt
        
        response = gai(sys_prompt,user_prompt,model="gpt-4o")
        gai_output = fetch_gai_content(response)
        output = process_output(gai_output)
        result[atom_id] = output
        results.append(result)
        print(f"processed {atom_id}")
        count += 1
        if count == 25:
            count = 0
            with open(results_file,'w') as f: 
                json.dump(results,f,indent=4)
                print('results saved...')
     
if __name__ == "__main__":
    conn = sqlite3.connect('./kuwait/kuwait_sp.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode = WAL;')
    cursor = conn.cursor()
    df = fetch_atom_files()
    if len(df) > 0:
        run_extraction(conn,df)
    else:
        print("no data")
    
