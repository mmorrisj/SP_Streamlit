"""
Custom ID utilities for OpenAI Batch API processing.

Provides functions to generate and parse custom IDs that link batch
results back to database records.

Format: {job_type}_{record_id}_{optional_suffix}

Examples:
- cluster_deconflict_8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c
- canonical_deconflict_7b2c1a0d-4e5f-3g6h-7i8j-9k0l1m2n3o4p
"""
import uuid
from typing import Dict, Optional


def generate_custom_id(job_type: str, record_id: uuid.UUID, suffix: Optional[str] = None) -> str:
    """
    Generate a custom_id for OpenAI Batch API request.

    Args:
        job_type: Job type ('cluster_deconflict', 'canonical_deconflict', etc.)
        record_id: UUID of the database record
        suffix: Optional suffix for additional identification

    Returns:
        Custom ID string in format: {job_type}_{record_id}_{suffix}

    Examples:
        >>> record_id = uuid.UUID('8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c')
        >>> generate_custom_id('cluster_deconflict', record_id)
        'cluster_deconflict_8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c'

        >>> generate_custom_id('entity_extract', record_id, 'person')
        'entity_extract_8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c_person'
    """
    # Convert UUID to string if needed
    record_id_str = str(record_id) if isinstance(record_id, uuid.UUID) else record_id

    # Validate job_type format (alphanumeric and underscores only)
    if not all(c.isalnum() or c == '_' for c in job_type):
        raise ValueError(f"Invalid job_type: {job_type}. Must be alphanumeric with underscores.")

    base = f"{job_type}_{record_id_str}"
    return f"{base}_{suffix}" if suffix else base


def parse_custom_id(custom_id: str) -> Dict[str, Optional[str]]:
    """
    Parse a custom_id into its components.

    Args:
        custom_id: Custom ID string from OpenAI Batch API response

    Returns:
        Dictionary with keys:
        - job_type: str (e.g., 'cluster_deconflict')
        - record_id: UUID object
        - suffix: Optional[str]

    Raises:
        ValueError: If custom_id format is invalid

    Examples:
        >>> parse_custom_id('cluster_deconflict_8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c')
        {
            'job_type': 'cluster_deconflict',
            'record_id': UUID('8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c'),
            'suffix': None
        }

        >>> parse_custom_id('entity_extract_7b2c1a0d-4e5f-3g6h-7i8j-9k0l1m2n3o4p_person')
        {
            'job_type': 'entity_extract',
            'record_id': UUID('7b2c1a0d-4e5f-3g6h-7i8j-9k0l1m2n3o4p'),
            'suffix': 'person'
        }
    """
    parts = custom_id.split('_')

    if len(parts) < 2:
        raise ValueError(f"Invalid custom_id format: {custom_id}. Expected at least 2 parts.")

    # Handle multi-word job types (e.g., "cluster_deconflict" = ["cluster", "deconflict"])
    # The UUID is always at index -1 or -2 (if there's a suffix)

    # Try to find the UUID in the parts
    record_id_str = None
    job_type_parts = []
    suffix = None

    for i, part in enumerate(parts):
        try:
            # Try to parse as UUID
            uuid.UUID(part)
            record_id_str = part

            # Everything before this is job_type
            job_type_parts = parts[:i]

            # Everything after this is suffix
            if i + 1 < len(parts):
                suffix = '_'.join(parts[i+1:])

            break
        except ValueError:
            continue

    if not record_id_str:
        raise ValueError(f"Invalid custom_id format: {custom_id}. Could not find valid UUID.")

    if not job_type_parts:
        raise ValueError(f"Invalid custom_id format: {custom_id}. Missing job_type.")

    job_type = '_'.join(job_type_parts)

    try:
        record_id = uuid.UUID(record_id_str)
    except ValueError:
        raise ValueError(f"Invalid UUID in custom_id: {record_id_str}")

    return {
        'job_type': job_type,
        'record_id': record_id,
        'suffix': suffix
    }


def validate_custom_id(custom_id: str) -> bool:
    """
    Validate that a custom_id is properly formatted.

    Args:
        custom_id: Custom ID string to validate

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_custom_id('cluster_deconflict_8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c')
        True

        >>> validate_custom_id('invalid_format')
        False
    """
    try:
        parse_custom_id(custom_id)
        return True
    except ValueError:
        return False
