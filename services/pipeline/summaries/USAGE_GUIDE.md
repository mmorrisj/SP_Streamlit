# Document-Based Summary Generator - Usage Guide

**Last Updated**: January 2026

## Overview

This generator creates hierarchical summaries with **full source attribution** and is designed for **iterative, resumable processing**.

### Key Features

1. **Resumable Processing** - Automatically resumes from last completed day
2. **JSON Ground Truth** - Each level reads from JSON files, not in-memory
3. **Chunked Processing** - Handles large document days with smart grouping
4. **Full Citation Chains** - Every claim traces back to source documents
5. **Iterative Workflow** - Re-run any level independently

---

## Basic Usage

### Generate Complete Hierarchy (All Levels)

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2
```

**Output Structure**:
```
publications/china_2025_h2/
├── daily/              # One JSON file per day
├── weekly/             # One JSON file per week
├── monthly/            # One JSON file per month
└── overall_*.json      # Single overall summary
```

---

## Resumable Processing

### Resume from Last Day (Automatic)

If the process crashes or you stop it, just re-run the same command:

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2
```

**What happens**:
```
📁 Found 45 existing daily summaries
📅 Latest: 2025-07-15
🔄 Resuming from next day...

  2025-07-16: 12 documents
  2025-07-17: 8 documents
  ...
```

### Force Complete Regeneration

To regenerate everything from scratch:

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --force
```

---

## Iterative Workflow

### 1. Generate Daily Summaries First

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --daily-only
```

**Why**: Review/edit daily JSON files before weekly aggregation

### 2. Generate Weekly from Daily JSON

After reviewing/editing daily summaries:

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-weekly
```

**What happens**:
```
STEP 1: Skipping daily generation (using existing JSON)
STEP 2: Generating Weekly Summaries
📁 Loading daily summaries from publications/china_2025_h2/daily...
✅ Loaded 214 daily summaries

  Week 2025-06-01 to 2025-06-07: 5 days
  Week 2025-06-08 to 2025-06-14: 7 days
  ...
```

### 3. Generate Monthly from Weekly JSON

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-monthly
```

### 4. Generate Overall from Monthly JSON

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-overall
```

---

## Chunked Processing (Large Document Days)

### Automatic Chunking

When a day has >100 documents (default), the system automatically chunks:

```
  2025-08-15:
    ⚠️  Large document set (347 docs) - using chunked processing
    📦 Split into 4 chunks
    Processing chunk 1/4 (100 docs)... ✅
    Processing chunk 2/4 (100 docs)... ✅
    Processing chunk 3/4 (100 docs)... ✅
    Processing chunk 4/4 (47 docs)... ✅
    🔄 Combining 4 chunk summaries...
  347 documents
```

### How Chunking Works

**1. Smart Sorting**
Documents are sorted to keep related content together:
- Primary: Recipient country (Kenya, Egypt, etc.)
- Secondary: Category (Economic, Diplomacy, etc.)
- Tertiary: Salience (highest first)

This ensures documents about the **same event stay in the same chunk**.

**Example**:
```
Chunk 1: All Kenya Economic documents (100 docs)
Chunk 2: Kenya Diplomacy + Egypt Economic (100 docs)
Chunk 3: Egypt Infrastructure + Tanzania Economic (100 docs)
Chunk 4: Remaining documents (47 docs)
```

**2. Map-Reduce Process**
- **Map**: Generate sub-summary for each chunk with citations [1-100], [101-200], etc.
- **Reduce**: LLM combines sub-summaries into cohesive daily summary
- **Citations**: Renumbered globally (chunk 1: [1-100], chunk 2: [101-200], etc.)

**3. Citation Preservation**
Final daily JSON contains all citations from all chunks:
```json
{
  "date": "2025-08-15",
  "summary": "China announced major infrastructure deals [5,108,234]...",
  "citations": [
    {"citation_number": 1, "doc_id": "abc", ...},
    {"citation_number": 2, "doc_id": "def", ...},
    ...
    {"citation_number": 347, "doc_id": "xyz", ...}
  ],
  "metrics": {
    "total_documents": 347,
    "chunks_processed": 4
  }
}
```

---

## Common Workflows

### Workflow 1: Full Generation (One Shot)

For small to medium datasets (<500 total days):

```bash
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2
```

### Workflow 2: Iterative with Review

For quality control:

```bash
# Step 1: Generate dailies (can take hours/days)
python ... --daily-only

# Step 2: Review daily/*.json files, edit if needed

# Step 3: Generate weeklies from reviewed dailies
python ... --from-weekly

# Step 4: Review weekly/*.json files

# Step 5: Generate monthlies
python ... --from-monthly

# Step 6: Review monthly/*.json files

# Step 7: Generate overall
python ... --from-overall
```

### Workflow 3: Resume After Crash

```bash
# Initial run (crashes after processing 100 days)
python ... --country China --start-date 2025-06-01 --end-date 2025-12-31

# Just re-run same command - automatically resumes from day 101
python ... --country China --start-date 2025-06-01 --end-date 2025-12-31
```

### Workflow 4: Regenerate Upper Levels Only

After editing daily summaries, regenerate everything above:

```bash
# Regenerate weekly, monthly, overall from existing daily JSON
python ... --from-weekly
```

---

## Command-Line Arguments

### Required
- `--country` - Country to analyze (e.g., "China", "Russia")
- `--start-date` - Start date (YYYY-MM-DD)
- `--end-date` - End date (YYYY-MM-DD)

### Optional
- `--output-dir` - Output directory (default: `./publications`)
- `--daily-only` - Stop after generating daily summaries
- `--from-weekly` - Skip daily, start from weekly (reads daily JSON)
- `--from-monthly` - Skip daily/weekly, start from monthly (reads weekly JSON)
- `--from-overall` - Skip all, generate only overall (reads monthly JSON)
- `--force` - Force regeneration (ignore existing files)
- `--dry-run` - Show what would be generated without generating
- `--model-daily` - Model for daily/weekly summaries (default: gpt-4o-mini)
- `--model-monthly` - Model for monthly/overall summaries (default: gpt-4o)

---

## Performance Tips

### 1. Use Resumable Processing

Instead of trying to process 6 months in one run:

```bash
# Process June-July
python ... --start-date 2025-06-01 --end-date 2025-07-31

# Then August-September
python ... --start-date 2025-08-01 --end-date 2025-09-30

# Finally combine with --from-weekly
python ... --start-date 2025-06-01 --end-date 2025-12-31 --from-weekly
```

### 2. Parallelize by Country

For multiple countries:

```bash
# Terminal 1
python ... --country China --start-date 2025-06-01 --end-date 2025-12-31

# Terminal 2
python ... --country Russia --start-date 2025-06-01 --end-date 2025-12-31

# Terminal 3
python ... --country "United States" --start-date 2025-06-01 --end-date 2025-12-31
```

### 3. Use Appropriate Models

- **Daily/Weekly**: Use `gpt-4o-mini` (fast, cheap, good enough)
- **Monthly/Overall**: Use `gpt-4o` (higher quality strategic analysis)

```bash
python ... --model-daily gpt-4o-mini --model-monthly gpt-4o
```

---

## Troubleshooting

### Issue: "No daily summaries found"

**Cause**: Trying to run `--from-weekly` without daily summaries

**Solution**: Run without `--from-weekly` first to generate dailies

### Issue: Large document days take too long

**Cause**: Default chunk size (100) may be too large

**Solution**: Currently hardcoded to 100. Consider reducing in code if needed.

### Issue: Want to re-process just one day

**Solution**:
1. Delete that day's JSON file: `rm publications/china_2025_h2/daily/2025-08-15.json`
2. Re-run with that date range: `--start-date 2025-08-15 --end-date 2025-08-15`

### Issue: Citations not appearing in summaries

**Cause**: LLM model may not be following citation instructions

**Solution**: Check a daily summary JSON file. If citations are in the JSON but not in the summary text, the LLM needs stronger prompting (this is model-dependent).

---

## Example: Complete Publication Workflow

```bash
# 1. Generate dailies for China H2 2025
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --daily-only

# Expected output:
# - 214 daily JSON files (one per day in 7 months)
# - Resumes automatically if crashes
# - Large days chunked automatically

# 2. Review daily summaries (optional)
ls ./publications/china_2025_h2/daily/
cat ./publications/china_2025_h2/daily/2025-08-15.json

# 3. Generate weekly summaries from daily JSON
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-weekly

# Expected output:
# - ~30 weekly JSON files
# - Loads all daily summaries from JSON
# - Generates new weekly summaries

# 4. Generate monthly summaries from weekly JSON
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-monthly

# Expected output:
# - 7 monthly JSON files (June through December)
# - Uses GPT-4o for higher quality

# 5. Generate overall summary from monthly JSON
python services/pipeline/summaries/generate_document_based_summaries.py \
    --country China \
    --start-date 2025-06-01 \
    --end-date 2025-12-31 \
    --output-dir ./publications/china_2025_h2 \
    --from-overall

# Expected output:
# - 1 overall JSON file
# - Executive-level strategic assessment
# - Full citation chain preserved

# 6. Final output structure
tree ./publications/china_2025_h2/
# publications/china_2025_h2/
# ├── daily/ (214 files)
# ├── weekly/ (~30 files)
# ├── monthly/ (7 files)
# └── overall_2025-06-01_to_2025-12-31.json
```

---

## Source Attribution

Every summary at every level includes full citation chains. See [README_SOURCE_ATTRIBUTION.md](README_SOURCE_ATTRIBUTION.md) for details on validating claims.

**Quick validation example**:
```bash
# Find a claim in overall summary
cat publications/china_2025_h2/overall_*.json | jq '.summary'

# Trace citation [Month 1] → [Week 2] → [Day 3] → [5] → doc_id
cat publications/china_2025_h2/overall_*.json | jq '.citations[0]'
cat publications/china_2025_h2/monthly/2025-06.json | jq '.citations[1]'
cat publications/china_2025_h2/weekly/2025-06-08_to_2025-06-14.json | jq '.citations[2]'
cat publications/china_2025_h2/daily/2025-06-10.json | jq '.citations[4]'
```

---

**For More Information**:
- Source attribution details: [README_SOURCE_ATTRIBUTION.md](README_SOURCE_ATTRIBUTION.md)
- Script source code: [generate_document_based_summaries.py](generate_document_based_summaries.py)
