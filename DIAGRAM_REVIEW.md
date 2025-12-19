# Diagram Review and Recommendations

## Overall Assessment

The three diagrams are **well-structured and comprehensive**. They accurately represent the pipeline architecture, publication workflow, and GAI interactions. Below are specific errors found and recommendations for additions.

---

## 1. Pipeline Flowchart Review

### ✅ CORRECT Elements

1. **Two-Stage Event Processing** - Correctly shown as separate stages:
   - Stage 2A/2B: Daily clustering + deconfliction
   - Stage 3A/3B/3C: Batch consolidation across dates

2. **DBSCAN eps value** - Shows `eps=0.15` (line 72) ✅ CORRECT (varies by country, but 0.15 is used)

3. **Table names** - All use correct `documents` table (no `softpower_documents` errors)

4. **Script names** - All accurate and match actual file paths

5. **Technology stack** - Correctly mentions Azure OpenAI, DBSCAN, sentence-transformers, pgvector

6. **Master event hierarchy** - Correctly shows `master_event_id IS NULL` for master events

### ❌ ERRORS TO FIX

#### Error 1: Missing `raw_events` Table Linkage
**Location**: Stage 0 - Document Ingestion (line 48-50)

**Issue**: Shows `raw_events` table is created during ingestion, but doesn't clarify that:
- `raw_events` is a many-to-many relationship table
- Contains `doc_id` + `event_name` pairs
- Maintains linkage between documents and their extracted event names

**Fix**: Add annotation showing `raw_events (doc_id, event_name)` with linkage arrow to documents

#### Error 2: Missing `subcategories` and `recipient_countries` Tables
**Location**: Stage 0 tables (line 36-50)

**Issue**: Only shows 4 tables, but 6 relationship tables are created:
- ✅ `documents`
- ✅ `categories`
- ❌ Missing: `subcategories`
- ✅ `initiating_countries`
- ❌ Missing: `recipient_countries`
- ✅ `raw_events`

**Fix**: Add `subcategories` and `recipient_countries` cylinder icons to the Stage 0 tables section

#### Error 3: Embeddings Stage Missing Critical Detail
**Location**: Stage 4 - Embeddings Management (line 133-156)

**Issue**: Doesn't mention the **backup/restore capability** which saves ~45 hours of regeneration time during migrations

**Current**: Shows basic embed/export/import scripts
**Missing**:
- S3 backup location (`morris-sp-bucket/embeddings/`)
- Time savings (45 hours regeneration vs 15-20 min restore)
- Idempotent import with progress tracking

**Fix**: Add annotation box showing:
```
⚠️ CRITICAL MIGRATION FEATURE
• Export saves ~45 hours regeneration time
• S3 bucket: morris-sp-bucket/embeddings/
• Idempotent import with progress tracking
• See: LINKAGE_VERIFICATION.md
```

#### Error 4: Materiality Scoring Progress Not Shown
**Location**: Optional Materiality Scoring (line 125-131)

**Issue**: Shows as "OPTIONAL" but doesn't indicate current progress state

**Current**: Dashed box labeled "OPTIONAL"
**Reality**: Active ongoing process with specific progress:
- China: 84.8% complete (2,993 remaining)
- Russia: 21.2% complete (10,249 remaining)
- Iran: 7.1% complete (36,526 remaining)
- **Total**: 19.8% complete (22,235 / 112,510 scored)

**Fix**: Add progress annotation or change label to:
```
MATERIALITY SCORING (IN PROGRESS)
19.8% Complete (22,235 / 112,510 events)
Next: Iran on System 2 (Azure OpenAI)
```

#### Error 5: Entity Extraction Status Not Shown
**Location**: Missing entirely from main pipeline flow

**Issue**: Entity extraction is actively running (China batch 4/30 remaining ~87%) but not shown in the diagram

**Fix**: Add new stage before or after materiality scoring:
```
STAGE 6: ENTITY EXTRACTION (OPTIONAL)
services/pipeline/analysis/batch_entity_extraction.py
• Extract people, organizations, locations
• Store in canonical_events.entities (JSONB)
• Status: China 87% complete
```

### 📋 RECOMMENDED ADDITIONS

#### Addition 1: Data Linkage Traceability Diagram
**Purpose**: Show complete end-to-end traceability

**Suggested location**: Bottom right corner or separate inset box

**Content**:
```
COMPLETE DATA TRACEABILITY:

Raw Document (S3 JSON)
    ↓ doc_id
documents table
    ↑ (doc_id FK)
categories, subcategories, countries, raw_events
    ↑ (aggregated)
event_clusters (doc_ids[] array)
    ↑ (consolidated)
canonical_events
    ↑ (canonical_event_id FK)
daily_event_mentions (doc_ids[] array)
    ↑ (summarized)
event_summaries

Result: ANY event can be traced to original source documents
```

#### Addition 2: Row Counts for Each Table
**Purpose**: Show scale of data at each stage

**Suggested**: Add small text under each table cylinder showing row count

**Examples**:
- `documents`: 496,783 rows
- `categories`: 648,408 rows
- `event_clusters`: 153,873 rows
- `canonical_events`: 112,510 rows
- `daily_event_mentions`: 140,037 rows (99.99% with doc_ids)
- `event_summaries`: 12,227 rows

#### Addition 3: Model Information
**Location**: Key Technologies box (line 348-350)

**Current**: Mentions "Azure OpenAI (gpt-4o-mini)"
**Add**:
```
KEY TECHNOLOGIES

• Azure OpenAI / OpenAI API
  - Model: gpt-4o-mini (primary)
  - Fallback: gpt-4o
  - Access: CLAUDE_KEY environment variable
• DBSCAN: Event clustering (eps varies by country)
• sentence-transformers: all-MiniLM-L6-v2 (768-dim embeddings)
• PostgreSQL + pgvector: Vector storage & search
• Streamlit: Interactive dashboard
• Parquet + zstd: Export/import format
```

#### Addition 4: Database Migration Flow
**Purpose**: Show System 1 → System 2 migration process

**Suggested**: Add separate swim lane at bottom showing:
```
FULL DATABASE MIGRATION (System 1 → System 2)

export_full_database.py
    ↓
175 parquet files (4.6M rows, 1.17 GB)
    ↓
Transfer (network/USB/cloud)
    ↓
import_full_database.py
    ├─> ON CONFLICT DO NOTHING (idempotent)
    ├─> Preserves ALL linkages
    └─> Dependency-order import
    ↓
System 2 (exact replica)
```

---

## 2. Summary Publication Flowchart Review

### ✅ CORRECT Elements

1. **Input parameters** - Correctly shows initiating country and date range
2. **Config.yaml reference** - Accurate list of influencers and recipients
3. **Database tables** - All correct table names (documents, canonical_events, daily_event_mentions, etc.)
4. **Soft power categories** - Accurate (Economic, Diplomacy, Social, Military)
5. **Scoring formula** - Correctly shows combined score with article count, recency, and material score
6. **AP Style rules** - Accurate journalism guidelines
7. **Output structure** - Comprehensive 8-section publication format

### ❌ ERRORS TO FIX

#### Error 1: Material Score Scale Mislabeled
**Location**: Step 2 - Key Event Scoring (line 63-66)

**Issue**: Shows "Material Relevance Score" but doesn't clarify that this score is NOT automatically generated

**Current**: "material_score from canonical_events (1-10)"
**Reality**:
- Only 19.8% of events have material_score (22,235 / 112,510)
- Score requires manual LLM processing via `score_canonical_event_materiality.py`
- Not all events will be scored

**Fix**: Add note:
```
3. Material Relevance Score (OPTIONAL)
   material_score from canonical_events (1-10)
   ⚠️ Only 19.8% of events currently scored
   Requires: score_canonical_event_materiality.py
```

#### Error 2: Missing Data Integrity Caveat
**Location**: Step 1 - Data Filtering (line 35-50)

**Issue**: Doesn't mention known data integrity issue

**Current**: Shows filtering without caveats
**Reality**: 8 out of 140,037 daily_event_mentions lack doc_ids (0.006%)

**Fix**: Add footnote:
```
⚠️ DATA INTEGRITY NOTE:
99.99% of events have source doc linkages
8 events missing doc_ids (Iran: 6, Turkey: 1, Duplicates: 1)
See: verify_data_linkage.py for details
```

### 📋 RECOMMENDED ADDITIONS

#### Addition 1: Publication Format Options
**Location**: Final Output section (line 151-157)

**Current**: Shows publication structure but not output format

**Add**:
```
OUTPUT FORMATS:
• HTML (web dashboard)
• PDF (downloadable report)
• Markdown (source format)
• JSON (API consumption)

Storage: services/publication/
Templates: services/publication/templates/
```

#### Addition 2: Refresh Frequency
**Location**: Input Parameters section

**Add box showing**:
```
PUBLICATION FREQUENCY:
• Daily: Generated each day at EOD
• Weekly: Generated Monday (prior week)
• Monthly: Generated 1st of month
• On-demand: Via CLI or dashboard trigger
```

#### Addition 3: Bilateral Summary Regeneration Logic
**Location**: Step 4 - Bilateral Recipient Check (line 91-103)

**Current**: Shows bilateral check but not update logic

**Add**:
```
UPDATE LOGIC:
• Check existing bilateral_relationship_summaries
• IF new high-material events OR >20% article increase:
    → Flag for regeneration
    → Run generate_bilateral_summaries.py --regenerate
• ELSE:
    → Use existing summary, append "New Developments" section
```

---

## 3. GAI Prompt Interactions Flowchart Review

### ✅ CORRECT Elements

1. **gai() function signature** - Accurate (line 20-24)
2. **Source options** - Correct ('proxy', 'azure', 'openai')
3. **Prompt file locations** - All accurate:
   - `shared/utils/prompts.py`
   - `shared/utils/prompts_entity.py`
   - `services/pipeline/summaries/summary_prompts.py`
4. **All 10 GAI interaction categories** - Comprehensive coverage
5. **JSON output structures** - Accurate for all interactions
6. **Material score scale** - Correct (1-3 symbolic, 4-6 mixed, 7-10 substantive)
7. **Entity types and labels** - Accurate taxonomy
8. **AP Style rules** - Correct journalism guidelines
9. **Summary hierarchy** - Correct flow (daily → weekly → monthly → yearly)

### ❌ ERRORS TO FIX

#### Error 1: Model Name Inconsistency
**Location**: Subtitle and KEY INFO (line 12, 312-313)

**Issue**: Shows only `gpt-4o-mini` but system uses multiple models

**Current**: "Model: gpt-4o-mini via Azure OpenAI"
**Reality**:
- Primary: `gpt-4o-mini` (default for most operations)
- Fallback: `gpt-4o` (for complex reasoning or when mini fails)
- System 2 uses Azure OpenAI endpoints
- System 1 can use proxy (FastAPI → OpenAI) or direct

**Fix**: Update subtitle to:
```
Models: gpt-4o-mini (primary), gpt-4o (fallback)
Backend: Azure OpenAI (System 2) | Proxy/Direct (System 1)
Function: gai() in shared/utils/utils.py
```

#### Error 2: Extraction Fields Count
**Location**: Category 1 - Full Metadata Extraction (line 86-88)

**Issue**: Shows "12 fields" but actually extracts more

**Current**: "12. event-name" (line 97)
**Reality**: The extraction actually produces these fields in the documents table:
1. salience_justification
2. salience_bool
3. category
4. category_justification
5. subcategory
6. initiating_country (can be multiple)
7. recipient_country (can be multiple)
8. project_name (optional)
9. LAT_LONG (optional)
10. location (optional)
11. monetary_commitment (optional)
12. distilled_text
13. event_name (can be multiple)

But many are stored in relationship tables, not as single fields. The diagram is simplified.

**Fix**: Clarify:
```
Extracted Fields (12 core + relationships):
1-2. Salience (justification + boolean)
3-5. Category classification
6-7. Countries (stored in relationship tables)
8-11. Optional metadata (projects, locations, amounts)
12-13. Distilled text + event names

Result: Updates documents + populates 6 relationship tables
```

#### Error 3: Missing Cluster Deconfliction Batch Size
**Location**: Category 2 - Cluster Deconfliction (line 99-116)

**Issue**: Doesn't mention processing constraints

**Current**: Shows validation process but not batch size

**Reality**:
- Processes clusters in batches (typically 20-50 clusters per batch)
- Each cluster can contain 2-50 events
- LLM processes each cluster individually

**Fix**: Add note:
```
Processing:
• Batched processing (20-50 clusters)
• Each cluster: 2-50 event names
• Chain-of-thought reasoning for each group
• Confidence threshold: 0.8 (typical)
```

#### Error 4: Materiality Scoring Progress Not Shown
**Location**: Category 3 - Materiality Scoring (line 138-158)

**Issue**: Shows as general process but doesn't indicate it's actively in progress

**Fix**: Add status box:
```
CURRENT STATUS:
Total events: 112,510
Scored: 22,235 (19.8%)
Remaining: 90,275 (80.2%)

By Country:
• China: 84.8% complete
• Russia: 21.2% complete
• Iran: 7.1% complete

Next: Iran materiality on System 2 (Azure)
```

### 📋 RECOMMENDED ADDITIONS

#### Addition 1: Error Handling and Retries
**Location**: GAI Function Core section (line 16-28)

**Add box showing**:
```
ERROR HANDLING:
• Automatic retry on rate limits (3 attempts)
• Exponential backoff (1s, 2s, 4s)
• Fallback to gpt-4o on parsing failures
• Logging: All prompts + responses tracked
• Cost tracking: Token usage per interaction
```

#### Addition 2: Token Usage Estimates
**Location**: GAI Interaction Summary (line 309-314)

**Add**:
```
TYPICAL TOKEN USAGE:
Document Extraction: ~2,000-4,000 tokens
Cluster Deconfliction: ~1,500-3,000 tokens
Materiality Scoring: ~1,000-2,000 tokens
Entity Extraction: ~1,500-2,500 tokens
Daily Summary: ~800-1,500 tokens
Bilateral Summary: ~3,000-5,000 tokens

Total processing cost estimate:
~$0.0001-0.0005 per document (full pipeline)
```

#### Addition 3: Prompt Engineering Best Practices
**Location**: Near prompts-box section

**Add annotation**:
```
PROMPT DESIGN PRINCIPLES:
✅ Chain-of-thought reasoning
✅ Structured JSON output (with schemas)
✅ Few-shot examples when needed
✅ Clear role definition in system prompts
✅ Explicit instructions (DO/DON'T lists)
✅ Attribution requirements (AP Style)
```

#### Addition 4: Quality Control Mechanisms
**Location**: Bottom section

**Add new box**:
```
QUALITY CONTROL:

1. Validation Layers:
   • JSON schema validation (all outputs)
   • Confidence thresholds (deconfliction)
   • Manual review flags (low confidence)

2. Human-in-the-Loop:
   • Materiality scoring: Optional review
   • Cluster splits: Flagged for verification
   • Bilateral summaries: Editorial review

3. Monitoring:
   • Failed parsing rate
   • Retry frequency
   • Average confidence scores
   • Manual override frequency
```

---

## Common Issues Across All Diagrams

### Issue 1: Missing System 1 vs System 2 Context
**Impact**: All three diagrams

**Problem**: Diagrams don't clarify that:
- System 1 (current) has 496,783 documents and partial materiality scores
- System 2 (target) will receive full database migration
- Azure OpenAI configuration differs between systems

**Fix**: Add footer to all diagrams:
```
SYSTEM ARCHITECTURE:
• System 1 (Primary): Full pipeline processing, 496k+ docs
• System 2 (Secondary): Azure OpenAI endpoint, will receive full DB migration
• Migration: export_full_database.py → import_full_database.py (1.17 GB, 175 files)
```

### Issue 2: No Version Control or Update Tracking
**Impact**: All diagrams

**Problem**: No indication of when diagrams were created or last updated

**Fix**: Add metadata footer:
```
Diagram Version: 1.0
Last Updated: 2025-12-19
Based on: CLAUDE.md, PIPELINE_STATUS.md, LINKAGE_VERIFICATION.md
```

### Issue 3: Missing Links to Documentation
**Impact**: All diagrams

**Problem**: No references to detailed documentation

**Fix**: Add reference box:
```
DOCUMENTATION:
📄 CLAUDE.md - Architecture overview
📄 PIPELINE_STATUS.md - Current processing status
📄 LINKAGE_VERIFICATION.md - Data integrity & linkages
📄 FULL_DATABASE_MIGRATION.md - Migration guide
📄 services/pipeline/README.md - Script documentation
```

---

## Summary: Priority Fixes

### HIGH PRIORITY (Fix Immediately):

1. ✅ **Pipeline**: Add missing tables (subcategories, recipient_countries)
2. ✅ **Pipeline**: Add embeddings backup/restore critical note (45-hour savings)
3. ✅ **Pipeline**: Update materiality scoring to show progress (19.8%)
4. ✅ **Publication**: Add material score availability caveat (only 19.8% scored)
5. ✅ **GAI**: Update model information to show fallback strategy

### MEDIUM PRIORITY (Enhance Understanding):

6. **Pipeline**: Add data linkage traceability diagram
7. **Pipeline**: Add row counts for all tables
8. **Pipeline**: Add entity extraction stage
9. **Publication**: Add data integrity note (99.99% complete)
10. **GAI**: Add materiality scoring progress status

### LOW PRIORITY (Nice to Have):

11. Add System 1 vs System 2 footer to all diagrams
12. Add documentation references
13. Add version control metadata
14. Add token usage estimates
15. Add quality control mechanisms box

---

## Conclusion

**Overall Grade: A-**

The diagrams are **excellent foundational work** that accurately capture the pipeline architecture, publication workflow, and GAI interactions. The errors found are mostly:
- **Missing supplementary information** (row counts, progress status)
- **Incomplete context** (System 1/2 differences, data integrity caveats)
- **Missing recent updates** (entity extraction, materiality progress)

**None of the errors represent fundamental misunderstandings** of the architecture. The core flows, table names, script paths, and processing logic are all accurate.

**Recommended Action Plan**:
1. Fix the 5 HIGH PRIORITY items immediately
2. Add the MEDIUM PRIORITY enhancements over next iteration
3. Consider LOW PRIORITY items for final polishing

Great work on these diagrams! They will be valuable documentation for understanding the system.
