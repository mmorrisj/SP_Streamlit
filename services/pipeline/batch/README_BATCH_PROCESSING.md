# OpenAI Batch API Processing Pipeline

Batch processing system for LLM deconfliction tasks in the event processing pipeline. Achieves **50% cost savings** and **10x throughput improvement** over synchronous processing.

## Overview

This system integrates OpenAI's Batch API into the existing event processing pipeline to enable efficient, cost-effective processing of large volumes of LLM requests.

### Benefits

- **50% Cost Reduction**: Batch API pricing is 50% cheaper than sync API
- **10x Throughput**: Parallel processing vs 10-second rate-limited sync calls
- **Backward Compatible**: Existing sync scripts unchanged
- **Resume Capability**: Checkpoint/resume via existing database flags
- **Centralized Tracking**: batch_jobs table provides full visibility

### Architecture

```
Stage 1: PREPARE     → Query database → Generate JSONL input file
Stage 2: SUBMIT      → Upload to OpenAI → Create batch job
Stage 3: MONITOR     → Poll status → Download results when complete
Stage 4: PROCESS     → Parse results → Update database using existing logic
Stage 5: CLEANUP     → Archive files to S3 → Delete OpenAI files
```

## Setup

### 1. Database Migration

Run the Alembic migration to create the batch_jobs table:

```bash
cd c:\Users\mmorr\Desktop\Apps\SP_Streamlit
alembic upgrade head
```

Verify the table exists:

```sql
SELECT * FROM batch_jobs LIMIT 1;
```

### 2. Environment Variables

Ensure these variables are set in your `.env` file:

```bash
# OpenAI API (required)
OPENAI_PROJ_API=sk-...

# S3 (optional, for file archiving)
S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

### 3. Install Dependencies

The batch system uses the OpenAI Python SDK:

```bash
pip install openai>=1.0.0 tiktoken>=0.5.0
```

## Usage

### Quick Start: Cluster Deconfliction

Process event clusters for a specific country and date range:

```bash
# Stage 1: Prepare JSONL input file
python services/pipeline/batch/batch_prepare.py \
    --job-type cluster_deconflict \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31

# Output: Batch Job ID (e.g., 8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c)

# Stage 2: Submit to OpenAI
python services/pipeline/batch/batch_submit.py \
    --batch-job-id 8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c

# Stage 3: Monitor status (will take 10-60 minutes typically)
python services/pipeline/batch/batch_monitor.py \
    --batch-job-id 8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c \
    --auto-download

# Stage 4: Process results into database
python services/pipeline/batch/batch_process_results.py \
    --batch-job-id 8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c

# Stage 5: Cleanup (archive to S3, delete OpenAI files)
python services/pipeline/batch/batch_cleanup.py \
    --batch-job-id 8a3f2b1c-5d6e-4f7a-8b9c-0d1e2f3a4b5c \
    --archive-s3
```

### Canonical Event Deconfliction

Process canonical event groups:

```bash
python services/pipeline/batch/batch_prepare.py \
    --job-type canonical_deconflict \
    --country China \
    --all-unprocessed
```

### Entity Extraction

Extract persons, organizations, companies, and locations from canonical events:

```bash
python services/pipeline/batch/batch_prepare.py \
    --job-type entity_extract \
    --country China \
    --min-articles 3
```

### Materiality Scoring

Score materiality (1.0-10.0) for canonical events:

```bash
python services/pipeline/batch/batch_prepare.py \
    --job-type score_materiality \
    --country China \
    --min-articles 3 \
    --min-days 1
```

### End-to-End Orchestration

Use the orchestrator to run all stages automatically:

```bash
python services/pipeline/batch/batch_runner.py \
    --job-type cluster_deconflict \
    --country China \
    --start-date 2024-08-01 \
    --end-date 2024-08-31 \
    --auto-submit \
    --auto-cleanup
```

## Command Reference

### Stage 1: batch_prepare.py

Generate JSONL input files from unprocessed database records.

```bash
python batch_prepare.py \
    --job-type {cluster_deconflict|canonical_deconflict|entity_extract|score_materiality} \
    [--country COUNTRY] \
    [--start-date YYYY-MM-DD] \
    [--end-date YYYY-MM-DD] \
    [--all-unprocessed] \
    [--min-articles N] \
    [--force] \
    [--min-days N] \
    [--rescore] \
    [--output PATH] \
    [--model MODEL] \
    [--dry-run] \
    [--verbose]
```

**Key Options:**
- `--job-type`: Type of batch job (required): cluster_deconflict, canonical_deconflict, entity_extract, score_materiality
- `--country`: Filter by initiating country
- `--start-date` / `--end-date`: Date range filter
- `--all-unprocessed`: Process all unprocessed records
- `--min-articles`: Minimum articles for entity_extract/score_materiality (default: 3)
- `--force`: Force entity extraction even if already processed
- `--min-days`: Minimum days for score_materiality (default: 1)
- `--rescore`: Rescore events even if already scored
- `--dry-run`: Preview without creating files

**Output:**
- JSONL file in scratchpad directory
- batch_jobs database record with status='preparing'
- Batch Job ID for next stages

### Stage 2: batch_submit.py

Upload JSONL to OpenAI and create batch job.

```bash
python batch_submit.py \
    --batch-job-id UUID \
    [--max-retries 3] \
    [--verbose]
```

**Key Options:**
- `--batch-job-id`: UUID from Stage 1 (required)
- `--max-retries`: Retry attempts on failure (default: 3)

**Output:**
- OpenAI batch ID
- Updates batch_jobs record with openai_batch_id

### Stage 3: batch_monitor.py

Monitor batch status until completion and download results.

```bash
python batch_monitor.py \
    --batch-job-id UUID \
    [--poll-interval 60] \
    [--max-duration 86400] \
    [--auto-download] \
    [--verbose]
```

**Key Options:**
- `--batch-job-id`: UUID from Stage 1 (required)
- `--poll-interval`: Polling interval in seconds (default: 60)
- `--max-duration`: Maximum wait time in seconds (default: 86400 = 24h)
- `--auto-download`: Automatically download results when complete

**Output:**
- Output JSONL file with LLM responses
- Error JSONL file (if any requests failed)
- Updates batch_jobs with output_file_path

### Stage 4: batch_process_results.py

Parse results and update database using existing deconfliction logic.

```bash
python batch_process_results.py \
    --batch-job-id UUID \
    [--checkpoint-frequency 100] \
    [--verbose]
```

**Key Options:**
- `--batch-job-id`: UUID from Stage 1 (required)
- `--checkpoint-frequency`: Commit every N processed results (default: 100)

**Output:**
- Updates EventCluster.llm_deconflicted = True
- Creates CanonicalEvent and DailyEventMention records
- Updates batch_jobs.processed_at

### Stage 5: batch_cleanup.py

Archive files to S3 and delete OpenAI files.

```bash
python batch_cleanup.py \
    --batch-job-id UUID \
    [--archive-s3] \
    [--delete-local] \
    [--verbose]
```

**Key Options:**
- `--batch-job-id`: UUID from Stage 1 (required)
- `--archive-s3`: Archive JSONL files to S3
- `--delete-local`: Delete local JSONL files after archiving

**Output:**
- Archived files in S3 (if --archive-s3)
- Deleted OpenAI files
- Updates batch_jobs.status = 'completed'

## Database Schema

### batch_jobs Table

Tracks OpenAI Batch API jobs through their lifecycle.

```sql
CREATE TABLE batch_jobs (
    id UUID PRIMARY KEY,

    -- Job identification
    job_type VARCHAR(50) NOT NULL,
    openai_batch_id VARCHAR(255),

    -- Processing scope
    initiating_country VARCHAR(100),
    date_range_start DATE,
    date_range_end DATE,
    batch_size INTEGER NOT NULL,

    -- Status tracking
    status VARCHAR(50) NOT NULL,  -- 'preparing', 'submitted', 'in_progress', 'completed', 'failed'
    progress_metadata JSONB,

    -- File tracking
    input_file_path TEXT,
    input_file_id VARCHAR(255),
    output_file_path TEXT,
    output_file_id VARCHAR(255),
    error_file_path TEXT,
    error_file_id VARCHAR(255),

    -- Cost tracking
    estimated_cost NUMERIC(10, 4),
    actual_cost NUMERIC(10, 4),

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    submitted_at TIMESTAMP,
    completed_at TIMESTAMP,
    processed_at TIMESTAMP,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);
```

### Query Examples

```sql
-- List recent batch jobs
SELECT id, job_type, status, batch_size, estimated_cost, created_at
FROM batch_jobs
ORDER BY created_at DESC
LIMIT 10;

-- Get active batches
SELECT id, job_type, openai_batch_id, status, submitted_at
FROM batch_jobs
WHERE status IN ('submitted', 'in_progress')
ORDER BY submitted_at DESC;

-- Calculate total costs
SELECT
    job_type,
    COUNT(*) as total_jobs,
    SUM(batch_size) as total_requests,
    SUM(estimated_cost) as total_estimated_cost,
    SUM(actual_cost) as total_actual_cost
FROM batch_jobs
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY job_type;

-- Check processing progress
SELECT
    id,
    job_type,
    status,
    progress_metadata->>'requests_completed' as completed,
    progress_metadata->>'requests_total' as total,
    progress_metadata->>'requests_failed' as failed
FROM batch_jobs
WHERE status = 'in_progress';
```

## Cost Analysis

### Pricing Comparison

**Synchronous API:**
- gpt-4o-mini: $0.15/1M input tokens, $0.60/1M output tokens

**Batch API (50% discount):**
- gpt-4o-mini: $0.075/1M input tokens, $0.30/1M output tokens

**Example Calculation:**

For 1,000 cluster deconfliction requests:
- Avg input: 500 tokens/request = 500k total input tokens
- Avg output: 300 tokens/request = 300k total output tokens

Sync cost:
- Input: (500k / 1M) × $0.15 = $0.075
- Output: (300k / 1M) × $0.60 = $0.18
- **Total: $0.255**

Batch cost:
- Input: (500k / 1M) × $0.075 = $0.0375
- Output: (300k / 1M) × $0.30 = $0.09
- **Total: $0.1275**

**Savings: $0.1275 (50%)**

### Performance Comparison

**Sync Processing:**
- 10-second rate limit = 6 requests/minute
- 1,000 requests = ~2.8 hours minimum

**Batch Processing:**
- OpenAI processes in parallel
- 1,000 requests typically complete in 10-60 minutes
- **Speedup: ~3-17x**

## Troubleshooting

### Common Issues

#### 1. "Batch job not found"

```bash
# Verify batch_jobs table exists
python -c "from shared.database.database import get_session; from shared.models.models import BatchJob; print('OK')"

# Check if record exists
python -c "from shared.database.database import get_session; from services.pipeline.batch.batch_tracker import BatchJobTracker; \
with get_session() as s: \
    with BatchJobTracker(s) as t: \
        job = t.get_batch_job('YOUR-UUID'); \
        print(f'Found: {job.id if job else None}')"
```

#### 2. "OpenAI API key not found"

```bash
# Check environment variable
echo $OPENAI_PROJ_API  # Linux/macOS
echo %OPENAI_PROJ_API%  # Windows

# Set if missing
export OPENAI_PROJ_API=sk-...  # Linux/macOS
set OPENAI_PROJ_API=sk-...     # Windows
```

#### 3. "File not found"

The batch system uses a scratchpad directory for temporary files. Check the path:

```python
from services.pipeline.batch.batch_config import SCRATCHPAD_DIR
print(f"Scratchpad: {SCRATCHPAD_DIR}")
```

Ensure this directory exists and is writable.

#### 4. Batch stuck in "in_progress"

OpenAI Batch API has a 24-hour completion window. If your batch exceeds this:

```bash
# Check OpenAI dashboard: https://platform.openai.com/batches

# Cancel stuck batch
python -c "from openai import OpenAI; import os; \
client = OpenAI(api_key=os.getenv('OPENAI_PROJ_API')); \
client.batches.cancel('batch_YOUR_OPENAI_ID')"

# Retry with smaller batch size
python batch_prepare.py --job-type cluster_deconflict --country China --start-date 2024-08-01 --end-date 2024-08-07  # Smaller date range
```

### Debug Mode

Enable verbose logging:

```bash
export BATCH_LOG_LEVEL=DEBUG
python batch_prepare.py --verbose ...
```

### Dry Run

Test without making changes:

```bash
python batch_prepare.py --job-type cluster_deconflict --country China --dry-run
```

## Monitoring

### Check Batch Status

```bash
# Via database
python -c "from shared.database.database import get_session; \
from services.pipeline.batch.batch_tracker import BatchJobTracker; \
with get_session() as s: \
    with BatchJobTracker(s) as t: \
        jobs = t.list_batch_jobs(limit=5); \
        for j in jobs: print(f'{j.id}: {j.status.value} - {j.batch_size} requests')"

# Via OpenAI dashboard
# https://platform.openai.com/batches
```

### Track Costs

```bash
python -c "from shared.database.database import get_session; \
from services.pipeline.batch.batch_tracker import BatchJobTracker; \
with get_session() as s: \
    with BatchJobTracker(s) as t: \
        stats = t.get_batch_job_stats(days=30); \
        print(f'Total jobs: {stats[\"total_jobs\"]}'); \
        print(f'Total cost: ${stats[\"total_estimated_cost\"]:.2f}')"
```

## Best Practices

### 1. Batch Size

- **Recommended**: 1,000-10,000 requests per batch
- **Maximum**: 50,000 requests (OpenAI limit)
- **Too small** (<100): Overhead not worth it, use sync
- **Too large** (>20,000): Longer to process, harder to debug

### 2. Date Ranges

Process data in manageable chunks:

```bash
# Good: 1-month batches
for month in 08 09 10 11 12; do
    python batch_prepare.py --country China --start-date 2024-${month}-01 --end-date 2024-${month}-31
done

# Bad: 1-year batch (too large)
python batch_prepare.py --country China --start-date 2024-01-01 --end-date 2024-12-31
```

### 3. Monitoring

- Use `--auto-download` to automate Stage 3
- Check status every 30-60 minutes (don't over-poll)
- OpenAI typically completes within 1-2 hours for <5k requests

### 4. Error Handling

- Always check error JSONL files if failed requests > 0
- Retry failed items with a new batch
- Keep retry_count < 3 (if still failing, investigate root cause)

### 5. Cost Management

- Estimate costs before submission with `--dry-run`
- Track actual costs in batch_jobs table
- Set budget alerts in OpenAI dashboard

## Integration with Existing Pipeline

### Sync vs Batch Decision Tree

```
START: Need to process event clusters?
│
├─ <100 clusters? → Use SYNC (llm_deconflict_clusters.py)
│   └─ Fast enough, not worth batch overhead
│
└─ ≥100 clusters?
    │
    ├─ Urgent (need results <1 hour)? → Use SYNC
    │   └─ Batch takes ~1-2 hours minimum
    │
    └─ Not urgent? → Use BATCH
        └─ 50% cost savings, 10x throughput
```

### Hybrid Approach

Process recent data with sync, historical data with batch:

```bash
# Real-time: sync processing for today
python services/pipeline/events/llm_deconflict_clusters.py --country China --date $(date +%Y-%m-%d)

# Batch: historical backfill for last month
python services/pipeline/batch/batch_prepare.py --country China --start-date 2024-08-01 --end-date 2024-08-31
```

## Support

For issues or questions:
1. Check [OpenAI Batch API docs](https://platform.openai.com/docs/guides/batch)
2. Review troubleshooting section above
3. Check batch_jobs table for error messages
4. Open issue at https://github.com/your-repo/issues

## Changelog

### v1.1.0 (2025-02-02)
- Added support for entity_extract job type (extract persons, organizations, companies, locations)
- Added support for score_materiality job type (score event materiality 1.0-10.0)
- Enhanced batch_prepare.py with --min-articles, --force, --min-days, --rescore parameters
- Updated batch_process_results.py to handle entity extraction and materiality scoring results

### v1.0.0 (2025-02-02)
- Initial implementation
- Support for cluster_deconflict and canonical_deconflict job types
- 5-stage pipeline with checkpoint/resume
- Cost estimation and tracking
- S3 archiving support
