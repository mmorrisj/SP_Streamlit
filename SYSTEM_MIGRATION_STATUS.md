# System Migration Status & Remaining Work

**Date:** December 17, 2024
**Objective:** Migrate data from System 1 to System 2 to continue pipeline processing using Azure OpenAI

---

## ✅ COMPLETED EXPORTS (Ready to Transfer)

### 1. Materiality Scores Export
**Location:** `C:\Users\mmorr\Desktop\Apps\SP_Streamlit\materiality_exports`
**Size:** 2.8 MB
**Files:** 3 parquet files

**Contents:**
- **22,235 scored canonical events** across all countries
- Breakdown by country:
  - China: 16,652 scored (84.8% complete)
  - Iran: 2,782 scored (7.1% complete)
  - Russia: 2,764 scored (21.2% complete)
  - Turkey: 37 scored (0.2% complete)

**What's included:**
- Event ID, canonical name, country
- Material score (1-10) and justification
- First/last mention dates
- Primary recipients and categories
- Article counts

### 2. Event Tables Export
**Location:** `C:\Users\mmorr\Desktop\Apps\SP_Streamlit\event_exports`
**Size:** 35 MB
**Files:** 34 parquet files

**Contents:**
- **Event Clusters** (153,873 rows): Raw daily clusters from DBSCAN
  - 16 parquet files (~17.5 MB)
  - Contains event names, doc IDs, cluster metadata
  - All clusters are LLM deconflicted

- **Daily Event Mentions** (140,037 rows): Event-to-document links
  - 15 parquet files (~11 MB)
  - Links canonical events to source documents by date
  - Includes headlines, summaries, sources

- **Event Summaries** (12,227 rows): Period summaries with narratives
  - 2 parquet files (~7 MB)
  - Daily/weekly/monthly/yearly summaries
  - Category breakdowns, document counts, material scores

---

## 📊 WHAT REMAINS TO BE PROCESSED

### Materiality Scoring Status

| Country       | Total Events | Scored  | % Complete | Unscored Remaining |
|---------------|-------------|---------|------------|-------------------|
| China         | 19,645      | 16,652  | 84.8%      | **2,993**         |
| Iran          | 39,308      | 2,782   | 7.1%       | **36,526**        |
| Russia        | 13,013      | 2,764   | 21.2%      | **10,249**        |
| Turkey        | 18,424      | 37      | 0.2%       | **18,387**        |
| United States | 22,120      | 0       | 0%         | **22,120**        |
| **TOTAL**     | **112,510** | **22,235** | **19.8%** | **90,275**     |

### Entity Extraction Status

- **China Entity Extraction:** Batch 4/30 complete (~13,328 docs remaining)
- **Other Countries:** Not yet started

### Background Processes (System 1)

Currently running on System 1:
1. China materiality scoring (via FastAPI proxy → OpenAI)
2. Iran materiality scoring  (via FastAPI proxy → OpenAI)
3. Russia materiality scoring (via FastAPI proxy → OpenAI)
4. China entity extraction (batch processing)

**Note:** These can continue running on System 1 while System 2 processes other countries.

---

## 🚀 RECOMMENDED WORKFLOW

### Phase 1: Transfer & Import (System 2)

1. **Transfer export directories to System 2:**
   ```bash
   # Copy both directories to System 2
   # materiality_exports/ (2.8 MB)
   # event_exports/ (35 MB)
   ```

2. **Import on System 2:**
   ```bash
   # Import materiality scores
   PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
       --input-dir ./materiality_exports \
       --dry-run  # Test first

   PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/import_materiality_scores.py \
       --input-dir ./materiality_exports  # Actually import

   # Import event tables (similar pattern - import scripts need to be created)
   ```

3. **Verify imports:**
   ```bash
   # Check materiality scores imported correctly
   PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/export_materiality_scores.py --stats-only

   # Check event tables
   PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/export_event_tables.py --stats-only
   ```

### Phase 2: Continue Processing (System 2 using Azure OpenAI)

**Materiality Scoring Priority:**
```bash
# 1. Iran (largest backlog - 36,526 events)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country Iran --source azure

# 2. United States (fresh start - 22,120 events)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country "United States" --source azure

# 3. Turkey (18,387 events)
PYTHONPATH=/path/to/SP_Streamlit python services/pipeline/events/score_canonical_event_materiality.py \
    --country Turkey --source azure
```

**Note:** Let System 1 finish China (2,993 remaining) and Russia (10,249 remaining) via OpenAI proxy while System 2 handles the larger backlogs.

### Phase 3: Parallel Processing Strategy

**System 1 (OpenAI via FastAPI Proxy):**
- Continue China materiality (2,993 remaining)
- Continue Russia materiality (10,249 remaining)
- Continue China entity extraction

**System 2 (Azure OpenAI):**
- Iran materiality (36,526 events - **HIGHEST PRIORITY**)
- United States materiality (22,120 events)
- Turkey materiality (18,387 events)

**Total estimated time:**
- System 1: ~13k events ÷ ~100 events/hour = ~130 hours (~5-6 days)
- System 2: ~77k events ÷ ~100 events/hour = ~770 hours (~32 days single-threaded)
- **With 3 parallel processes on System 2:** ~11 days

---

## 📋 REQUIRED SCRIPTS FOR SYSTEM 2

### Already Created:
✅ `export_materiality_scores.py` - Export materiality scores
✅ `import_materiality_scores.py` - Import materiality scores
✅ `export_event_tables.py` - Export event clusters/mentions/summaries
✅ `test_azure_connection.ipynb` - Test Azure OpenAI connection
✅ Updated `gai()` function in `shared/utils/utils.py` with Azure support

### Still Needed:
❌ `import_event_tables.py` - Import event clusters/mentions/summaries
❌ Update `score_canonical_event_materiality.py` to support `--source azure` parameter

---

## 🔍 DATA VERIFICATION CHECKLIST

Before starting production processing on System 2:

- [ ] Test Azure OpenAI connection (`test_azure_connection.ipynb`)
- [ ] Verify AWS Secrets Manager access (boto3 credentials)
- [ ] Import materiality scores and verify counts match
- [ ] Import event tables and verify counts match
- [ ] Run test materiality scoring on 10 events
- [ ] Verify material scores are being saved to database
- [ ] Monitor first 100 events for any errors

---

## 💾 EXPORT FILE STRUCTURE

### materiality_exports/
```
materiality_scores_20251216_160028_batch0000.parquet  (10,000 events, 1.3 MB)
materiality_scores_20251216_160028_batch0001.parquet  (10,000 events, 1.2 MB)
materiality_scores_20251216_160029_batch0002.parquet   (2,235 events, 0.3 MB)
```

### event_exports/
```
event_clusters_20251217_193347_batch0000.parquet through batch0015.parquet  (153,873 total)
daily_event_mentions_20251217_193358_batch0000.parquet through batch0014.parquet  (140,037 total)
event_summaries_20251217_193445_batch0000.parquet through batch0001.parquet  (12,227 total)
```

---

## 📊 PROGRESS METRICS

**Overall Pipeline Completion:**
- Documents ingested: ✅ Complete
- Event clustering: ✅ Complete (153,873 clusters)
- LLM deconfliction: ✅ Complete
- Canonical events created: ✅ Complete (112,510 events)
- Materiality scoring: 🔄 **19.8% complete** (22,235 / 112,510)
- Event summaries: ✅ Complete (12,227 summaries)
- Entity extraction: 🔄 In progress (China only, batch 4/30)

**Critical Path Forward:**
1. ✅ Export data from System 1 → **DONE**
2. 🔄 Transfer to System 2 → **READY**
3. 🔄 Import on System 2 → **NEXT STEP**
4. 🔄 Score remaining 90,275 events → **Main workload**
5. 🔄 Complete entity extraction for all countries

---

## 🎯 IMMEDIATE NEXT STEPS

1. **Transfer exports to System 2** (38 MB total)
2. **Test Azure OpenAI connection** on System 2
3. **Import materiality scores** (22,235 events)
4. **Import event tables** (306,137 total rows)
5. **Start Iran materiality scoring** (highest priority - 36,526 events)
6. **Monitor and verify** first few batches for accuracy

---

## 📝 NOTES

- All exports use zstd compression for optimal file size
- UUID fields converted to strings for parquet compatibility
- JSONB fields converted to JSON strings
- Arrays converted to JSON strings where needed
- All timestamps preserved for audit trail
- Exports are incremental-safe (can be re-run without duplicates via import logic)
