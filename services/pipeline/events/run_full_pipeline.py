"""
Complete event summary and publication pipeline orchestrator.

This script runs the full pipeline:
1. Generate EventSummary records from documents
2. Generate publication documents (Reviewer and Summary versions)

Usage:
    python services/pipeline/events/run_full_pipeline.py --start 2024-10-01 --end 2024-10-31 --country China
    python services/pipeline/events/run_full_pipeline.py --start 2024-10-01 --end 2024-10-31  # All countries
"""

import argparse
import sys
import subprocess
from datetime import datetime, date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.config.config import Config


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def run_command(cmd: list, description: str) -> bool:
    """
    Run a command and return success status.

    Args:
        cmd: Command list for subprocess
        description: Human-readable description

    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*80}")
    print(f"RUNNING: {description}")
    print(f"{'='*80}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*80}\n")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=False,
            text=True
        )
        print(f"\n✅ {description} - COMPLETED SUCCESSFULLY\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} - FAILED")
        print(f"Error code: {e.returncode}\n")
        return False
    except Exception as e:
        print(f"\n❌ {description} - ERROR: {e}\n")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run complete event summary and publication pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Required arguments
    parser.add_argument(
        '--start',
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end',
        required=True,
        help='End date (YYYY-MM-DD)'
    )

    # Optional arguments
    parser.add_argument(
        '--country',
        help='Specific country to process (optional, processes all if not specified)'
    )
    parser.add_argument(
        '--categories',
        default='Economic,Diplomacy,Social,Military',
        help='Categories for publication (default: Economic,Diplomacy,Social,Military)'
    )
    parser.add_argument(
        '--recipients',
        help='Recipient countries to filter (comma-separated, optional)'
    )
    parser.add_argument(
        '--period-type',
        default='monthly',
        choices=['daily', 'weekly', 'monthly', 'yearly'],
        help='Period type (default: monthly)'
    )
    parser.add_argument(
        '--min-docs',
        type=int,
        default=2,
        help='Minimum documents per event (default: 2)'
    )
    parser.add_argument(
        '--model',
        default='gpt-4',
        help='GPT model for AI generation (default: gpt-4)'
    )
    parser.add_argument(
        '--max-sources',
        type=int,
        default=10,
        help='Maximum sources per publication section (default: 10)'
    )
    parser.add_argument(
        '--skip-summary',
        action='store_true',
        help='Skip EventSummary generation (use existing)'
    )
    parser.add_argument(
        '--skip-publication',
        action='store_true',
        help='Skip publication generation'
    )

    args = parser.parse_args()

    # Parse and validate dates
    try:
        start_date = parse_date(args.start)
        end_date = parse_date(args.end)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if start_date > end_date:
        print("Error: Start date must be before or equal to end date")
        sys.exit(1)

    # Load config
    try:
        config = Config.from_yaml()
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)

    # Determine countries
    if args.country:
        if args.country not in config.influencers:
            print(f"Error: Country '{args.country}' not in config")
            print(f"Available: {', '.join(config.influencers)}")
            sys.exit(1)
        countries = [args.country]
    else:
        countries = config.influencers

    # Print pipeline configuration
    print("\n" + "="*80)
    print("EVENT SUMMARY & PUBLICATION PIPELINE")
    print("="*80)
    print(f"Date Range:        {args.start} to {args.end}")
    print(f"Countries:         {', '.join(countries)}")
    print(f"Period Type:       {args.period_type}")
    print(f"Categories:        {args.categories}")
    if args.recipients:
        print(f"Recipients:        {args.recipients}")
    print(f"Model:             {args.model}")
    print(f"Min Docs/Event:    {args.min_docs}")
    print(f"Max Sources:       {args.max_sources}")
    print(f"\nPipeline Steps:")
    print(f"  1. EventSummary Generation:  {'SKIP' if args.skip_summary else 'RUN'}")
    print(f"  2. Publication Generation:   {'SKIP' if args.skip_publication else 'RUN'}")
    print("="*80 + "\n")

    # Confirm with user
    response = input("Proceed with pipeline? [y/N]: ")
    if response.lower() not in ['y', 'yes']:
        print("Aborted by user")
        sys.exit(0)

    success_count = 0
    total_steps = len(countries) * (2 if not (args.skip_summary or args.skip_publication) else 1)
    current_step = 0

    # Process each country
    for country in countries:
        print(f"\n{'#'*80}")
        print(f"# PROCESSING COUNTRY: {country}")
        print(f"{'#'*80}\n")

        # Step 1: Generate EventSummary records
        if not args.skip_summary:
            current_step += 1
            print(f"\n[STEP {current_step}/{total_steps}] Generating EventSummary records for {country}")

            cmd = [
                sys.executable,
                'services/pipeline/events/generate_event_summaries.py',
                '--start', args.start,
                '--end', args.end,
                '--country', country,
                '--period-type', args.period_type,
                '--min-docs', str(args.min_docs)
            ]

            success = run_command(
                cmd,
                f"EventSummary Generation - {country}"
            )

            if success:
                success_count += 1
            else:
                print(f"⚠️  EventSummary generation failed for {country}")
                print("Continuing to next country...\n")
                continue

        # Step 2: Generate publications
        if not args.skip_publication:
            current_step += 1
            print(f"\n[STEP {current_step}/{total_steps}] Generating publications for {country}")

            cmd = [
                sys.executable,
                'services/publication/generate_publication.py',
                '--country', country,
                '--start', args.start,
                '--end', args.end,
                '--categories', args.categories,
                '--period-type', args.period_type,
                '--model', args.model,
                '--max-sources', str(args.max_sources)
            ]

            if args.recipients:
                cmd.extend(['--recipients', args.recipients])

            success = run_command(
                cmd,
                f"Publication Generation - {country}"
            )

            if success:
                success_count += 1
            else:
                print(f"⚠️  Publication generation failed for {country}\n")

    # Final summary
    print("\n" + "="*80)
    print("PIPELINE SUMMARY")
    print("="*80)
    print(f"Countries Processed:   {len(countries)}")
    print(f"Total Steps:           {total_steps}")
    print(f"Successful Steps:      {success_count}")
    print(f"Failed Steps:          {total_steps - success_count}")

    if success_count == total_steps:
        print(f"\n✅ ALL STEPS COMPLETED SUCCESSFULLY")
        print("\nGenerated files can be found in:")
        print("  - services/publication/output/")
    elif success_count > 0:
        print(f"\n⚠️  PARTIALLY COMPLETED ({success_count}/{total_steps} steps)")
    else:
        print(f"\n❌ PIPELINE FAILED")
        sys.exit(1)

    print("="*80 + "\n")


if __name__ == "__main__":
    main()
