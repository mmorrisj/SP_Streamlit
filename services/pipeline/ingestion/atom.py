import os
import pandas as pd
from shared.utils.utils import Config, concatenate_files
from datetime import datetime
cfg = Config.from_yaml()

def clean_atom_output(df,fields,process_body,filter_fields,qry=None):
    try:
        df = df[df['Collection Name'] == cfg.atom_collection]
    except:
        pass
    df = df.dropna(subset=['Body'])
    cols = [col for col in df.columns if 'Unnamed' not in col]
    df = df[cols]
    df[cfg.text_field] = df['Body']
    if filter_fields:
        
        df = df[fields]
    
    if qry:
        df["Query"] = qry
    
    df.drop_duplicates('Title', inplace=True)
    df[cfg.text_field] = [text.replace('\n', ' ').strip() for text in df['BODY']]

    return df

def process_atom_files(directory= './backend/atom', 
                       output_directory = os.path.join(directory,'processed'),
                       delete=True,
                       fields=cfg.fields['raw_atom'],
                       process_body=True,
                       filter_fields=True):
    
    # Get the current date
    current_date = datetime.now().strftime("%Y-%m-%d")  # Format: YYYY-MM-DD
    
    for filename in os.listdir(directory):
        if filename.endswith('.csv'):
            file_path = os.path.join(directory, filename)
            # try:
                # Read the CSV file
            try:
                df = pd.read_csv(file_path, engine='python',on_bad_lines='skip', encoding="utf-8-sig")
            except:
                df = pd.read_csv(file_path, engine='python',on_bad_lines='skip', encoding="latin-1")
                df.rename(columns={'ï»¿Title': 'Title'}, inplace=True)
            # except:
            #     print(f'ERROR:{file_path}')
            #     continue
            # Clean the data
            cleaned_df = clean_atom_output(df,fields,process_body,filter_fields)
            
            # Export the cleaned data
            cleaned_file_path = os.path.join(output_directory, f'cleaned_{filename[:-4]}_{current_date}.xlsx')
            cleaned_df.to_excel(cleaned_file_path, index=False)
            if delete:
                #Delete the original file
                os.remove(file_path)

if __name__ == "__main__":
    process_atom_files()
