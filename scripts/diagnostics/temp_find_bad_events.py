import json
from pathlib import Path

daily_dir = Path("publications/events/China/daily")

bad_events = []

for json_file in sorted(daily_dir.glob("2025-*_events.json")):
    with open(json_file, encoding='utf-8') as f:
        data = json.load(f)

    for event in data.get('events', []):
        source_ids = event.get('source_doc_ids', [])

        # Check if any source ID is suspiciously short (not a UUID)
        has_short_ids = any(len(str(id)) <= 3 for id in source_ids)

        if has_short_ids:
            bad_events.append({
                'file': json_file.name,
                'event_name': event['event_name'],
                'source_ids': source_ids,
                'url': event.get('atom_search_url', 'NO URL')[:100]
            })

print(f"Found {len(bad_events)} events with malformed source_doc_ids:\n")

for i, event in enumerate(bad_events[:10]):
    print(f"{i+1}. File: {event['file']}")
    print(f"   Event: {event['event_name']}")
    print(f"   Bad IDs: {event['source_ids']}")
    print()

print(f"\n(Showing first 10 of {len(bad_events)} total)")
