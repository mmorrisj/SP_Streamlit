"""
Configuration constants for OpenAI Batch API processing.

Provides centralized configuration for batch job types, models,
file paths, and processing parameters.
"""
import os
from pathlib import Path
from typing import Dict, Any


# Job types
JOB_TYPE_CLUSTER_DECONFLICT = "cluster_deconflict"
JOB_TYPE_CANONICAL_DECONFLICT = "canonical_deconflict"
JOB_TYPE_ENTITY_EXTRACT = "entity_extract"
JOB_TYPE_SCORE_MATERIALITY = "score_materiality"
JOB_TYPE_DAILY_ENTITY_EXTRACT = "daily_entity_extract"
JOB_TYPE_ENTITY_DECONFLICT = "entity_deconflict"
JOB_TYPE_CANONICAL_ENTITY_DECONFLICT = "canonical_entity_deconflict"
JOB_TYPE_GENERATE_DAILY_SUMMARY = "generate_daily_summary"
JOB_TYPE_GENERATE_WEEKLY_SUMMARY = "generate_weekly_summary"
JOB_TYPE_GENERATE_MONTHLY_SUMMARY = "generate_monthly_summary"
JOB_TYPE_SCORE_SUMMARY_MATERIALITY = "score_summary_materiality"
JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS = "generate_entity_descriptions"
JOB_TYPE_GENERATE_BILATERAL_SUMMARIES = "generate_bilateral_summaries"
JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS = "classify_entity_relationships"
JOB_TYPE_EVENT_RENAME = "event_rename"

# Supported job types
SUPPORTED_JOB_TYPES = [
    JOB_TYPE_CLUSTER_DECONFLICT,
    JOB_TYPE_CANONICAL_DECONFLICT,
    JOB_TYPE_ENTITY_EXTRACT,
    JOB_TYPE_SCORE_MATERIALITY,
    JOB_TYPE_DAILY_ENTITY_EXTRACT,
    JOB_TYPE_ENTITY_DECONFLICT,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
    JOB_TYPE_GENERATE_DAILY_SUMMARY,
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
    JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
    JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
    JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
    JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
    JOB_TYPE_EVENT_RENAME,
]

# OpenAI API configuration
OPENAI_API_KEY_ENV = "OPENAI_PROJ_API"
OPENAI_BATCH_ENDPOINT = "/v1/chat/completions"
OPENAI_COMPLETION_WINDOW = "24h"

# Tiered model selection: reasoning-heavy tasks use stronger models,
# high-volume extraction tasks use cost-effective models.
# Override any job's model via env var: BATCH_MODEL_<JOB_TYPE>=model-name
_EXTRACTION_MODEL = os.getenv("BATCH_MODEL_EXTRACTION", "gpt-4o-mini")
_REASONING_MODEL = os.getenv("BATCH_MODEL_REASONING", "gpt-4o-mini")
_GENERATION_MODEL = os.getenv("BATCH_MODEL_GENERATION", "gpt-4o-mini")

DEFAULT_MODELS = {
    # Extraction tasks (high volume, structured output) — cost-effective model
    JOB_TYPE_ENTITY_EXTRACT: _EXTRACTION_MODEL,
    JOB_TYPE_DAILY_ENTITY_EXTRACT: _EXTRACTION_MODEL,
    JOB_TYPE_SCORE_MATERIALITY: _EXTRACTION_MODEL,
    JOB_TYPE_SCORE_SUMMARY_MATERIALITY: _EXTRACTION_MODEL,
    JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS: _EXTRACTION_MODEL,
    JOB_TYPE_EVENT_RENAME: _EXTRACTION_MODEL,
    # Reasoning tasks (deconfliction, judgment) — stronger model
    JOB_TYPE_CLUSTER_DECONFLICT: _REASONING_MODEL,
    JOB_TYPE_CANONICAL_DECONFLICT: _REASONING_MODEL,
    JOB_TYPE_ENTITY_DECONFLICT: _REASONING_MODEL,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT: _REASONING_MODEL,
    # Generation tasks (user-facing narratives) — stronger model
    JOB_TYPE_GENERATE_DAILY_SUMMARY: _GENERATION_MODEL,
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY: _GENERATION_MODEL,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY: _GENERATION_MODEL,
    JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS: _GENERATION_MODEL,
    JOB_TYPE_GENERATE_BILATERAL_SUMMARIES: _GENERATION_MODEL,
}

# Temperature settings per task tier
TEMPERATURE_EXTRACTION = 0.1    # Deterministic for structured extraction
TEMPERATURE_REASONING = 0.3     # Consistent analytical judgment
TEMPERATURE_GENERATION = 0.4    # Slight creativity for narratives

# Map job types to appropriate temperatures
TEMPERATURE_BY_JOB_TYPE = {
    JOB_TYPE_ENTITY_EXTRACT: TEMPERATURE_EXTRACTION,
    JOB_TYPE_DAILY_ENTITY_EXTRACT: TEMPERATURE_EXTRACTION,
    JOB_TYPE_SCORE_MATERIALITY: TEMPERATURE_EXTRACTION,
    JOB_TYPE_SCORE_SUMMARY_MATERIALITY: TEMPERATURE_EXTRACTION,
    JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS: TEMPERATURE_EXTRACTION,
    JOB_TYPE_EVENT_RENAME: TEMPERATURE_EXTRACTION,
    JOB_TYPE_CLUSTER_DECONFLICT: TEMPERATURE_REASONING,
    JOB_TYPE_CANONICAL_DECONFLICT: TEMPERATURE_REASONING,
    JOB_TYPE_ENTITY_DECONFLICT: TEMPERATURE_REASONING,
    JOB_TYPE_CANONICAL_ENTITY_DECONFLICT: TEMPERATURE_REASONING,
    JOB_TYPE_GENERATE_DAILY_SUMMARY: TEMPERATURE_GENERATION,
    JOB_TYPE_GENERATE_WEEKLY_SUMMARY: TEMPERATURE_GENERATION,
    JOB_TYPE_GENERATE_MONTHLY_SUMMARY: TEMPERATURE_GENERATION,
    JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS: TEMPERATURE_GENERATION,
    JOB_TYPE_GENERATE_BILATERAL_SUMMARIES: TEMPERATURE_GENERATION,
}

DEFAULT_TEMPERATURE = 0.1  # Fallback for backward compatibility

# Batch processing limits
MAX_BATCH_SIZE = 50000  # OpenAI API limit per batch
RECOMMENDED_BATCH_SIZE = 4000  # Conservative batch size for reliable uploads
MAX_UPLOAD_FILE_SIZE_MB = 2  # Max JSONL file size for upload (network/SSL inspection safe)
DEFAULT_CHECKPOINT_FREQUENCY = 100  # Commit every N processed results

# File paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SCRATCHPAD_DIR = os.getenv(
    'BATCH_SCRATCHPAD_DIR',
    Path(os.getenv('TEMP', os.getenv('TMP', '/tmp'))) / 'claude' / 'scratchpad' / 'batch'
)

# Ensure scratchpad directory exists
Path(SCRATCHPAD_DIR).mkdir(parents=True, exist_ok=True)

# File naming patterns
INPUT_FILE_PATTERN = "{job_type}_{country}_{date_start}_{date_end}_input.jsonl"
OUTPUT_FILE_PATTERN = "{job_type}_{country}_{date_start}_{date_end}_output.jsonl"
ERROR_FILE_PATTERN = "{job_type}_{country}_{date_start}_{date_end}_errors.jsonl"

# S3 configuration (if using S3 for file storage)
S3_BUCKET_ENV = "S3_BUCKET"
S3_PREFIX_BATCH = "batch_processing/"

# Monitoring configuration
DEFAULT_POLL_INTERVAL = 60  # seconds
MAX_POLL_DURATION = 86400  # 24 hours (OpenAI SLA)

# Retry configuration
MAX_SUBMISSION_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds (exponential backoff: 2s, 4s, 8s)

# Database batch sizes
DB_QUERY_BATCH_SIZE = 1000  # Fetch records in batches of 1000

# Cost estimation defaults
DEFAULT_OUTPUT_TOKENS = 300  # Conservative estimate

# Logging configuration
LOG_LEVEL = os.getenv('BATCH_LOG_LEVEL', 'INFO')


def get_batch_file_path(
    job_type: str,
    file_type: str = 'input',
    country: str = None,
    date_start: str = None,
    date_end: str = None,
    batch_job_id: str = None
) -> str:
    """
    Generate file path for batch processing files.

    Args:
        job_type: Job type (cluster_deconflict, canonical_deconflict, etc.)
        file_type: File type ('input', 'output', 'error')
        country: Country code (optional)
        date_start: Start date (optional)
        date_end: End date (optional)
        batch_job_id: Batch job ID (optional, used for tracking)

    Returns:
        Absolute file path

    Example:
        >>> path = get_batch_file_path('cluster_deconflict', 'input', 'China', '2024-08-01', '2024-08-31')
        >>> print(path)
        '/tmp/claude/scratchpad/batch/cluster_deconflict_China_2024-08-01_2024-08-31_input.jsonl'
    """
    if batch_job_id:
        # Use batch job ID for unique filenames
        filename = f"{job_type}_{batch_job_id}_{file_type}.jsonl"
    else:
        # Use country and date range
        country_str = country or "all"
        date_start_str = date_start or "all"
        date_end_str = date_end or "all"
        filename = f"{job_type}_{country_str}_{date_start_str}_{date_end_str}_{file_type}.jsonl"

    return str(Path(SCRATCHPAD_DIR) / filename)


def get_s3_key(
    job_type: str,
    file_type: str,
    batch_job_id: str
) -> str:
    """
    Generate S3 key for batch processing files.

    Args:
        job_type: Job type
        file_type: File type ('input', 'output', 'error')
        batch_job_id: Batch job ID

    Returns:
        S3 key path

    Example:
        >>> key = get_s3_key('cluster_deconflict', 'output', 'abc-123')
        >>> print(key)
        'batch_processing/cluster_deconflict/outputs/abc-123.jsonl'
    """
    return f"{S3_PREFIX_BATCH}{job_type}/{file_type}s/{batch_job_id}.jsonl"


def validate_job_type(job_type: str) -> bool:
    """
    Validate that job_type is supported.

    Args:
        job_type: Job type to validate

    Returns:
        True if valid, False otherwise
    """
    return job_type in SUPPORTED_JOB_TYPES


def get_model_for_job_type(job_type: str) -> str:
    """
    Get default model for a job type.

    Args:
        job_type: Job type

    Returns:
        Model name

    Raises:
        ValueError: If job_type is not supported
    """
    if not validate_job_type(job_type):
        raise ValueError(f"Unsupported job_type: {job_type}. Supported types: {SUPPORTED_JOB_TYPES}")

    return DEFAULT_MODELS.get(job_type, "gpt-4o-mini")


# Configuration summary for logging
def get_config_summary() -> Dict[str, Any]:
    """
    Get configuration summary for logging/debugging.

    Returns:
        Dictionary with current configuration values
    """
    return {
        'supported_job_types': SUPPORTED_JOB_TYPES,
        'default_models': DEFAULT_MODELS,
        'scratchpad_dir': str(SCRATCHPAD_DIR),
        'max_batch_size': MAX_BATCH_SIZE,
        'recommended_batch_size': RECOMMENDED_BATCH_SIZE,
        'default_poll_interval': DEFAULT_POLL_INTERVAL,
        'max_poll_duration': MAX_POLL_DURATION,
        'max_submission_retries': MAX_SUBMISSION_RETRIES,
        'checkpoint_frequency': DEFAULT_CHECKPOINT_FREQUENCY,
        'log_level': LOG_LEVEL
    }
