import yaml
import json
import os
import re
import time
from pathlib import Path
import ast
from openai import AzureOpenAI
import boto3
from botocore.exceptions import ClientError
# import pandas as pd
from functools import wraps
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

class Config:
    def __init__(self, **entries):
        # Normalize any path fields
        for key, value in entries.items():
            if isinstance(value, str) and value.startswith('./'):
                entries[key] = str(Path(value).resolve())
        self.__dict__.update(entries)

    @classmethod
    def from_yaml(cls, yaml_path=None):
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

def get_db_secret(secret_name):
    """
    Fetches a specific secret from AWS Secrets Manager by name.

    Args:
        secret_name: Name of the secret to fetch

    Returns:
        dict: Parsed JSON secret
    """
    region_name = cfg.aws.get('region_name', 'us-east-1')

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise e

    secret = get_secret_value_response['SecretString']
    return json.loads(secret)

def initialize_client(use_env_vars=False):
    """
    Initialize Azure OpenAI client.

    Args:
        use_env_vars: If True, use environment variables (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY).
                     If False (default), use AWS Secrets Manager via boto3.

    Returns:
        AzureOpenAI client
    """
    if use_env_vars:
        # Environment variables mode
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')

        if not azure_endpoint or not api_key:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set in environment variables "
                "when use_env_vars=True"
            )

        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
        )
    else:
        # AWS Secrets Manager mode (default)
        secret_string = get_secret()
        credentials = json.loads(secret_string)

        client = AzureOpenAI(
            azure_endpoint=credentials["endpoint"],
            api_key=credentials["key"],
            api_version=cfg.aws.get('api_version', '2024-02-15-preview'),
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
    user_prompt = str(prompt)


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
        temperature=0.3,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        model=deployment
    )
    return response.choices[0].message.content


@rate_limit(min_interval=10.0)
def gai(sys_prompt, user_prompt, model="gpt-4o-mini", source="proxy", use_proxy=None, azure_use_env=False):
    """
    Unified LLM call supporting multiple backends.

    Args:
        sys_prompt: System prompt for the LLM
        user_prompt: User prompt for the LLM
        model: Model to use (default: gpt-4o-mini)
        source: Backend source - "proxy" (default), "litellm", "azure", or "openai"
        use_proxy: [DEPRECATED] Use source="proxy" instead. Maintained for backward compatibility.
        azure_use_env: If True with source="azure", use env vars instead of AWS Secrets Manager

    Environment Variables:
        API_URL: Required for source="proxy" (base URL, e.g. http://localhost:5001)
        LITELLM_URL, LITELLM_API_KEY: Required for source="litellm"
        LITELLM_MODEL: Optional model override for LITELLM (if not set, uses 'model' parameter)
        AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY: Required for source="azure" with azure_use_env=True
        OPENAI_PROJ_API: Required for source="openai"

    Returns:
        LLM response (parsed as JSON if possible, otherwise raw string)

    Raises:
        ValueError: If required configuration is missing
        requests.RequestException: If FastAPI proxy call fails
    """
    import requests

    # Handle backward compatibility with use_proxy parameter
    if use_proxy is not None:
        source = "proxy" if use_proxy else "openai"

    # AZURE OpenAI (System 2 default)
    if source == "azure":
        print(f"  [AZURE] Calling Azure OpenAI (credentials from {'env vars' if azure_use_env else 'AWS Secrets Manager'})")

        try:
            # Initialize Azure client
            client = initialize_client(use_env_vars=azure_use_env)

            # Get deployment name
            if azure_use_env:
                deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', model)
            else:
                # Try to get deployment name from AWS Secrets Manager
                try:
                    secret_dict = get_db_secret('azure-open-ai-credentials')
                    deployment = (
                        secret_dict.get('deployment_name') or
                        secret_dict.get('GPT_4_1_DEPLOYMENT_NAME') or
                        model
                    )
                except Exception:
                    # Fallback to model name if secret doesn't have deployment name
                    deployment = model

            # Make Azure OpenAI call
            completion = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )

            content = completion.choices[0].message.content

            # Parse response
            if isinstance(content, (dict, list)):
                return content

            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON from markdown-wrapped response
                    match = re.search(r'(\[.*\]|\{.*\})', content, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(1))
                        except json.JSONDecodeError:
                            pass
                    return content

            return content

        except Exception as e:
            error_msg = f"Azure OpenAI call failed: {e}"
            print(f"ERROR: {error_msg}")
            raise RuntimeError(error_msg) from e

    # LITELLM Proxy
    elif source == "litellm":
        print("  [LITELLM] Calling LiteLLM API")

        try:
            from openai import OpenAI

            litellm_url = os.getenv('LITELLM_URL')
            litellm_key = os.getenv('LITELLM_API_KEY')
            litellm_model = os.getenv('LITELLM_MODEL', model)  # Use LITELLM_MODEL if set, otherwise use passed model

            if not litellm_url or not litellm_key:
                raise ValueError("LITELLM_URL and LITELLM_API_KEY must be set in environment")

            print(f"  [LITELLM] Using model: {litellm_model}")

            client = OpenAI(
                api_key=litellm_key,
                base_url=litellm_url,
            )

            completion = client.chat.completions.create(
                model=litellm_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            content = completion.choices[0].message.content

            if isinstance(content, (dict, list)):
                return content

            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content

            return content

        except Exception as e:
            print(f"ERROR: LiteLLM call failed: {e}")
            raise

    # OPENAI Direct API
    elif source == "openai":
        print("  [OPENAI] Calling OpenAI API directly")

        try:
            from openai import OpenAI

            api_key = os.getenv('OPENAI_PROJ_API')
            if not api_key:
                raise ValueError("OPENAI_PROJ_API not found in environment")

            client = OpenAI(api_key=api_key)

            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = completion.choices[0].message.content

            if isinstance(content, (dict, list)):
                return content

            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content

            return content

        except Exception as e:
            print(f"ERROR: Direct OpenAI call failed: {e}")
            raise

    # PROXY (System 1, FastAPI → OpenAI)
    elif source == "proxy":
        api_url = os.getenv('API_URL', '').strip()
        if not api_url:
            # Backward compat: try FASTAPI_URL and extract base
            fastapi_url = os.getenv('FASTAPI_URL', '').strip()
            if fastapi_url:
                api_url = fastapi_url.split('/proxy_query')[0].split('/material_query')[0]
            else:
                raise ValueError(
                    "API_URL environment variable must be set for proxy mode. "
                    "Example: API_URL=http://127.0.0.1:5001"
                )
        fastapi_url = f"{api_url.rstrip('/')}/proxy_query"

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
            resp_content = data.get("response") if isinstance(data, dict) and "response" in data else data

            if isinstance(resp_content, str):
                try:
                    return json.loads(resp_content)
                except json.JSONDecodeError:
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

    else:
        raise ValueError(f"Invalid source: {source}. Must be 'azure', 'litellm', 'openai', or 'proxy'")


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


