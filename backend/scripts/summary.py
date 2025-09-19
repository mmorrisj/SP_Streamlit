import pandas as pd
import nltk
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from nltk.tokenize import sent_tokenize
import sqlite3
import re
import json
import os
import boto3

cfg = Config.from_yaml()
current_date = datetime.now()
date_string = current_date.strftime("%Y-%m-%d")
# Initialize database connection
conn = sqlite3.connect(cfg.db_path)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA journal_mode = WAL;')
cursor = conn.cursor()

def insert_summary(country, category, start_date, end_date, event_list,recipient=None):
    # Iterate over each event in the event list
    for event in event_list:
        key_event = event['key_event']
        overview = event['overview']
        outcome = event['outcomes']
        # Load the SQL command template for inserting a summary
        if recipient:
            sql_command = load_sql('insert_recipient_summary')
            # Prepare data tuple for insertion
            data = (country,recipient, category, start_date, end_date, key_event, overview, outcome)
        else:
            sql_command = load_sql('insert_summary')
            # Prepare data tuple for insertion
            data = (country, category, start_date, end_date, key_event, overview, outcome)
        # Execute the SQL command with the provided data
        cursor.execute(sql_command, data)
    # Commit the transaction to the database
    conn.commit()

def file_name(country,start_date,end_date,category,recipient):
    filename = ''
    if country:
        filename += f'{country}_'
    if recipient:
        filename += f'{recipient}_'
    filename += f'{start_date}_{end_date}_'
    if category:
        filename += f'{category}'
    return filename

def parse_summary(summary, country, start_date, end_date, category=None, recipient=None):
    topic_summary = {}
    # Create a unique identifier for the summary
    if recipient:
        rng = 6
        category = summary[3]
        event_name = summary[6]
        summ = summary[7]
        outcome = summary[8]
    else:
        rng = 5
        category = summary[2]
        event_name = summary[5]
        summ = summary[6]
        outcome = summary[7]
    identifiers = '-'.join([str(summary[i]) for i in range(rng)])
    id_ = summary[0]
    
    
    # Tokenize the summary and outcome into sentences
    sum_sentences = sent_tokenize(summ)
    out_sentences = sent_tokenize(outcome)
    sent_num = 1
    # Populate the topic summary dictionary with relevant information
    topic_summary['id'] = id_
    topic_summary['summary'] = summ
    topic_summary['event_name'] = event_name
    topic_summary['outcome'] = outcome
    topic_summary['country'] = country
    if recipient:
        topic_summary['recipient'] = recipient
    topic_summary['start_date'] = start_date
    topic_summary['end_date'] = end_date
    topic_summary['category'] = category
    topic_summary['sentences'] = []
    # Add sentences from the summary to the topic summary
    for sent in sum_sentences:
        sentence = {}
        if len(sent) > 0:
            sent_id = f"{identifiers}-summary-{sent_num}"
            sentence[sent_id] = {}
            sentence[sent_id]['text'] = sent
            topic_summary['sentences'].append(sentence)
            sent_num += 1
    sent_num = 1
    # Add sentences from the outcome to the topic summary
    for sent in out_sentences:
        sentence = {}
        if len(sent) > 0:
            sent_id = f"{identifiers}-outcome-{sent_num}"
            sentence[sent_id] = {}
            sentence[sent_id]['text'] = sent
            topic_summary['sentences'].append(sentence)
            sent_num += 1
    return topic_summary

def build_parsed_summaries(summaries, country, start_date, end_date, category=None,recipient=None):
    topic_summaries = []
    # Parse each summary and add to the list of topic summaries
    for summary in summaries:
        topic_summary = parse_summary(summary, country, start_date, end_date, category=category, recipient=recipient)
        topic_summaries.append(topic_summary)
    return topic_summaries

def source_summaries(summaries, records):
    source_outputs = []
    # Source sentences for each summary
    for summary in summaries:
        sentences = summary['sentences']
        summ = summary['summary']
        for sentence in sentences:
            source_output = source_sentence(records, summary, sentence)
            source_outputs.append(source_output)
    return source_outputs

def source_sentence(records, summary, sentence):
    # Source each sentence and fetch its content
    for k, v in sentence.items():
        _id = k
        text = v['text']
        sys_prompt = source_sys_prompt.format(sentence_id=_id)
        user_prompt = source_user_prompt.format(sentence_id=_id, sentence=text, summary=summary, reports=records)
        source_response = gai(sys_prompt=sys_prompt, user_prompt=user_prompt)
        source_output = fetch_gai_content(source_response)
    return source_output

def convert_list(x):
    # Return the first element if x is a list, otherwise return x
    if isinstance(x, list):
        return x[0]
    else:
        return x

def flatten_dict(x):
    new_dict = {}
    # Flatten the list of dictionaries into a single dictionary
    for item in x:
        try:
            new_dict[item['sentence_id']] = item['sources']
        except:
            continue
    return new_dict

def fetch_citation(atom_id):
    # Fetch citation from the database using the atom_id
    sql_command = load_sql('fetch_citation')
    data = (atom_id,)
    return cursor.execute(sql_command, data).fetchone()[0]

def parse_sources(summaries, sources):
    summary_output = []
    # Parse sources for each summary and update the summary output
    for summary in summaries:
        sentences = summary['sentences']
        update = summary
        summ = summary['summary']
        new_sentences = []
        for sentence in sentences:
            x = parse_sentence(sentence, sources)
            new_sentences.append(x)
        update['sentences'] = new_sentences
        summary_output.append(update)
    return summary_output

def parse_sentence(sentence, sources):
    # Parse each sentence and add source information
    for k, v in sentence.items():
        x = {}
        x[k] = v
        source_list = sources[k]
        x[k]['atom_ids'] = source_list
        # link = build_hyperlink(source_list)
        # x[k]['atom_url'] = link
        # try:
        #     citations = list(map(fetch_citation, source_list))
        # except:
        # #     citations = []
        # x[k]['citations'] = citations
        return x

def consolidate_sources(country,start_date,end_date,recipient=None):
    filename = file_name(country,start_date,end_date,recipient=recipient,category=None)
    source_outputs = []
    source_dict = {}
    consolidated_summaries = {}
    directory = cfg.gai_json
    for file in os.listdir(directory):
        if f'{filename}' in file:
            full_path = os.path.join(directory, file)
            with open(full_path, 'r') as f:
                try:
                    sources = json.load(f)
                    if isinstance(sources, list):
                        source_outputs.append(sources)
                    else:
                        print(f"Unexpected format in {file}: {type(sources)}")
                except json.JSONDecodeError as e:
                    print(f"Skipping {file}: invalid JSON ({e})")
    source_num = 1
    for output in source_outputs:
        for item in output:
            if not isinstance(item, dict):
                print(f"Skipping non-dict item: {item}")
                continue
            id_ = item['id']
            sentences = item['sentences']
            summary_hyperlink_atoms = []
            outcome_hyperlink_atoms = []
            summary_citations = []
            outcome_citations = []
            for sentence in sentences:
                for k,v in sentence.items():
                    sentence_id = k
                    atoms = sentence[k]['atom_ids']
                    for atom in atoms:
                        if atom not in source_dict.keys():
                            source_dict[atom] = {}
                            source_dict[atom]['summary_ids'] = []
                            
                            source_dict[atom]['source_number'] = source_num
                            source_num += 1
                        source_dict[atom]['summary_ids'].append(id_)
                        source_dict[atom]['summary_ids'] = list(set(source_dict[atom]['summary_ids']))
                        try:
                            citation = fetch_citation(atom)
                        except:
                            citation = atom

                        if 'summary' in sentence_id:
                            summary_hyperlink_atoms.append(atom)
                            summary_citations.append(citation)
                        else:
                            outcome_hyperlink_atoms.append(atom)
                            outcome_citations.append(citation)
            summary_hyperlink_atoms = list(set(summary_hyperlink_atoms))
            outcome_hyperlink_atoms = list(set(outcome_hyperlink_atoms))
            summary_citations = list(set(summary_citations))
            outcome_citations = list(set(outcome_citations))

            consolidated_summaries[id_] = {}
            consolidated_summaries[id_]['event_name'] = item['event_name']
            consolidated_summaries[id_]['summary'] = item['summary']
            consolidated_summaries[id_]['outcome'] = item['outcome']
            consolidated_summaries[id_]['summary_hyperlink'] = build_hyperlink(summary_hyperlink_atoms)
            consolidated_summaries[id_]['output_hyoerlink'] = build_hyperlink(outcome_hyperlink_atoms)
            consolidated_summaries[id_]['summary_citations'] = summary_citations
            consolidated_summaries[id_]['outcome_citations'] = outcome_citations
            consolidated_summaries[id_]['category'] = item['category']
            consolidated_summaries[id_]['country'] = item['country']
            if recipient:
                consolidated_summaries[id_]['recipient'] = item['recipient']
            consolidated_summaries[id_]['start_date'] = item['start_date']
            consolidated_summaries[id_]['end_date'] = item['end_date']
            
    with open(os.path.join(directory,f"{filename}summaries.json"),'w') as f:
        json.dump(consolidated_summaries,f,indent=4)
    with open(os.path.join(directory,f"{filename}sources.json"),'w') as f:
        json.dump(source_dict,f,indent=4)

def event_summaries_outcomes(country,start_date,end_date,recipient=None):
    filename = file_name(country,start_date,end_date,category=None,recipient=recipient)
    directory = cfg.gai_json
    summaries = json.load(open(os.path.join(directory,f"{filename}summaries.json")))
    ids = list(summaries.keys())
    events = {}
    for category in cfg.categories:
        events[category] = []
        for id_ in ids:
            x = summaries[id_]
            if x['category'] == category:
                event = {}
                event['id'] = id_
                event['event_name'] = x['event_name']
                event['content'] = x['summary'] + x['outcome']
                events[category].append(event)
    return events

def process_output(output):
    if isinstance(output,dict):
        return output
    if isinstance(output,list):
        return output[0]

def deduplicate_events(country,start_date,end_date,category=None,recipient=None):
    filename = file_name(country,start_date,end_date,category=category,recipient=recipient)
    directory = cfg.gai_json
    summaries = json.load(open(os.path.join(directory,f"{filename}summaries.json")))
    events = event_summaries_outcomes(country,start_date,end_date,recipient=recipient)
    consolidation_response = gai(consolidation_prompt,str(events))
    c_response = fetch_gai_content(consolidation_response)
    result = process_output(c_response)
    with open(os.path.join(directory,f"{filename}deduplication.json"),'w') as f:
        json.dump(result,f,indent=4)
    mapping = {}
    ids = []
    for k,v in result.items():
        mapping[k] = []
        for id_ in v:
            mapping[k].append(summaries[id_]['event_name'])
            ids.append(id_)
    mapping['unlisted'] = [summaries[id_]['event_name'] for id_ in list(summaries.keys()) if id_ not in ids]
    with open(os.path.join(directory,f"{filename}mapping.json"),'w') as f:
        json.dump(mapping,f,indent=4)

def ose_summary(country,start_date,end_date,category,recipient=None):
    #collect records
    rpt = SoftPowerReports(conn,
                       country=country,
                       rec_country=recipient,
                       start_date=start_date,
                       end_date=end_date,
                       category=category)
    
    filename = file_name(country,start_date,end_date,category,recipient)
    directory = cfg.gai_json
    records = rpt.fetch_records()
    # save records to json and xlsx for review
    pd.DataFrame(records).to_excel(f'./gai_summary/data/{filename}.xlsx')
    #build prompts
    metrics = SoftPowerMetrics(conn)
    if recipient:
        records = 'NEWS MEDIA REPORTING:' + str(records) + '\n\n' +  metrics.recipient_metrics(country,recipient,start_date,end_date) 
    else:
        records = 'NEWS MEDIA REPORTING:' + str(records) + '\n\n' + metrics.metrics_prompt_string(country=country,start_date=start_date,end_date=end_date)

    # save data and prompts
    with open(f'{directory}/{filename}_report_text.json','w') as f:
        json.dump(records,f)
    with open(f'{directory}/{filename}_metrics_text.json','w') as f:
        json.dump(metrics.metrics_prompt_string(country=country,start_date=start_date,end_date=end_date),f)
    if recipient:
        sys_prompt = gai_recipient_summary.format(country=country,recipient=recipient,current_date=date_string,category=category,start_date=start_date,end_date=end_date,top_n=10)
    
    else:
        sys_prompt = gai_summary.format(country=country,date_string=date_string,category=category,start_date=start_date,end_date=end_date,top_n=10)
    user_prompt = records
    
    #GAI summary run
    response = gai(sys_prompt=sys_prompt,user_prompt=user_prompt)
    gai_output = fetch_gai_content(response) 

    #insert gai_output into db
    if recipient:
        insert_summary(country,category,start_date,end_date,gai_output,recipient=recipient)
    else:
        insert_summary(country,category,start_date,end_date,gai_output)
    print(f'summary inserted for {filename}')

def ose_sources(country,start_date,end_date,category,recipient=None):
    
    filename = file_name(country,start_date,end_date,category,recipient)
    directory = cfg.gai_json
    records = json.load(open(f'{directory}/{filename}report_text.json'))
    #retrieve summary for country, start date, end date, and category
    
    if recipient:
        query = 'SELECT * from recipient_summary WHERE country = ? AND recipient= ? AND start_date = ? AND category = ? AND end_date = ?'
        data = (country,recipient,start_date,category,end_date)
    else:
        query = 'SELECT * from summary WHERE country = ? AND start_date = ? AND category = ? AND end_date = ?'
        data = (country,start_date,category,end_date)
    summaries = cursor.execute(query,data).fetchall()
    
    #parse sentences for sourcing alignment
    parsed_summaries = build_parsed_summaries(summaries,country,start_date,end_date,category,recipient=recipient)

    #Generate source alignments
    summary_sources = source_summaries(parsed_summaries,records)

    #normalize and flatten gai output
    summary_sources = list(map(convert_list,summary_sources)) 

    sources = flatten_dict(summary_sources)

    summary_output = parse_sources(parsed_summaries,sources)
    with open(f'{directory}/{filename}.json','w') as f:
        json.dump(summary_output,f,indent=4)
    print(f'{filename} sources saved.')
    # return summary_output

def country_summary(country,start_date,end_date,recipient=None):
    for category in cfg.categories:
        filename = file_name(country=country,start_date=start_date,end_date=end_date,category=category,recipient=recipient)
        if recipient:
            print(f'running overall summary for {country}-{recipient}-{category}')
            ose_summary(country=country,start_date=start_date,end_date=end_date,category=category,recipient=recipient)
            print(f'pulling sources for {filename} summaries')
            ose_sources(country=country,recipient=recipient,start_date=start_date,end_date=end_date,category=category)
        else:
            print(f'running overall summary for {country}-{category}')
            ose_summary(country=country,start_date=start_date,end_date=end_date,category=category)
            print(f'pulling sources for {country}-{category} summaries')
            ose_sources(country=country,start_date=start_date,end_date=end_date,category=category)
    print(f'consolidating summaries and sources.')
    
    if recipient:
        consolidate_sources(country=country,recipient=recipient,start_date=start_date,end_date=end_date)   
    else:
        consolidate_sources(country=country,start_date=start_date,end_date=end_date)  

def recipient_summary(country,recipient,start_date,end_date):
    for category in cfg.categories:
        query = 'SELECT * from recipient_summary WHERE country = ? AND recipient= ? AND start_date = ? AND category = ?AND end_date = ?'
        data = (country,recipient,start_date,category,end_date)
        filename = file_name(country,start_date,end_date,category,recipient)
        records = json.load(open(f'./gai_summary/data/{filename}_report_text.json'))
        summaries = cursor.execute(query,data).fetchall()
        parsed_summaries = build_parsed_summaries(summaries,country,start_date,end_date,category,recipient=recipient)
        summary_sources = source_summaries(parsed_summaries,records)
        summary_sources = list(map(convert_list,summary_sources)) 
        sources = flatten_dict(summary_sources) 
        summary_output = parse_sources(parsed_summaries,sources)
        with open(f'./gai_summary/json/{filename}.json','w') as f:
            json.dump(summary_output,f,indent=4)
        print(f'{filename} sources saved.')
    consolidate_sources(country=country,start_date=start_date,end_date=end_date,recipient=recipient)  

def fetch_summaries(country, category=None, recipient=None):
    name = country
    query = 'SELECT start_date, end_date FROM {} WHERE country=?'
    data = [country]
    table = 'summary'

    if category:
        query += ' AND category=?'
        data.append(category)
        name += f'_{category}'

    if recipient:
        table = 'recipient_summary'
        query += ' AND recipient=?'
        data.append(recipient)
        name += f'_{recipient}'

    query = query.format(table)
    data = tuple(data)

    summs = cursor.execute(query, data).fetchall()

    seen = set()
    unique_results = []

    for row in summs:
        key = (country, row["start_date"], row["end_date"])
        if key not in seen:
            seen.add(key)
            unique_results.append({
                "country": country,
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "label": f"{name} coverage: {row['start_date']} - {row['end_date']}"
            })

    return unique_results