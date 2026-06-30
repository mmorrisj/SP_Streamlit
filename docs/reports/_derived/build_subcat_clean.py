"""Build analytics.subcat_clean — normalize dirty subcategory labels (strip 'X. ' enumeration
prefixes leaked by extraction, strip 'Other-', trim). public read-only.
Run: python docs/reports/_derived/build_subcat_clean.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.database.database import get_session
from sqlalchemy import text

DDL = r"""
CREATE TABLE analytics.subcat_clean AS
WITH norm AS (
  SELECT DISTINCT subcategory AS raw_label,
         btrim(regexp_replace(subcategory, '^[A-Z]\.\s*', '')) AS s1
  FROM subcategories)
SELECT raw_label,
       CASE WHEN s1 ILIKE 'Other-%' THEN btrim(substring(s1 from 7)) ELSE s1 END AS clean_label
FROM norm
"""

if __name__ == "__main__":
    with get_session() as s:
        s.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
        s.execute(text("DROP TABLE IF EXISTS analytics.subcat_clean CASCADE"))
        s.execute(text(DDL))
        s.execute(text("CREATE INDEX ix_subcat_clean_raw ON analytics.subcat_clean(raw_label)"))
        s.commit()
        n = s.execute(text("SELECT count(*) FROM analytics.subcat_clean")).scalar()
    print(f"[done] analytics.subcat_clean: {n} labels")
