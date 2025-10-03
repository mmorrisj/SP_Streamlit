# SP_Streamlit

## DSR Document Processing System

This system processes DSR (Document Source Repository) JSON files and loads them into a database with optional embedding generation for vector search capabilities.

### Overview

The DSR processing system supports two data sources:
- **S3 Bucket** (default): Processes JSON files stored in AWS S3
- **Local Directory**: Processes JSON files from local filesystem

### Quick Start

#### S3 Processing (Default)

```bash
# Process all unprocessed files from S3 with embedding
python backend/scripts/dsr.py

# Show processing status
python backend/scripts/dsr.py --status

# Process without embedding
python backend/scripts/dsr.py --no-embed
```

#### Local Processing

```bash
# Process local files with embedding
python backend/scripts/dsr.py --source local

# Process and move files to processed folder
python backend/scripts/dsr.py --source local --relocate
```

### Command Line Options

#### Data Source Options
- `--source {local,s3}`: Data source (default: s3)
- `--s3-prefix PREFIX`: S3 prefix/folder for JSON files (default: dsr_extracts/)

#### S3-Specific Options
- `--s3-files FILE1 FILE2 ...`: Process specific S3 files
- `--reprocess FILE1 FILE2 ...`: Reprocess specific files (removes from processed list first)
- `--status`: Show S3 processing status

#### Local-Specific Options
- `--relocate`: Move processed files to processed folder

#### General Options
- `--doc-batch-size N`: Batch size for document loading (default: 100)
- `--embed-batch-size N`: Batch size for embedding tasks (default: 50)
- `--no-embed`: Skip embedding processing
- `--no-celery`: Use direct embedding instead of Celery workers

### S3 Processing Features

#### Processed Files Tracking
The system maintains a `processed_files.json` tracker in S3 that:
- Tracks which JSON files have been successfully processed
- Prevents duplicate processing of the same files
- Allows selective reprocessing of specific files
- Stores processing metadata and timestamps

#### File Processing Workflow
1. **Discovery**: Lists all JSON files in the S3 bucket prefix
2. **Filtering**: Excludes files already marked as processed
3. **Download**: Downloads and parses JSON files from S3
4. **Processing**: Extracts document data and loads into database
5. **Tracking**: Marks successfully processed files in the tracker
6. **Embedding**: Optionally generates embeddings for vector search

### Usage Examples

#### Basic S3 Processing
```bash
# Process all new files
python backend/scripts/dsr.py

# Check what files are available/processed
python backend/scripts/dsr.py --status
```

#### Targeted Processing
```bash
# Process specific files only
python backend/scripts/dsr.py --s3-files document1.json document2.json

# Reprocess files (useful for testing or data corrections)
python backend/scripts/dsr.py --reprocess document1.json document2.json
```

#### Performance Tuning
```bash
# Large batch processing
python backend/scripts/dsr.py --doc-batch-size 500 --embed-batch-size 100

# Skip embedding for faster loading
python backend/scripts/dsr.py --no-embed
```

### Configuration

The system uses configuration from `backend/scripts/utils.Config` which loads from YAML configuration files.

#### S3 Configuration
- Bucket: `morris-sp-bucket`
- Default prefix: `dsr_extracts/`
- Processed files tracker: `dsr_extracts/processed_files.json`

### Error Handling

- Files containing 'errors' in the filename are automatically skipped
- Processing continues if individual documents fail to parse
- Detailed error logging for troubleshooting
- Automatic retry capabilities for S3 operations

### Database Integration

- Documents are loaded into the `Document` model
- Supports batch processing for performance
- Duplicate detection prevents reloading existing documents
- Optional embedding generation for vector search

### Monitoring and Status

Use the status command to monitor processing:
```bash
python backend/scripts/dsr.py --status
```

This shows:
- Total JSON files in S3
- Number of processed vs unprocessed files
- List of pending files
- Last processing timestamp