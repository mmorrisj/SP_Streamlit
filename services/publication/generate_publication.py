"""
CLI script for generating publication reports.

Usage:
    python services/publication/generate_publication.py --country China --start 2024-10-01 --end 2024-10-31

Options:
    --country: Initiating country (required)
    --start: Start date YYYY-MM-DD (required)
    --end: End date YYYY-MM-DD (required)
    --categories: Comma-separated categories (default: Economic,Diplomacy,Social,Military)
    --recipients: Comma-separated recipient countries (optional)
    --period-type: Period type - daily, weekly, monthly, yearly (default: monthly)
    --model: GPT model to use (default: gpt-4)
    --template: Path to template file (default: services/publication/templates/GAI_Summary_Template.docx)
    --output: Output directory (default: services/publication/output)
    --max-sources: Maximum sources per section (default: 10)
    --no-consolidation: Skip event consolidation step
"""

import argparse
import sys
import os
from datetime import datetime, date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.models.models import PeriodType
from shared.config.config import Config
from services.publication.publication_service import PublicationService


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def parse_period_type(period_str: str) -> PeriodType:
    """Parse period type string."""
    period_map = {
        'daily': PeriodType.DAILY,
        'weekly': PeriodType.WEEKLY,
        'monthly': PeriodType.MONTHLY,
        'yearly': PeriodType.YEARLY
    }
    period_str_lower = period_str.lower()
    if period_str_lower not in period_map:
        raise ValueError(f"Invalid period type: {period_str}. Use daily, weekly, monthly, or yearly")
    return period_map[period_str_lower]


def main():
    parser = argparse.ArgumentParser(
        description="Generate publication reports from event summaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Required arguments
    parser.add_argument(
        '--country',
        required=True,
        help='Initiating country (e.g., China, Russia, India)'
    )
    parser.add_argument(
        '--start',
        required=True,
        help='Start date in YYYY-MM-DD format'
    )
    parser.add_argument(
        '--end',
        required=True,
        help='End date in YYYY-MM-DD format'
    )

    # Optional arguments
    parser.add_argument(
        '--categories',
        default='Economic,Diplomacy,Social,Military',
        help='Comma-separated list of categories (default: Economic,Diplomacy,Social,Military)'
    )
    parser.add_argument(
        '--recipients',
        help='Comma-separated list of recipient countries to filter (optional)'
    )
    parser.add_argument(
        '--period-type',
        default='monthly',
        choices=['daily', 'weekly', 'monthly', 'yearly'],
        help='Period aggregation type (default: monthly)'
    )
    parser.add_argument(
        '--model',
        default='gpt-4',
        help='GPT model for AI generation (default: gpt-4)'
    )
    parser.add_argument(
        '--template',
        default='services/publication/templates/GAI_Summary_Template.docx',
        help='Path to Word template file'
    )
    parser.add_argument(
        '--output',
        default='services/publication/output',
        help='Output directory for generated files'
    )
    parser.add_argument(
        '--max-sources',
        type=int,
        default=10,
        help='Maximum source documents per section (default: 10)'
    )
    parser.add_argument(
        '--no-consolidation',
        action='store_true',
        help='Skip event consolidation step'
    )
    parser.add_argument(
        '--use-existing',
        action='store_true',
        default=True,
        help='Use existing EventSummary data (default: True)'
    )

    args = parser.parse_args()

    # Parse arguments
    try:
        start_date = parse_date(args.start)
        end_date = parse_date(args.end)
        period_type = parse_period_type(args.period_type)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Validate dates
    if start_date > end_date:
        print("Error: Start date must be before or equal to end date")
        sys.exit(1)

    # Parse categories
    categories = [cat.strip() for cat in args.categories.split(',')]

    # Parse recipients if provided
    recipient_countries = None
    if args.recipients:
        recipient_countries = [r.strip() for r in args.recipients.split(',')]

    # Check template exists
    template_path = args.template
    if not os.path.exists(template_path):
        print(f"Error: Template file not found: {template_path}")
        sys.exit(1)

    # Check for image file
    image_path = 'services/publication/templates/atom.png'
    if not os.path.exists(image_path):
        print(f"Warning: Image file not found: {image_path}. Hyperlinks will not have images.")
        image_path = None

    # Print configuration
    print("=" * 70)
    print("PUBLICATION GENERATION")
    print("=" * 70)
    print(f"Country:           {args.country}")
    print(f"Period:            {start_date} to {end_date}")
    print(f"Period Type:       {args.period_type}")
    print(f"Categories:        {', '.join(categories)}")
    if recipient_countries:
        print(f"Recipients:        {', '.join(recipient_countries)}")
    print(f"Model:             {args.model}")
    print(f"Template:          {template_path}")
    print(f"Output Directory:  {args.output}")
    print(f"Max Sources:       {args.max_sources}")
    print(f"Consolidation:     {'Disabled' if args.no_consolidation else 'Enabled'}")
    print("=" * 70)
    print()

    # Create database session
    with get_session() as session:
        # Create service
        service = PublicationService(
            session=session,
            template_path=template_path,
            output_dir=args.output,
            image_path=image_path,
            model=args.model
        )

        try:
            # Generate publication
            result = service.generate_publication(
                initiating_country=args.country,
                start_date=start_date,
                end_date=end_date,
                categories=categories,
                recipient_countries=recipient_countries,
                period_type=period_type,
                use_existing_summaries=args.use_existing,
                max_sources_per_section=args.max_sources
            )

            if result:
                print()
                print("=" * 70)
                print("✅ PUBLICATION GENERATED SUCCESSFULLY")
                print("=" * 70)
                print(f"Title:             {result.get('title', 'N/A')}")
                print(f"Reviewer Version:  {result.get('reviewer_version', 'N/A')}")
                print(f"Summary Version:   {result.get('summary_version', 'N/A')}")
                print("=" * 70)
            else:
                print()
                print("=" * 70)
                print("⚠️  NO PUBLICATION GENERATED")
                print("=" * 70)
                print("No event summaries found for the specified parameters.")
                print("Make sure EventSummary data exists in the database for this period.")
                sys.exit(1)

        except Exception as e:
            print()
            print("=" * 70)
            print("❌ ERROR GENERATING PUBLICATION")
            print("=" * 70)
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
