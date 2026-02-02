"""
JSONL file utilities for OpenAI Batch API processing.

Provides functions to read, write, and manipulate JSONL (JSON Lines) files
used by the OpenAI Batch API.
"""
import json
from typing import List, Dict, Any, Generator, Optional
from pathlib import Path


def read_jsonl(file_path: str) -> Generator[Dict[str, Any], None, None]:
    """
    Read JSONL file line by line as a generator.

    Args:
        file_path: Path to JSONL file

    Yields:
        Dictionary parsed from each line

    Example:
        >>> for record in read_jsonl('batch_input.jsonl'):
        ...     print(record['custom_id'])
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:  # Skip empty lines
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON on line: {line[:50]}... Error: {e}")


def read_jsonl_as_list(file_path: str) -> List[Dict[str, Any]]:
    """
    Read entire JSONL file into a list.

    Useful for smaller files where you need all records in memory.

    Args:
        file_path: Path to JSONL file

    Returns:
        List of dictionaries

    Example:
        >>> records = read_jsonl_as_list('batch_input.jsonl')
        >>> print(f"Found {len(records)} records")
    """
    return list(read_jsonl(file_path))


def write_jsonl(file_path: str, records: List[Dict[str, Any]], mode: str = 'w') -> int:
    """
    Write records to JSONL file.

    Args:
        file_path: Path to output JSONL file
        records: List of dictionaries to write
        mode: File mode ('w' for write, 'a' for append). Default: 'w'

    Returns:
        Number of records written

    Example:
        >>> records = [
        ...     {"custom_id": "req-1", "method": "POST", ...},
        ...     {"custom_id": "req-2", "method": "POST", ...}
        ... ]
        >>> count = write_jsonl('batch_input.jsonl', records)
        >>> print(f"Wrote {count} records")
    """
    count = 0
    with open(file_path, mode, encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            count += 1
    return count


def append_to_jsonl(file_path: str, record: Dict[str, Any]) -> None:
    """
    Append a single record to JSONL file.

    Args:
        file_path: Path to JSONL file
        record: Dictionary to append

    Example:
        >>> record = {"custom_id": "req-1", "method": "POST", ...}
        >>> append_to_jsonl('batch_input.jsonl', record)
    """
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def count_jsonl_lines(file_path: str) -> int:
    """
    Count number of non-empty lines in JSONL file.

    Args:
        file_path: Path to JSONL file

    Returns:
        Number of records

    Example:
        >>> count = count_jsonl_lines('batch_input.jsonl')
        >>> print(f"File contains {count} records")
    """
    count = 0
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def validate_jsonl_file(file_path: str) -> Dict[str, Any]:
    """
    Validate JSONL file structure and content.

    Args:
        file_path: Path to JSONL file

    Returns:
        Validation report with keys:
        - valid: bool
        - total_lines: int
        - invalid_lines: List[int] (line numbers)
        - errors: List[str]

    Example:
        >>> report = validate_jsonl_file('batch_input.jsonl')
        >>> if not report['valid']:
        ...     print(f"Errors: {report['errors']}")
    """
    errors = []
    invalid_lines = []
    total_lines = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue  # Skip empty lines

            total_lines += 1
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                invalid_lines.append(line_num)
                errors.append(f"Line {line_num}: {str(e)}")

    return {
        'valid': len(invalid_lines) == 0,
        'total_lines': total_lines,
        'invalid_lines': invalid_lines,
        'errors': errors
    }


def split_jsonl_file(input_file: str, output_prefix: str, chunk_size: int) -> List[str]:
    """
    Split large JSONL file into smaller chunks.

    Useful for managing OpenAI Batch API limits or parallel processing.

    Args:
        input_file: Path to input JSONL file
        output_prefix: Prefix for output files (will add _001.jsonl, _002.jsonl, etc.)
        chunk_size: Number of records per chunk

    Returns:
        List of output file paths

    Example:
        >>> output_files = split_jsonl_file('large_batch.jsonl', 'batch_chunk', 1000)
        >>> print(f"Split into {len(output_files)} files")
    """
    output_files = []
    chunk_num = 1
    records_buffer = []

    for record in read_jsonl(input_file):
        records_buffer.append(record)

        if len(records_buffer) >= chunk_size:
            output_file = f"{output_prefix}_{chunk_num:03d}.jsonl"
            write_jsonl(output_file, records_buffer)
            output_files.append(output_file)
            chunk_num += 1
            records_buffer = []

    # Write remaining records
    if records_buffer:
        output_file = f"{output_prefix}_{chunk_num:03d}.jsonl"
        write_jsonl(output_file, records_buffer)
        output_files.append(output_file)

    return output_files


def filter_jsonl_by_custom_id(input_file: str, output_file: str, custom_ids: List[str]) -> int:
    """
    Filter JSONL file to only include records with specific custom_ids.

    Useful for retrying failed items from a batch.

    Args:
        input_file: Path to input JSONL file
        output_file: Path to output JSONL file
        custom_ids: List of custom_ids to include

    Returns:
        Number of records written to output file

    Example:
        >>> failed_ids = ['req-123', 'req-456']
        >>> count = filter_jsonl_by_custom_id('batch_input.jsonl', 'retry_batch.jsonl', failed_ids)
        >>> print(f"Created retry batch with {count} requests")
    """
    custom_id_set = set(custom_ids)
    matching_records = []

    for record in read_jsonl(input_file):
        if record.get('custom_id') in custom_id_set:
            matching_records.append(record)

    return write_jsonl(output_file, matching_records)


def extract_custom_ids(file_path: str) -> List[str]:
    """
    Extract all custom_ids from a JSONL file.

    Args:
        file_path: Path to JSONL file

    Returns:
        List of custom_ids

    Example:
        >>> custom_ids = extract_custom_ids('batch_input.jsonl')
        >>> print(f"Found {len(custom_ids)} requests")
    """
    custom_ids = []
    for record in read_jsonl(file_path):
        custom_id = record.get('custom_id')
        if custom_id:
            custom_ids.append(custom_id)
    return custom_ids


def merge_jsonl_files(input_files: List[str], output_file: str) -> int:
    """
    Merge multiple JSONL files into one.

    Args:
        input_files: List of input JSONL file paths
        output_file: Path to output JSONL file

    Returns:
        Total number of records written

    Example:
        >>> files = ['batch_001.jsonl', 'batch_002.jsonl', 'batch_003.jsonl']
        >>> count = merge_jsonl_files(files, 'batch_merged.jsonl')
        >>> print(f"Merged {count} records from {len(files)} files")
    """
    total_count = 0

    with open(output_file, 'w', encoding='utf-8') as out_f:
        for input_file in input_files:
            for record in read_jsonl(input_file):
                out_f.write(json.dumps(record, ensure_ascii=False) + '\n')
                total_count += 1

    return total_count
