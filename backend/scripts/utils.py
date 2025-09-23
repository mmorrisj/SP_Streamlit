import yaml
import json
import os
from pathlib import Path
import yaml
# from openai import AzureOpenAI
# import ast
import json
# import boto3
# from botocore.exceptions import ClientError
# import re 
# import pandas as pd

class Config:
    def __init__(self, **entries):
        # Normalize any path fields
        for key, value in entries.items():
            if isinstance(value, str) and value.startswith('./'):
                entries[key] = str(Path(value).resolve())
        self.__dict__.update(entries)

    @classmethod
    def from_yaml(cls, yaml_path='./backend/config.yaml'):
        if yaml_path is None:
            yaml_path = Path(__file__).resolve().parent.parent / 'config.yaml'
        else:
            yaml_path = Path(yaml_path).resolve()

        with yaml_path.open('r') as file:
            config_data = yaml.safe_load(file) or {}
        return cls(**config_data)

    def __repr__(self):
        return f'Config({self.__dict__})'

cfg = Config.from_yaml()

# def get_secret():
 
#     secret_name = cfg.aws['secret_name']
#     region_name = cfg.aws['region_name']
 
#     # Create a Secrets Manager client
#     session = boto3.session.Session()
#     client = session.client(
#         service_name='secretsmanager',
#         region_name=region_name
#     )
 
#     try:
#         get_secret_value_response = client.get_secret_value(
#             SecretId=secret_name
#         )
#     except ClientError as e:
#         # For a list of exceptions thrown, see
#         # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
#         raise e
 
#     secret = get_secret_value_response['SecretString']
#     return secret
 
# def initialize_client():
#     secret_string = get_secret()

#     credentials = json.loads(secret_string)
#     client = AzureOpenAI(
#         azure_endpoint=credentials["endpoint"],
#         api_key=credentials["key"],
#         api_version=cfg.aws['api_version'],
#     )
#     return client

# def fetch_gai_content(response):
#     import ast
#     try:
#         # Attempt to evaluate the content of the response as a Python literal structure
#         gai_output = ast.literal_eval(response['choices'][0]['message']['content'])
#     except:
#         # If evaluation fails, find JSON objects within the content
#         gai_output = find_json_objects(response['choices'][0]['message']['content'])
#     return gai_output

# # 

# def gai(sys_prompt, user_prompt, model="gpt-4o"):
#     client = initialize_client()
#     # Create a chat completion using the specified model and prompts
#     completion = client.chat.completions.create(
#         model=model, 
#         messages=[
#             {
#                 "role": "system",
#                 "content": sys_prompt,
#             },
#             {
#                 "role": "user",
#                 "content": user_prompt,
#             },
#         ],
#     )
#     # Return the completion as a JSON object
#     return json.loads(completion.model_dump_json())


    
# def clean_json_string(text):
#     """
#     Cleans the input text to prepare it for JSON parsing.
#     - Removes Markdown code block delimiters.
#     - Replaces single quotes around values with double quotes.
#     - Handles escaped quotes and special characters.
#     """
#     # Remove Markdown code block delimiters
#     text = text.strip().strip('```json').strip().strip('```').strip()

#     # Replace single quotes around values with double quotes
#     text = re.sub(r':\s*\'([^\']*)\'', r': "\1"', text)

#     # Replace escaped single quotes within values
#     text = text.replace("\\'", "'")
#     text = text.replace('\\"', '"')

#     # Handle special characters and ensure proper JSON formatting
#     text = text.replace('\n', ' ').replace('\r', '')

#     return text

# def extract_jsons(text):
#     """
#     Attempts to extract JSON data from the input text.
#     """
#     cleaned_text = clean_json_string(text)
    
#     # Attempt to load the cleaned JSON string
#     try:
#         json_data = json.loads(cleaned_text)
#         return json_data
#     except json.JSONDecodeError:
#         return extract_json_regex(cleaned_text)

# def extract_json_ast(text):
#     """
#     Attempts to extract JSON data using the ast.literal_eval method.
#     """
#     cleaned_text = clean_json_string(text)

#     try:
#         json_data = ast.literal_eval(cleaned_text)
#         return json_data
#     except (ValueError, SyntaxError):
#         return None

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

# def migrate_softpower_entities_table(engine):
#     with engine.connect() as conn:
#         try:
#             print("Renaming old table...")
#             conn.execute(text("ALTER TABLE softpower_entities RENAME TO softpower_entities_old;"))

#             print("Creating new table with composite primary key...")
#             conn.execute(text("""
#                 CREATE TABLE softpower_entities (
#                     sp_id INTEGER NOT NULL,
#                     entity TEXT NOT NULL,
#                     PRIMARY KEY (sp_id, entity)
#                 );
#             """))

#             print("Copying data (de-duplicated)...")
#             conn.execute(text("""
#                 INSERT INTO softpower_entities (sp_id, entity)
#                 SELECT DISTINCT sp_id, entity FROM softpower_entities_old;
#             """))

#             print("Dropping old table...")
#             conn.execute(text("DROP TABLE softpower_entities_old;"))

#             print("✅ Migration complete: softpower_entities now uses (sp_id, entity) as primary key.")
#         except SQLAlchemyError as e:
#             print("❌ Migration failed:", e)
#             conn.rollback()

    
# def clean_json_string(text):
#     """
#     Cleans the input text to prepare it for JSON parsing.
#     - Removes Markdown code block delimiters.
#     - Replaces single quotes around values with double quotes.
#     - Handles escaped quotes and special characters.
#     """
#     # Remove Markdown code block delimiters
#     text = text.strip().strip('```json').strip().strip('```').strip()

#     # Replace single quotes around values with double quotes
#     text = re.sub(r':\s*\'([^\']*)\'', r': "\1"', text)

#     # Replace escaped single quotes within values
#     text = text.replace("\\'", "'")
#     text = text.replace('\\"', '"')

#     # Handle special characters and ensure proper JSON formatting
#     text = text.replace('\n', ' ').replace('\r', '')

#     return text

# def extract_jsons(text):
#     """
#     Attempts to extract JSON data from the input text.
#     """
#     cleaned_text = clean_json_string(text)
    
#     # Attempt to load the cleaned JSON string
#     try:
#         json_data = json.loads(cleaned_text)
#         return json_data
#     except json.JSONDecodeError:
#         return extract_json_regex(cleaned_text)

# def extract_json_ast(text):
#     """
#     Attempts to extract JSON data using the ast.literal_eval method.
#     """
#     cleaned_text = clean_json_string(text)

#     try:
#         json_data = ast.literal_eval(cleaned_text)
#         return json_data
#     except (ValueError, SyntaxError):
#         return None

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
