"""
Regenerate ONLY the dates that have events with malformed source document IDs
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from publications.scripts.extract_daily_events import process_date_range
from shared.utils.utils import Config

def main():
    # Read the bad dates file
    bad_dates_file = Path(__file__).parent / "bad_event_dates.txt"

    if not bad_dates_file.exists():
        print("Error: bad_event_dates.txt not found. Run find_bad_event_dates.py first.")
        sys.exit(1)

    with open(bad_dates_file, 'r') as f:
        bad_dates = [line.strip() for line in f if line.strip()]

    print("="*80)
    print(f"REGENERATING {len(bad_dates)} DATES WITH BAD SOURCE DOCUMENT IDs")
    print("="*80)
    print(f"\nDates to regenerate:")
    for date in bad_dates:
        print(f"  - {date}")

    print("\n" + "="*80)
    confirm = input(f"\nProceed with regeneration of {len(bad_dates)} dates? (yes/no): ")

    if confirm.lower() not in ['yes', 'y']:
        print("Cancelled.")
        sys.exit(0)

    # Load config once
    config_path = project_root / 'shared' / 'config' / 'config.yaml'
    config = Config.from_yaml(config_path)

    # Regenerate each date
    successful = 0
    failed = []

    for i, date in enumerate(bad_dates, 1):
        print(f"\n{'='*80}")
        print(f"[{i}/{len(bad_dates)}] Regenerating {date}...")
        print(f"{'='*80}")

        try:
            # Convert date string to datetime
            date_obj = datetime.strptime(date, "%Y-%m-%d")

            # Call process_date_range directly
            process_date_range(
                country="China",
                start_date=date_obj,
                end_date=date_obj,
                publications_dir="publications",
                output_dir="publications/events",
                config=config,
                force=True
            )

            successful += 1
            print(f"✓ Successfully regenerated {date}")
        except Exception as e:
            print(f"✗ Failed to regenerate {date}")
            print(f"Error: {str(e)}")
            failed.append(date)

    # Summary
    print("\n" + "="*80)
    print("REGENERATION COMPLETE")
    print("="*80)
    print(f"Successful: {successful}/{len(bad_dates)}")

    if failed:
        print(f"Failed: {len(failed)}")
        print("Failed dates:")
        for date in failed:
            print(f"  - {date}")
    else:
        print("All dates regenerated successfully!")

    print("\nYou can now run the summary publication script:")
    print("  python summary_template/generate_summary_publication.py")

if __name__ == "__main__":
    main()
