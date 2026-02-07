"""
Identify specific dates that have events with malformed source document IDs
"""

import json
import os
from pathlib import Path
from collections import defaultdict

def validate_source_doc_ids(doc_ids):
    """Check if source document IDs are valid UUIDs"""
    if not doc_ids:
        return False

    for doc_id in doc_ids:
        doc_id_str = str(doc_id)
        # Valid UUIDs are 36 characters with hyphens
        if len(doc_id_str) < 10 or '-' not in doc_id_str:
            return False

    return True

def main():
    events_dir = Path(__file__).parent.parent / "publications" / "events" / "China" / "daily"

    bad_dates = []
    date_stats = []

    print("Scanning daily event files for malformed source document IDs...\n")
    print("="*80)

    for file_path in sorted(events_dir.glob("2025-*_events.json")):
        date_str = file_path.stem.replace("_events", "")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading {file_path.name}: {e}")
            continue

        events = data.get('events', [])
        if not events:
            continue

        # Check each event
        total_events = len(events)
        bad_events = []

        for event in events:
            source_ids = event.get('source_doc_ids', [])
            if not validate_source_doc_ids(source_ids):
                bad_events.append({
                    'name': event.get('event_name', 'Unknown'),
                    'bad_ids': source_ids
                })

        if bad_events:
            bad_dates.append(date_str)
            date_stats.append({
                'date': date_str,
                'total_events': total_events,
                'bad_events': len(bad_events),
                'bad_event_names': [e['name'] for e in bad_events]
            })

    # Print summary
    print(f"\nFound {len(bad_dates)} dates with malformed source document IDs:")
    print("="*80)

    for stat in date_stats:
        print(f"\n{stat['date']}: {stat['bad_events']}/{stat['total_events']} events with bad IDs")
        for name in stat['bad_event_names']:
            print(f"  - {name[:70]}...")

    print("\n" + "="*80)
    print(f"\nSUMMARY:")
    print(f"  Bad dates: {len(bad_dates)}")
    print(f"  Total bad events: {sum(s['bad_events'] for s in date_stats)}")
    print(f"  Dates to regenerate: {', '.join(bad_dates)}")

    # Save to file for easy reference
    output_file = Path(__file__).parent / "bad_event_dates.txt"
    with open(output_file, 'w') as f:
        f.write('\n'.join(bad_dates))

    print(f"\nBad dates saved to: {output_file}")
    print("\nTo regenerate just these dates, run:")
    print(f"  python publications/scripts/extract_daily_events.py --country China --start-date <DATE> --end-date <DATE> --force")

    # Group dates into ranges for easier regeneration
    print("\nOR regenerate in batches:")
    if bad_dates:
        print(f"  python publications/scripts/extract_daily_events.py --country China --start-date {bad_dates[0]} --end-date {bad_dates[-1]} --force")
        print("  (Note: this will regenerate ALL dates in range, including good ones)")

if __name__ == "__main__":
    main()
