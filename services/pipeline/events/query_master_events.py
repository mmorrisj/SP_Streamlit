"""
Helper functions for querying master events and their underlying data.

Usage examples:
    # Get all doc_ids for a master event
    python query_master_events.py --master-event "Ceasefire Proposal in Gaza" --get-docs

    # Get timeline for master event
    python query_master_events.py --master-event "Ceasefire Proposal in Gaza" --timeline

    # List top master events
    python query_master_events.py --list-top 10 --country "United States"
"""

import argparse
from datetime import date
from typing import List, Dict
from sqlalchemy import text

from shared.database.database import get_session


def get_master_event_docs(master_event_name: str, country: str = None) -> List[str]:
    """
    Get all document IDs for a master event.

    Args:
        master_event_name: Name of the master event
        country: Optional country filter

    Returns:
        List of document IDs
    """
    with get_session() as session:
        query = '''
            SELECT DISTINCT unnest(dem.doc_ids) as doc_id
            FROM canonical_events m
            JOIN canonical_events c ON c.master_event_id = m.id
            JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
            AND m.canonical_name = :name
        '''

        params = {'name': master_event_name}

        if country:
            query += " AND m.initiating_country = :country"
            params['country'] = country

        result = session.execute(text(query), params)
        return [row[0] for row in result]


def get_master_event_timeline(master_event_name: str, country: str = None) -> List[Dict]:
    """
    Get daily timeline for a master event.

    Args:
        master_event_name: Name of the master event
        country: Optional country filter

    Returns:
        List of dicts with date and article counts
    """
    with get_session() as session:
        query = '''
            SELECT
                dem.mention_date,
                c.canonical_name,
                dem.article_count,
                array_length(dem.doc_ids, 1) as doc_count
            FROM canonical_events m
            JOIN canonical_events c ON c.master_event_id = m.id
            JOIN daily_event_mentions dem ON dem.canonical_event_id = c.id
            WHERE m.master_event_id IS NULL
            AND m.canonical_name = :name
        '''

        params = {'name': master_event_name}

        if country:
            query += " AND m.initiating_country = :country"
            params['country'] = country

        query += " ORDER BY dem.mention_date"

        result = session.execute(text(query), params)
        return [
            {
                'date': row[0],
                'event_name': row[1],
                'articles': row[2],
                'doc_count': row[3]
            }
            for row in result
        ]


def list_top_master_events(limit: int = 10, country: str = None) -> List[Dict]:
    """
    List top master events by article count.

    Args:
        limit: Number of events to return
        country: Optional country filter

    Returns:
        List of dicts with master event info
    """
    with get_session() as session:
        query = '''
            SELECT
                m.canonical_name,
                m.initiating_country,
                m.first_mention_date,
                m.last_mention_date,
                m.total_articles,
                COUNT(DISTINCT c.id) as child_count
            FROM canonical_events m
            LEFT JOIN canonical_events c ON c.master_event_id = m.id
            WHERE m.master_event_id IS NULL
        '''

        params = {'limit': limit}

        if country:
            query += " AND m.initiating_country = :country"
            params['country'] = country

        query += '''
            GROUP BY m.id
            ORDER BY m.total_articles DESC
            LIMIT :limit
        '''

        result = session.execute(text(query), params)
        return [
            {
                'name': row[0],
                'country': row[1],
                'first_date': row[2],
                'last_date': row[3],
                'total_articles': row[4],
                'child_events': row[5],
                'days_span': (row[3] - row[2]).days + 1
            }
            for row in result
        ]


def main():
    parser = argparse.ArgumentParser(
        description="Query master events and their underlying data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Query options
    parser.add_argument('--master-event', type=str, help='Master event name to query')
    parser.add_argument('--country', type=str, help='Filter by country')

    # Actions
    parser.add_argument('--get-docs', action='store_true', help='Get all doc_ids for master event')
    parser.add_argument('--timeline', action='store_true', help='Get daily timeline for master event')
    parser.add_argument('--list-top', type=int, help='List top N master events')

    args = parser.parse_args()

    if args.list_top:
        events = list_top_master_events(args.list_top, args.country)
        print(f"Top {args.list_top} Master Events" + (f" ({args.country})" if args.country else ""))
        print("=" * 100)
        for i, event in enumerate(events, 1):
            print(f"\n{i}. {event['name']}")
            print(f"   Country: {event['country']}")
            print(f"   Period: {event['first_date']} to {event['last_date']} ({event['days_span']} days)")
            print(f"   Articles: {event['total_articles']}")
            print(f"   Child Events: {event['child_events']}")

    elif args.master_event:
        if args.get_docs:
            doc_ids = get_master_event_docs(args.master_event, args.country)
            print(f"Documents for '{args.master_event}':")
            print(f"Total: {len(doc_ids)} documents")
            print("\nSample doc_ids:")
            for doc_id in doc_ids[:10]:
                print(f"  {doc_id}")
            if len(doc_ids) > 10:
                print(f"  ... and {len(doc_ids) - 10} more")

        elif args.timeline:
            timeline = get_master_event_timeline(args.master_event, args.country)
            print(f"Timeline for '{args.master_event}':")
            print("=" * 100)
            for entry in timeline:
                print(f"{entry['date']}: {entry['event_name']}")
                print(f"  Articles: {entry['articles']}, Documents: {entry['doc_count']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
