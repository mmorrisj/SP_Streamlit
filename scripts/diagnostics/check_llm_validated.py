import sys
from pathlib import Path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from shared.database.database import get_session

with get_session() as session:
    # Check if llm_validated column exists
    result = session.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'canonical_events'
        AND column_name LIKE '%llm%'
    """)).fetchall()

    print("LLM-related columns in canonical_events:")
    if result:
        for row in result:
            print(f"  - {row[0]}: {row[1]}")
    else:
        print("  No LLM-related columns found!")

    # Check count of validated vs unvalidated events for China
    try:
        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE llm_validated = TRUE) as validated,
                COUNT(*) FILTER (WHERE llm_validated = FALSE) as not_validated,
                COUNT(*) as total
            FROM canonical_events
            WHERE initiating_country = 'China'
            AND master_event_id IS NULL
        """)).fetchone()

        print("\nChina master events status:")
        print(f"  Validated: {result[0]}")
        print(f"  Not validated: {result[1]}")
        print(f"  Total: {result[2]}")
    except Exception as e:
        print(f"\nError checking validation status: {e}")
