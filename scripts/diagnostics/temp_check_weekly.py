import json
import os

path = 'c:/Users/mmorr/Desktop/Apps/SP_Streamlit/publications/events/China/weekly'
files = [f for f in os.listdir(path) if f.endswith('.json')]

total_events = 0
bad_id_events = 0

for f in files:
    data = json.load(open(os.path.join(path, f), encoding='utf-8'))
    for e in data.get('events', []):
        total_events += 1
        ids = e.get('source_doc_ids', [])
        if any(len(str(id)) < 10 for id in ids):
            bad_id_events += 1

print(f'Weekly events total: {total_events}')
print(f'Events with bad IDs: {bad_id_events}')
if total_events > 0:
    print(f'Percentage good: {100*(total_events-bad_id_events)/total_events:.1f}%')
