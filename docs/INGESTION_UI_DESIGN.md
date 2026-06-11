# Ingestion UI — Pipeline Review & Design Proposal

**Goal:** Replace terminal-driven ingestion with a web interface where users drop in a
`results.json` (DSR extract) or `atom.csv` file, review what will be ingested, run the
pipeline, and watch progress — with a persistent history of every ingestion run.

---

## Part 1: Review of the current ingestion pipeline

### 1.1 The `results.json` (DSR) path — complete and DB-connected

`services/pipeline/ingestion/dsr.py` is the production path. Flow:

```
results.json (S3 dsr_extracts/ or local ./data)
   └─> load_dsr / load_dsr_from_s3      # JSON tracker file in S3 prevents re-processing
   └─> parse_doc()                      # maps DSR schema → Document model
   │     • requires auto.gai[1] (pre-computed LLM analysis) — docs without it are skipped
   │     • event-name > project-name > projects fallback consolidation
   │     • normalizes "n/a"/"none"/empty → None
   └─> per-document duplicate check against Postgres
   │     • existing docs: skipped, but relationships re-flattened
   └─> batch insert (100/batch) → flatten_all_relationships()
   │     • categories, subcategories, initiating/recipient countries, raw_events
   │     • row-by-row INSERT ... ON CONFLICT DO NOTHING
   └─> embed_documents_direct()         # in-process, 50/batch, requires distilled_text
```

CLI supports `--status`, `--no-embed`, `--s3-files`, `--reprocess`, batch-size tuning.

**Strengths:** idempotent (duplicate checks + ON CONFLICT), batched commits, S3 tracker,
schema-evolution handling in `parse_doc`, clear two-step load-then-embed separation.

**Gaps that matter for a UI:**

| Gap | Detail |
|---|---|
| No run records | Results exist only as console prints. `BatchJob` in `shared/models/models.py` tracks only OpenAI deconfliction jobs, not ingestion. |
| No progress hooks | All feedback is `print()`. Nothing a UI can poll or stream. |
| No dry-run / validation mode | There is no way to answer "what would this file do?" without committing. |
| Synchronous, in-process | A large file blocks the caller for minutes-to-hours (embeddings). No cancellation. |
| N+1 duplicate check | One `SELECT` per document (`dsr.py` `process_dsr`); should be one `IN (...)` query per batch. |
| Row-by-row flatten inserts | `flatten_all_relationships` executes one INSERT per relationship row; should use `executemany`. |
| Error capture | Parse errors are printed and dropped — no record of *which* doc IDs failed or why. |

### 1.2 The `atom.csv` path — legacy and currently broken

The atom path never reaches the production Postgres database:

- **`services/pipeline/ingestion/atom.py`** only cleans CSV → XLSX into a `processed/`
  folder. It has a **blocking bug**: the function signature
  `def process_atom_files(directory='./backend/atom', output_directory=os.path.join(directory,'processed'), ...)`
  evaluates `os.path.join(directory, ...)` at definition time, where `directory` is
  undefined → `NameError` the moment the module is imported. It also references the
  pre-reorg `./backend/atom` path, which no longer exists.
- **`services/pipeline/analysis/atom_extraction.py`** is pre-migration code: it reads
  from/writes to a hardcoded SQLite DB (`./kuwait/kuwait_sp.db`), creates an Azure
  OpenAI client **at import time** (requires AWS Secrets Manager access just to import),
  checkpoints results to a local JSON file, and never touches Postgres or
  `shared/models/models.py`.

**Implication:** the `results.json` path can be wired into a UI with a modest refactor;
the `atom.csv` path needs modernization first (Postgres-backed, shared LLM config,
ideally the OpenAI Batch API since extraction costs money per document). The UI design
below accounts for both, but recommends shipping `results.json` first.

### 1.3 Existing infrastructure the UI can build on

- **React client** (`client/`): React Router v7, TanStack Query + axios (`api/client.ts`),
  custom CSS, Lucide icons, Sonner toasts, JWT auth with `VIEWER`/`ANALYST`/`ADMIN` roles.
  No upload page exists today.
- **FastAPI server** (`server/main.py`): serves the React app, has S3 proxy and OpenAI
  `/batch/*` endpoints, runs an in-process alert scheduler (precedent for background
  work). No ingestion endpoint exists today.
- **`BatchJob` model**: a good template for an ingestion job table (status enum,
  progress JSONB, file paths, cost fields).
- **Redis** is in the compose stack but unused — the natural upgrade path for a real
  task queue (Celery/RQ) if in-process background tasks prove insufficient.

---

## Part 2: UI design proposal

### 2.1 Where it lives

A new React page **`/ingestion` → `client/src/pages/DataIngestionPage.tsx`**, restricted
to `ANALYST`/`ADMIN` roles, added to the main nav. The React app is the primary UI and
already has auth, roles, query/toast infrastructure, and an axios client.

*(Alternative considered: a Streamlit `00_Data_Ingestion` page would be faster to build
but has no role gating, no real upload→background-job UX, and the dashboard is positioned
as analytics, not administration. Not recommended.)*

### 2.2 User flow — a 4-step wizard plus a history tab

```
┌──────────────────────────────────────────────────────────────────┐
│  Data Ingestion                                [New Run] [History]│
├──────────────────────────────────────────────────────────────────┤
│  ① Upload ─── ② Review ─── ③ Configure ─── ④ Run & Results       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │        ⬇  Drag & drop results.json or atom.csv             │  │
│  │           or click to browse                               │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│  Detected: DSR results.json · 4.2 MB · ~1,830 documents          │
└──────────────────────────────────────────────────────────────────┘
```

**Step 1 — Upload.** Drag-and-drop zone accepting `.json` and `.csv`. The client guesses
type by extension; the server confirms by sniffing structure (DSR: list of doc arrays
containing `auto.gai`; atom: CSV with `Title`/`Body`/`Collection Name` columns). The file
is streamed to the server, staged to S3 (`uploads/` prefix), and an `IngestionJob` row is
created in `UPLOADED` status. Wrong/ambiguous structure → immediate, specific error
("This JSON has no `auto.gai` analysis block — is this a raw export rather than a DSR
extract?").

**Step 2 — Review (dry-run validation).** The server parses the file *without writing
documents* and returns a validation report the user reviews before committing anything:

- **Summary cards:** total docs · parseable · **new** vs **already in DB** (single
  `WHERE doc_id IN (...)` query) · parse errors
- **Distributions:** date range, collections, top initiating/recipient countries —
  a cheap sanity check that the user uploaded the file they think they did
- **Warnings:** docs with all event fields empty, docs missing `distilled_text`
  (won't be embeddable), CSV encoding fallback used, within-file duplicates
- **Sample table:** first ~20 parsed documents (title, date, source, countries, category)
- **Errors table:** doc ID + reason for every unparseable record, downloadable as CSV

Cancel here = nothing was written; the staged file and job row are marked `CANCELLED`.

**Step 3 — Configure.** A small options panel (defaults match current CLI behavior):

- ☑ Generate embeddings now *(uncheck to defer — mirrors `--no-embed`)*
- ☐ Re-flatten relationships for duplicate documents *(current behavior for existing docs)*
- ▸ Advanced (collapsed): doc batch size (100), embed batch size (50)
- *Atom flow only:* ☑ Run LLM soft-power extraction — shows doc count and **estimated
  cost** with an explicit confirm, since this calls a paid model per document

**Step 4 — Run & Results.** Start moves the job to background execution; the UI shows a
staged progress tracker driven by polling `GET /api/ingestion/jobs/{id}` every ~2s
(React Query `refetchInterval`):

```
  ✓ Parse        1,830 / 1,830
  ✓ Load           1,795 new · 31 duplicates · 4 errors
  ● Flatten       categories 3,210 · countries 3,544 · events 2,101
  ○ Embed          0 / 1,795
  ───────────────────────────────────────────────
  [ live log tail — last 15 lines ]            [Cancel]
```

On completion: summary cards (loaded / skipped / errors / embedded), **Download error
report** (CSV of doc_id + reason), **View ingested documents** (deep link into the
Documents page filtered by this job's batch ID), and suggested next steps ("New documents
span China → Egypt, 2024-08-01 to 2024-08-14 — run event clustering for this range"),
which can later become one-click pipeline triggers.

**History tab.** Table of all `IngestionJob` rows: file name, type, who, when, status,
counts, duration — with per-row actions (view report, download errors, re-run embeddings,
reprocess). This replaces the opaque S3 tracker JSON as the system of record and gives
the team an audit trail for the first time.

### 2.3 Backend design

**New model** (Alembic migration), modeled on the existing `BatchJob`:

```python
class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id            # UUID pk
    filename, file_type            # 'dsr_json' | 'atom_csv'
    s3_key                         # staged upload location
    status        # UPLOADED → VALIDATING → READY → LOADING → FLATTENING
                  #   → EMBEDDING → COMPLETED | COMPLETED_WITH_ERRORS
                  #   | FAILED | CANCELLED
    options       # JSONB: embed_now, reflatten_duplicates, batch sizes
    validation_report  # JSONB: counts, distributions, warnings, sample
    progress      # JSONB: per-stage counters, updated each batch
    error_log     # JSONB (or S3 key for large logs): [{doc_id, stage, reason}]
    created_by, created_at, started_at, finished_at
    cancel_requested   # bool — checked between batches for cooperative cancel
```

**New endpoints** (suggest a dedicated router, `server/routers/ingestion.py`):

| Endpoint | Purpose |
|---|---|
| `POST /api/ingestion/upload` | Multipart upload → stage to S3, create job, kick off validation in background |
| `GET  /api/ingestion/jobs` | History list (paginated) |
| `GET  /api/ingestion/jobs/{id}` | Status + progress + validation report (the polling target) |
| `POST /api/ingestion/jobs/{id}/start` | Begin processing with chosen options |
| `POST /api/ingestion/jobs/{id}/cancel` | Set `cancel_requested`; worker stops at next batch boundary |
| `GET  /api/ingestion/jobs/{id}/errors` | Error report as CSV download |

**Execution model — phase 1: FastAPI `BackgroundTasks`.** The codebase already runs the
alert scheduler in-process, files arrive one at a time, and batch boundaries give natural
checkpoints for progress writes and cancellation. The worker uses its own DB session and
updates the job row after every batch, so polling always has fresh counts. **Phase 2:**
if concurrent ingestions or very large files become routine, move the same worker
function onto Celery/RQ using the Redis already in the compose stack — the job table and
API don't change, only the dispatch mechanism.

**Pipeline refactor (modest, and worth doing regardless of the UI):**

1. Extract `dsr.py`'s parse/load/flatten/embed into functions that accept a
   `progress_cb(stage, counters)` and a cancellation check, so CLI and API share one code
   path (CLI passes a print-based callback — current behavior preserved).
2. Add `validate_dsr(parsed_docs) -> ValidationReport` — runs `parse_doc` over everything,
   collects errors/warnings, does **one** `IN (...)` duplicate query. This is the dry-run
   the Review step needs and also fixes the N+1 existence checks in the real load.
3. Batch the `flatten_all_relationships` inserts with `executemany` instead of one
   `session.execute` per row.
4. Capture per-document errors as structured records `(doc_id, stage, reason)` instead of
   prints.

### 2.4 The atom.csv path: scope recommendation

**Ship `results.json` first (V1).** It is the only path that reaches Postgres, and the
refactor needed is small. In V1, the drop zone still *accepts* `.csv` and runs cleaning +
validation (preview of rows, dedupe-by-title counts, encoding warnings), but the run step
is gated "LLM extraction coming soon" — users still get value from the validation report.

**V2 — modernize the atom flow** so the UI can run it end-to-end:

```
atom.csv → clean (port atom.py logic, fix paths/bugs)
        → LLM soft-power extraction (rewrite atom_extraction.py: shared config/creds,
          OpenAI Batch API for cost + resilience, results → Postgres via the existing
          BatchJob pattern)
        → emit DSR-shaped records → reuse the exact same load/flatten/embed pipeline
```

Funneling atom output into the same loader keeps one ingestion code path and gives atom
files the same dedupe/flatten/embed behavior for free. Because extraction is paid and
slow, the UI treats it as an explicitly confirmed sub-job with its own cost estimate and
progress stage (the `/batch/*` endpoints and `BatchJob` table already exist for this).

### 2.5 Phased delivery

| Phase | Scope |
|---|---|
| **1** | `IngestionJob` model + migration · refactor `dsr.py` (callbacks, dry-run, batched queries) · upload/validate/start/status/cancel endpoints · React wizard + history page · polling progress |
| **2** | Error-report download · retry / re-run embeddings from history · CSV validation preview for atom files · SSE upgrade for progress (optional — polling is fine) |
| **3** | Atom modernization (clean → Batch-API extraction → shared loader) with cost-confirm gate · one-click downstream triggers (event clustering for affected country/date range) |

### 2.6 Bugs found during review (worth fixing independently)

1. `atom.py:27-28` — default argument `output_directory=os.path.join(directory, 'processed')`
   raises `NameError` at import time (`directory` isn't defined when defaults evaluate).
2. `atom.py` / `atom_extraction.py` — hardcoded pre-reorg `./backend/atom` paths.
3. `atom_extraction.py:60` — Secrets Manager fetch + Azure client construction at module
   import; any import without AWS credentials crashes.
4. `dsr.py` `process_dsr` / `process_dsr_s3` — per-document existence `SELECT` (N+1).
5. `dsr.py` `flatten_all_relationships` — one `execute` per relationship row.
