import os
import json

dirs = ['daily', 'weekly', 'monthly']
base_path = 'c:/Users/mmorr/Desktop/Apps/SP_Streamlit/publications/events/China'

for d in dirs:
    path = os.path.join(base_path, d)
    files = [f for f in os.listdir(path) if f.endswith('.json')]
    print(f'{d}: {len(files)} files')
    for f in sorted(files)[:10]:
        print(f'  {f}')

# Check the overall files
overall_files = [f for f in os.listdir(base_path) if 'overall' in f and f.endswith('.json')]
print(f'\nOverall files: {len(overall_files)}')
for f in sorted(overall_files):
    print(f'  {f}')
    # Get file size
    file_path = os.path.join(base_path, f)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f'    Size: {size_mb:.2f} MB')

    # Try to parse and get event count
    try:
        with open(file_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            if 'events' in data:
                print(f'    Events: {len(data["events"])}')
                print(f'    Period: {data.get("period", "N/A")}')
    except Exception as e:
        print(f'    Error: {e}')
