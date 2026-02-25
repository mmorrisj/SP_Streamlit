"""
AidData Global Chinese Development Finance Dataset v3.0 - Ingestion Script

Imports the GCDF 3.0 XLSX into PostgreSQL tables:
  - aiddata_projects  : 20,985 project records
  - aiddata_locations : ADM1 + ADM2 sub-national location data

Usage:
    python services/pipeline/ingestion/aiddata.py
    python services/pipeline/ingestion/aiddata.py --dry-run
    python services/pipeline/ingestion/aiddata.py --projects-only
    python services/pipeline/ingestion/aiddata.py --locations-only
    python services/pipeline/ingestion/aiddata.py --clear
"""

import argparse
import csv
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.database.database import get_session
from shared.models.models import AidDataProject, AidDataLocation

DATASET_DIR = Path(__file__).resolve().parents[3] / "AidDatas_Global_Chinese_Development_Finance_Dataset_Version_3_0"
XLSX_PATH   = DATASET_DIR / "AidDatasGlobalChineseDevelopmentFinanceDataset_v3.0.xlsx"
ADM1_PATH   = DATASET_DIR / "ADM Location Data" / "GCDF_3.0_ADM1_Locations.csv"
ADM2_PATH   = DATASET_DIR / "ADM Location Data" / "GCDF_3.0_ADM2_Locations.csv"
SHEET_NAME  = "GCDF_3.0"
BATCH_SIZE  = 500


def _bool(val) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s == 'yes':
        return True
    if s == 'no':
        return False
    return None


def _int(val) -> Optional[int]:
    try:
        if val is None or str(val).strip() == '':
            return None
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _float(val) -> Optional[float]:
    try:
        if val is None or str(val).strip() == '':
            return None
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def _text(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


_COL: dict = {}


def _build_col_map(headers: tuple) -> None:
    global _COL
    _COL = {h: i for i, h in enumerate(headers) if h is not None}


def _get(row: tuple, name: str):
    idx = _COL.get(name)
    if idx is None:
        return None
    return row[idx] if idx < len(row) else None


def row_to_project(row: tuple) -> dict:
    return {
        'aiddata_record_id':              _int(_get(row, 'AidData Record ID')),
        'aiddata_parent_id':              _int(_get(row, 'AidData Parent ID')),
        'recommended_for_aggregates':     _bool(_get(row, 'Recommended For Aggregates')),
        'umbrella':                       _bool(_get(row, 'Umbrella')),
        'status':                         _text(_get(row, 'Status')),
        'intent':                         _text(_get(row, 'Intent')),
        'financier_country':              _text(_get(row, 'Financier Country')),
        'recipient':                      _text(_get(row, 'Recipient')),
        'recipient_iso3':                 _text(_get(row, 'Recipient ISO-3')),
        'recipient_region':               _text(_get(row, 'Recipient Region')),
        'oda_eligible_recipient':         _text(_get(row, 'ODA Eligible Recipient')),
        'oecd_oda_income_group':          _text(_get(row, 'OECD ODA Income Group')),
        'commitment_year':                _int(_get(row, 'Commitment Year')),
        'implementation_start_year':      _int(_get(row, 'Implementation Start Year')),
        'completion_year':                _int(_get(row, 'Completion Year')),
        'commitment_date':                _date(_get(row, 'Commitment Date (MM/DD/YYYY)')),
        'flow_type':                      _text(_get(row, 'Flow Type')),
        'flow_type_simplified':           _text(_get(row, 'Flow Type Simplified')),
        'flow_class':                     _text(_get(row, 'Flow Class')),
        'amount_original_currency':       _float(_get(row, 'Amount (Original Currency)')),
        'original_currency':              _text(_get(row, 'Original Currency')),
        'amount_usd_2021':                _float(_get(row, 'Amount (Constant USD 2021)')),
        'amount_nominal_usd':             _float(_get(row, 'Amount (Nominal USD)')),
        'adjusted_amount_usd_2021':       _float(_get(row, 'Adjusted Amount (Constant USD 2021)')),
        'adjusted_amount_nominal_usd':    _float(_get(row, 'Adjusted Amount (Nominal USD)')),
        'sector_code':                    _int(_get(row, 'Sector Code')),
        'sector_name':                    _text(_get(row, 'Sector Name')),
        'infrastructure':                 _bool(_get(row, 'Infrastructure')),
        'covid':                          _bool(_get(row, 'COVID')),
        'funding_agencies':               _text(_get(row, 'Funding Agencies')),
        'funding_agencies_type':          _text(_get(row, 'Funding Agencies Type')),
        'cofinanced':                     _bool(_get(row, 'Co-financed')),
        'cofinancing_agencies':           _text(_get(row, 'Co-financing Agencies')),
        'direct_receiving_agencies':      _text(_get(row, 'Direct Receiving Agencies')),
        'direct_receiving_agencies_type': _text(_get(row, 'Direct Receiving Agencies Type')),
        'implementing_agencies':          _text(_get(row, 'Implementing Agencies')),
        'on_lending':                     _bool(_get(row, 'On-lending')),
        'title':                          _text(_get(row, 'Title')),
        'description':                    _text(_get(row, 'Description')),
        'location_narrative':             _text(_get(row, 'Location Narrative')),
        'maturity':                       _float(_get(row, 'Maturity')),
        'interest_rate':                  _float(_get(row, 'Interest Rate')),
        'grace_period':                   _float(_get(row, 'Grace Period')),
        'management_fee':                 _float(_get(row, 'Management Fee')),
        'commitment_fee':                 _float(_get(row, 'Commitment Fee')),
        'grant_element_imf':              _float(_get(row, 'Grant Element (IMF)')),
        'grant_element_oecd_cashflow':    _float(_get(row, 'Grant Element (OECD Cash-Flow)')),
        'financial_distress':             _bool(_get(row, 'Financial Distress')),
        'guarantee_provided':             _bool(_get(row, 'Guarantee Provided')),
        'collateralized':                 _bool(_get(row, 'Collateralized')),
        'rescue':                         _bool(_get(row, 'Rescue')),
        'level_of_public_liability':      _text(_get(row, 'Level of Public Liability')),
        'geographic_precision':           _text(_get(row, 'Geographic Level of Precision Available')),
        'adm1_available':                 _bool(_get(row, 'ADM1 Level Available')),
        'adm2_available':                 _bool(_get(row, 'ADM2 Level Available')),
        'source_quality_score':           _int(_get(row, 'Source Quality Score')),
        'data_completeness_score':        _int(_get(row, 'Data Completeness Score')),
        'implementation_detail_score':    _int(_get(row, 'Implementation Detail Score')),
        'loan_detail_score':              _int(_get(row, 'Loan Detail Score')),
        'total_source_count':             _int(_get(row, 'Total Source Count')),
        'official_source_count':          _int(_get(row, 'Official Source Count')),
    }


def import_projects(dry_run: bool = False, clear: bool = False) -> int:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Loading projects from:\n  {XLSX_PATH}")
    if not XLSX_PATH.exists():
        print(f"ERROR: XLSX not found at {XLSX_PATH}")
        return 0

    wb = openpyxl.load_workbook(str(XLSX_PATH), read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    row_iter = ws.iter_rows(values_only=True)
    headers = next(row_iter)
    _build_col_map(headers)

    with get_session() as session:
        if clear:
            deleted = session.query(AidDataProject).delete()
            print(f"  Cleared {deleted:,} existing rows")

        existing_ids = set(
            r[0] for r in session.query(AidDataProject.aiddata_record_id).all()
        )
        print(f"  {len(existing_ids):,} projects already in DB — skipping duplicates")

        batch = []
        total = skipped = errors = 0

        for raw_row in row_iter:
            data = row_to_project(raw_row)
            record_id = data.get('aiddata_record_id')

            if record_id is None:
                errors += 1
                continue
            if record_id in existing_ids:
                skipped += 1
                continue

            batch.append(data)
            total += 1

            if len(batch) >= BATCH_SIZE:
                if not dry_run:
                    session.bulk_insert_mappings(AidDataProject, batch)
                    session.flush()
                print(f"  Inserted {total:,} projects...", end='\r')
                batch = []

        if batch and not dry_run:
            session.bulk_insert_mappings(AidDataProject, batch)

    wb.close()
    print(f"\n  Done — {total:,} inserted, {skipped:,} skipped, {errors} errors")
    return total


def _load_adm_csv(path: Path, adm_level: str, valid_ids: set) -> list:
    rows = []
    if not path.exists():
        print(f"  WARNING: {path.name} not found, skipping")
        return rows

    with open(str(path), newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for csv_row in reader:
            record_id = _int(csv_row.get('id'))
            if record_id is None or record_id not in valid_ids:
                continue
            rows.append({
                'aiddata_record_id':                   record_id,
                'adm_level':                           adm_level,
                'shape_id':                            _text(csv_row.get('shapeID')),
                'shape_group':                         _text(csv_row.get('shapeGroup')),
                'shape_name':                          _text(csv_row.get('shapeName')),
                'intersection_ratio':                  _float(csv_row.get('intersection_ratio')),
                'even_split_ratio':                    _float(csv_row.get('even_split_ratio')),
                'intersection_ratio_commitment_value': _float(csv_row.get('intersection_ratio_commitment_value')),
                'even_split_ratio_commitment_value':   _float(csv_row.get('even_split_ratio_commitment_value')),
                'centroid_longitude':                  _float(csv_row.get('centroid_longitude')),
                'centroid_latitude':                   _float(csv_row.get('centroid_latitude')),
            })
    return rows


def import_locations(dry_run: bool = False, clear: bool = False) -> int:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Loading ADM1 + ADM2 locations...")

    with get_session() as session:
        if clear:
            deleted = session.query(AidDataLocation).delete()
            print(f"  Cleared {deleted:,} existing location rows")

        valid_ids = set(
            r[0] for r in session.query(AidDataProject.aiddata_record_id).all()
        )
        if not valid_ids:
            print("  WARNING: No projects in DB — run project import first")
            return 0
        print(f"  {len(valid_ids):,} projects available for location linking")

        adm1_rows = _load_adm_csv(ADM1_PATH, 'ADM1', valid_ids)
        adm2_rows = _load_adm_csv(ADM2_PATH, 'ADM2', valid_ids)
        all_rows = adm1_rows + adm2_rows
        total = len(all_rows)
        print(f"  ADM1: {len(adm1_rows):,} | ADM2: {len(adm2_rows):,} | Total: {total:,}")

        if not dry_run and all_rows:
            for i in range(0, total, BATCH_SIZE):
                session.bulk_insert_mappings(AidDataLocation, all_rows[i:i + BATCH_SIZE])
                session.flush()
                print(f"  Inserted {min(i + BATCH_SIZE, total):,}/{total:,} locations...", end='\r')
            print()

    print(f"  Done — {total:,} location rows inserted")
    return total


def main():
    parser = argparse.ArgumentParser(description="Import AidData GCDF 3.0 into PostgreSQL")
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse data but do not write to DB')
    parser.add_argument('--projects-only', action='store_true',
                        help='Import only the aiddata_projects table')
    parser.add_argument('--locations-only', action='store_true',
                        help='Import only the aiddata_locations table')
    parser.add_argument('--clear', action='store_true',
                        help='Delete existing rows before importing (full reload)')
    args = parser.parse_args()

    run_projects  = not args.locations_only
    run_locations = not args.projects_only

    start = datetime.now()
    print(f"AidData GCDF 3.0 ingestion — {start:%Y-%m-%d %H:%M:%S}")
    print(f"  dry_run={args.dry_run}  clear={args.clear}")

    if run_projects:
        import_projects(dry_run=args.dry_run, clear=args.clear)

    if run_locations:
        import_locations(dry_run=args.dry_run, clear=(args.clear and not run_projects))

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\nFinished in {elapsed:.1f}s")


if __name__ == '__main__':
    main()
