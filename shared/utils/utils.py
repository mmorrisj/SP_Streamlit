import yaml
import json
import os
import re
import time
from pathlib import Path
import yaml
# from openai import AzureOpenAI
# import ast
import json
# import boto3
# from botocore.exceptions import ClientError
# import pandas as pd
from functools import wraps

class Config:
    def __init__(self, **entries):
        # Normalize any path fields
        for key, value in entries.items():
            if isinstance(value, str) and value.startswith('./'):
                entries[key] = str(Path(value).resolve())
        self.__dict__.update(entries)

    @classmethod
    def from_yaml(cls, yaml_path='./shared/config/config.yaml'):
        if yaml_path is None:
            yaml_path = Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'
        else:
            yaml_path = Path(yaml_path).resolve()

        with yaml_path.open('r') as file:
            config_data = yaml.safe_load(file) or {}
        return cls(**config_data)

    def __repr__(self):
        return f'Config({self.__dict__})'

cfg = Config.from_yaml()

def get_secret():
 
    secret_name = cfg.aws['secret_name']
    region_name = cfg.aws['region_name']
 
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
 
def initialize_client():
    secret_string = get_secret()

    credentials = json.loads(secret_string)
    client = AzureOpenAI(
        azure_endpoint=credentials["endpoint"],
        api_key=credentials["key"],
        api_version=cfg.aws['api_version'],
    )
    return client

def fetch_gai_content(response):
    import ast
    try:
        # Attempt to evaluate the content of the response as a Python literal structure
        gai_output = ast.literal_eval(response['choices'][0]['message']['content'])
    except:
        # If evaluation fails, find JSON objects within the content
        gai_output = find_json_objects(response['choices'][0]['message']['content'])
    return gai_output

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

@rate_limit(min_interval=10.0)
def fetch_gai_response(sys_prompt,prompt,model):
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


@rate_limit(min_interval=10.0)
def gai(sys_prompt, user_prompt, model="gpt-4o-mini", use_proxy=None):
    """
    LLM call that routes through FastAPI proxy (designed for production deployment).

    Args:
        sys_prompt: System prompt for the LLM
        user_prompt: User prompt for the LLM
        model: Model to use (default: gpt-4o-mini)
        use_proxy: If True, use FastAPI proxy. If False, attempt direct OpenAI.
                   If None (default), REQUIRES FASTAPI_URL environment variable.

    Environment Variables:
        FASTAPI_URL: Required. Full URL to FastAPI endpoint (e.g., http://127.0.0.1:5001/material_query)
                     Set this to enable LLM functionality.

    Returns:
        LLM response (parsed as JSON if possible, otherwise raw string)

    Raises:
        ValueError: If FASTAPI_URL is not configured and use_proxy is None
        requests.RequestException: If FastAPI proxy call fails
    """
    import requests

    # Determine routing mode
    if use_proxy is None:
        # Default mode: require FASTAPI_URL to be set
        fastapi_url = os.getenv('FASTAPI_URL', '').strip()

        if not fastapi_url:
            raise ValueError(
                "FASTAPI_URL environment variable not set. "
                "LLM calls require the FastAPI proxy to be configured. "
                "Set FASTAPI_URL=http://HOST:PORT/material_query in your .env file. "
                "To bypass the proxy (not recommended for production), call gai(..., use_proxy=False)."
            )

        use_proxy = True

    # Route through FastAPI proxy (recommended for production)
    if use_proxy:
        fastapi_url = os.getenv('FASTAPI_URL', '').strip()

        if not fastapi_url:
            # Try to construct from API_URL if available
            api_url = os.getenv('API_URL', '').strip()
            if api_url:
                fastapi_url = f"{api_url.rstrip('/')}/material_query"
            else:
                raise ValueError(
                    "FASTAPI_URL or API_URL environment variable must be set for proxy mode. "
                    "Example: FASTAPI_URL=http://127.0.0.1:5001/material_query"
                )

        print(f"  [PROXY] Calling LLM via FastAPI proxy: {fastapi_url}")

        payload = {
            "sys_prompt": sys_prompt,
            "prompt": user_prompt,
            "model": model
        }

        try:
            response = requests.post(fastapi_url, json=payload, timeout=120)
            response.raise_for_status()

            data = response.json()

            # Extract response content (FastAPI returns {"response": content})
            resp_content = data.get("response") if isinstance(data, dict) and "response" in data else data

            # Try to parse as JSON if it's a string
            if isinstance(resp_content, str):
                try:
                    return json.loads(resp_content)
                except json.JSONDecodeError:
                    # Try to extract JSON from markdown-wrapped response
                    match = re.search(r'(\[.*\]|\{.*\})', resp_content, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(1))
                        except json.JSONDecodeError:
                            pass
                    return resp_content

            return resp_content

        except requests.RequestException as e:
            error_msg = (
                f"FastAPI proxy call failed: {e}\n"
                f"  URL: {fastapi_url}\n"
                f"  Ensure the FastAPI server is running: uvicorn backend.api:app --host 0.0.0.0 --port 5001"
            )
            print(f"ERROR: {error_msg}")
            raise RuntimeError(error_msg) from e

    # Direct OpenAI call (for local development only - not recommended for production)
    else:
        print("  [WARNING] Bypassing FastAPI proxy and calling OpenAI directly")
        print("  [WARNING] This mode is for local development only and requires OPENAI_PROJ_API env var")

        try:
            from openai import OpenAI

            # Get API key from environment
            api_key = os.getenv('OPENAI_PROJ_API')
            if not api_key:
                raise ValueError(
                    "OPENAI_PROJ_API not found in environment. "
                    "For production deployments, use the FastAPI proxy instead (use_proxy=True)."
                )

            # Initialize OpenAI client
            client = OpenAI(api_key=api_key)

            # Make API call
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = completion.choices[0].message.content

            # If it's already a dict/list (parsed JSON)
            if isinstance(content, (dict, list)):
                return content

            # If it's a string, try parsing as JSON
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content  # just return raw string if not JSON

            # Fallback — return raw content
            return content

        except Exception as e:
            print(f"ERROR: Direct OpenAI call failed: {e}")
            raise


def clean_json_string(text):
    """
    Cleans the input text to prepare it for JSON parsing.
    - Removes Markdown code block delimiters.
    - Replaces single quotes around values with double quotes.
    - Handles escaped quotes and special characters.
    """
    # Remove Markdown code block delimiters
    text = text.strip().strip('```json').strip().strip('```').strip()

    # Replace single quotes around values with double quotes
    text = re.sub(r':\s*\'([^\']*)\'', r': "\1"', text)

    # Replace escaped single quotes within values
    text = text.replace("\\'", "'")
    text = text.replace('\\"', '"')

    # Handle special characters and ensure proper JSON formatting
    text = text.replace('\n', ' ').replace('\r', '')

    return text

def extract_jsons(text):
    """
    Attempts to extract JSON data from the input text.
    """
    cleaned_text = clean_json_string(text)
    
    # Attempt to load the cleaned JSON string
    try:
        json_data = json.loads(cleaned_text)
        return json_data
    except json.JSONDecodeError:
        return extract_json_regex(cleaned_text)

def extract_json_ast(text):
    """
    Attempts to extract JSON data using the ast.literal_eval method.
    """
    cleaned_text = clean_json_string(text)

    try:
        json_data = ast.literal_eval(cleaned_text)
        return json_data
    except (ValueError, SyntaxError):
        return None

def clean_and_extract_json(text):
    """
    Cleans the input text and attempts to extract JSON data.
    """
    cleaned_text = clean_json_string(text)
    
    # Replace single quotes around keys and values with double quotes
    cleaned_text = re.sub(r"'([^']*)'", r'"\1"', cleaned_text)

    try:
        json_data = json.loads(cleaned_text)
        return json_data
    except json.JSONDecodeError:
        return extract_json_ast(cleaned_text)

def extract_json_regex(text):
    """
    Attempts to extract JSON data using regular expressions.
    """
    cleaned_text = clean_json_string(text)
    
    # Replace single quotes around values with double quotes
    cleaned_text = re.sub(r'\'([^,{}[\]\s]*)\'', r'"\1"', cleaned_text)

    try:
        json_data = json.loads(cleaned_text)
        return json_data
    except json.JSONDecodeError:
        return clean_and_extract_json(cleaned_text)

def find_json_objects(text):
    """
    Finds and extracts JSON objects from the input text.
    """
    json_objects = []
    stack = []
    start = -1

    # Clean the text to handle escaped single quotes
    cleaned_text = re.sub(r'\\\'', "'", str(text)).replace("'s",'')

    # Iterate through the text character by character
    for i, char in enumerate(cleaned_text):
        if char == '{':
            if not stack:
                start = i
            stack.append(char)
        elif char == '}':
            if stack:
                stack.pop()
                if not stack:
                    # End of a JSON object
                    try:
                        json_str = cleaned_text[start:i+1]
                        json_str = json_str.replace('""', '"')
                        obj = json.loads(json_str)
                        json_objects.append(obj)
                        start = -1  # Reset start for the next object
                    except json.JSONDecodeError:
                        pass

    if json_objects:
        return json_objects
    else:
        return extract_jsons(cleaned_text)

def migrate_softpower_entities_table(engine):
    with engine.connect() as conn:
        try:
            print("Renaming old table...")
            conn.execute(text("ALTER TABLE softpower_entities RENAME TO softpower_entities_old;"))

            print("Creating new table with composite primary key...")
            conn.execute(text("""
                CREATE TABLE softpower_entities (
                    sp_id INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    PRIMARY KEY (sp_id, entity)
                );
            """))

            print("Copying data (de-duplicated)...")
            conn.execute(text("""
                INSERT INTO softpower_entities (sp_id, entity)
                SELECT DISTINCT sp_id, entity FROM softpower_entities_old;
            """))

            print("Dropping old table...")
            conn.execute(text("DROP TABLE softpower_entities_old;"))

            print("✅ Migration complete: softpower_entities now uses (sp_id, entity) as primary key.")
        except SQLAlchemyError as e:
            print("❌ Migration failed:", e)
            conn.rollback()

    
def clean_json_string(text):
    """
    Cleans the input text to prepare it for JSON parsing.
    - Removes Markdown code block delimiters.
    - Replaces single quotes around values with double quotes.
    - Handles escaped quotes and special characters.
    """
    # Remove Markdown code block delimiters
    text = text.strip().strip('```json').strip().strip('```').strip()

    # Replace single quotes around values with double quotes
    text = re.sub(r':\s*\'([^\']*)\'', r': "\1"', text)

    # Replace escaped single quotes within values
    text = text.replace("\\'", "'")
    text = text.replace('\\"', '"')

    # Handle special characters and ensure proper JSON formatting
    text = text.replace('\n', ' ').replace('\r', '')

    return text

def extract_jsons(text):
    """
    Attempts to extract JSON data from the input text.
    """
    cleaned_text = clean_json_string(text)
    
    # Attempt to load the cleaned JSON string
    try:
        json_data = json.loads(cleaned_text)
        return json_data
    except json.JSONDecodeError:
        return extract_json_regex(cleaned_text)

def extract_json_ast(text):
    """
    Attempts to extract JSON data using the ast.literal_eval method.
    """
    cleaned_text = clean_json_string(text)

    try:
        json_data = ast.literal_eval(cleaned_text)
        return json_data
    except (ValueError, SyntaxError):
        return None

# def clean_and_extract_json(text):
#     """
#     Cleans the input text and attempts to extract JSON data.
#     """
#     cleaned_text = clean_json_string(text)
    
#     # Replace single quotes around keys and values with double quotes
#     cleaned_text = re.sub(r"'([^']*)'", r'"\1"', cleaned_text)

#     try:
#         json_data = json.loads(cleaned_text)
#         return json_data
#     except json.JSONDecodeError:
#         return extract_json_ast(cleaned_text)

# def extract_json_regex(text):
#     """
#     Attempts to extract JSON data using regular expressions.
#     """
#     cleaned_text = clean_json_string(text)
    
#     # Replace single quotes around values with double quotes
#     cleaned_text = re.sub(r'\'([^,{}[\]\s]*)\'', r'"\1"', cleaned_text)

#     try:
#         json_data = json.loads(cleaned_text)
#         return json_data
#     except json.JSONDecodeError:
#         return clean_and_extract_json(cleaned_text)

# def find_json_objects(text):
#     """
#     Finds and extracts JSON objects from the input text.
#     """
#     json_objects = []
#     stack = []
#     start = -1

#     # Clean the text to handle escaped single quotes
#     cleaned_text = re.sub(r'\\\'', "'", str(text)).replace("'s",'')

#     # Iterate through the text character by character
#     for i, char in enumerate(cleaned_text):
#         if char == '{':
#             if not stack:
#                 start = i
#             stack.append(char)
#         elif char == '}':
#             if stack:
#                 stack.pop()
#                 if not stack:
#                     # End of a JSON object
#                     try:
#                         json_str = cleaned_text[start:i+1]
#                         json_str = json_str.replace('""', '"')
#                         obj = json.loads(json_str)
#                         json_objects.append(obj)
#                         start = -1  # Reset start for the next object
#                     except json.JSONDecodeError:
#                         pass

#     if json_objects:
#         return json_objects
#     else:
#         return extract_jsons(cleaned_text)

# def concatenate_files(directory, columns=None,insert_value=None,str_value=None,num_docs=None,sort_by=None):
#     """
#     Concatenates all Excel files in the specified directory into a single DataFrame.
    
#     Parameters:
#     - directory (str): The path to the directory containing Excel files.
#     - columns (list of str, optional): If specified, the resulting DataFrame will include these columns only.
    
#     Returns:
#     - pd.DataFrame: A DataFrame containing the concatenated data from all Excel files in the directory.
#     """
#     # Initialize the DataFrame with specified columns if provided
#     if columns:
#         df = pd.DataFrame(columns=columns)
#     else:
#         df = pd.DataFrame()

#     # Iterate through all files in the directory
#     for filename in os.listdir(directory):
#         if filename.endswith('.xlsx'):
#             if str_value:
#                 if str_value in filename:
#                     file_path = os.path.join(directory, filename)
#                 else:
#                     continue
#             else:   
#                 file_path = os.path.join(directory, filename)
#             # Read the Excel file into a DataFrame
#             try:
#                 # Test for 1toN output
#                 file_df = pd.read_excel(file_path, sheet_name='Outputs')
            
#             except:
#                 #otherwise load first sheet
#                 file_df = pd.read_excel(file_path)
            
#             if insert_value:
#                 for k,v in insert_value.items():
#                     file_df[k] = v
#             if sort_by:
#                 # Sort by the 'Score' column in descending order
#                 file_df = file_df.sort_values(by=sort_by, ascending=False)
                
#             if num_docs:
#                 file_df = file_df[:num_docs]
            
#             # If columns are specified, ensure the file DataFrame has those columns
#             if columns:
#                 file_df = file_df[columns]

#             # Concatenate the DataFrame with the main DataFrame
#             df = pd.concat([df, file_df])
#     df.reset_index(drop=True,inplace=True)        
#     return df
