# Enterprise Cutover Runbook — Embedding Fix + Full Rebuild

Repeatable procedure to deploy the embedding fix and rebuild the event/summary/
entity layers on correct vectors in the enterprise environment. Distilled from
the laptop validation run — every step here exists because something bit us.

## Why this is needed

Every `1.8.x` image before **1.8.18** shipped a broken embedding model:
`transformers 5.x` + `sentence-transformers 5.x` silently loaded **random
weights** for `nomic-embed-text-v1.5`, so all embeddings were noise. The enterprise
DB has the same history, so:

- Document/entity embeddings are garbage → retrieval returns near-random results.
- Everything built from embeddings (event clusters, canonical events, entity
  clusters, and the summaries on top of them) is therefore also garbage.

The fix is **1.8.18** (transformers pinned `<5`, `sentence-transformers <4`,
nomic prompt prefixes corrected) plus a **full re-embed + rebuild**.

## Pre-flight

1. **Image** — confirm prod runs `mmorrisj/softpower-analytics:1.8.18` (web app) and
   rebuild the preprocessing image so the baked model is correct:
   ```bash
   docker compose -f docker-compose.preprocessing.yml build
   docker compose -f docker-compose.preprocessing.yml run --rm preprocessing \
     python -m services.pipeline.embeddings.embedding_model_check
   ```
   **Gate:** `cos(load1, load2) = 1.000` and `<All keys matched successfully>`.
   If it's not 1.0, STOP — the model is still loading random weights.

2. **Batch proxy** — `server/main.py` must be running on the host at the port the
   preprocessing container targets (`API_URL=http://host.docker.internal:${API_PORT:-7001}`),
   bound to `0.0.0.0`, with `OPENAI_PROJ_API` + AWS creds in its environment.

3. **batch_jobs table** — `docker compose -f docker-compose.preprocessing.yml run --rm
   preprocessing alembic upgrade head`.

4. **Persistent scratchpad** — the preprocessing compose now mounts a named volume
   at `/app/_data` (`preproc_batch_data`). **Do not run without it** — batch JSONL
   inputs/outputs live there and are lost across `run --rm` containers otherwise
   (this caused unrecoverable "File not found" retries on the laptop).

5. **Know your OpenAI Batch Queue Limit (BQL).** OpenAI dashboard → Limits →
   gpt-4o-mini → "Batch queue limit" (tokens). Each cluster_deconflict batch ≈
   **0.43M enqueued tokens**. Safe concurrency = `floor(BQL / 0.43M)`. Exceeding it
   = HTTP 429 "Enqueued token limit reached" and failed batches. (Tier 3 ≈ 40M ⇒
   ~15–25 is safe.) Set `--max-concurrent` accordingly; default 5 is always safe.

## Procedure

Alias for brevity (enterprise uses the preprocessing stack):
```bash
PRE="docker compose -f docker-compose.preprocessing.yml run --rm preprocessing"
```

### 1. Re-embed entities (384 → 768)
```bash
$PRE python -m services.pipeline.embeddings.reembed_entities --all
```

### 2. Re-embed the document corpus
The existing chunk vectors are random-weight garbage; clear and regenerate.
**Backup the DB first.** Then (counts will differ in prod):
```sql
-- inspect, then clear ONLY the document collection
DELETE FROM langchain_pg_embedding
WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name='chunk_embeddings');
```
```bash
$PRE python services/pipeline/embeddings/embed_missing_documents.py --yes
```
**Gate:** `embedding_sanity` shows `cos(stored, embed_doc) ≈ 1.0`.

### 3. Wipe the embedding-derived layers (clusters keep nothing stale)
```bash
$PRE python services/pipeline/events/wipe_event_tables.py --dry-run     # preview
$PRE python services/pipeline/events/wipe_event_tables.py --yes
$PRE python services/pipeline/entities/wipe_entity_tables.py --dry-run
$PRE python services/pipeline/entities/wipe_entity_tables.py --yes
```
These preserve `documents`, `raw_events`, `raw_entities`, and the (now-correct)
embeddings — they only clear clusters/canonical/mentions/summaries/relationships.

### 4. Run the full pipeline
```bash
$PRE python services/run_ingestion_pipeline.py \
    --start-date <START> --end-date <END> --source local \
    --max-concurrent <BQL/0.43M, e.g. 15>
```
Notes:
- `--stall-timeout` now **defaults to 0** (disabled) — correct for Batch API; do
  not set a small value or OpenAI's slow-but-valid batches get cancelled.
- Runs all stages, all config influencers, scoped to config MENA `recipients`.
- It's a multi-hour-to-multi-day job bounded by your daily token throughput. Run
  it in tmux / nohup. It's resumable and idempotent (skip-existing); on
  interruption, re-run the same command — `batch_prepare` only fills gaps.

### 5. Recover the tail (scattered batch failures are normal, ~2%)
After it finishes, completed-on-OpenAI results can be re-pulled without re-paying:
```bash
for JT in cluster_deconflict canonical_deconflict generate_daily_summary \
          generate_weekly_summary generate_monthly_summary score_summary_materiality \
          daily_entity_extract entity_deconflict event_rename; do
  $PRE python services/pipeline/batch/recover_batch_results.py --job-type "$JT" --days 3
done
```
For batches that genuinely failed (no OpenAI output), delete and re-run the gaps:
```sql
DELETE FROM batch_jobs WHERE status IN ('failed','processing_results');
```
then re-run step 4 (prepare fills only the holes).

## Validate
```bash
$PRE python services/pipeline/diagnostics/validate_rebuild.py
```
**Gate:** 0 FAIL. WARNs for singleton clusters (cluster_size=1, never deconflicted
by design) and a small batch-failure tail are expected. Then confirm retrieval:
```bash
$PRE python -c "from shared.utils.model_cache import get_hf_embeddings; \
from shared.database.database import get_session; from sqlalchemy import text; \
v=get_hf_embeddings().embed_query('China infrastructure projects in Egypt'); \
vec='['+','.join(format(x,'.6f') for x in v)+']'; \
s=get_session().__enter__(); \
print([(round(float(r[0]),3), r[1][:70]) for r in s.execute(text('SELECT 1-(e.embedding<=>cast(:v as vector)) sim,left(e.document,70) d FROM langchain_pg_embedding e JOIN langchain_pg_collection c ON e.collection_id=c.uuid WHERE c.name=:cn ORDER BY e.embedding<=>cast(:v as vector) LIMIT 3'),{'v':vec,'cn':'chunk_embeddings'}).fetchall()])"
```
**Gate:** top hits on-topic with similarity ≥ ~0.5.

## Lessons baked in (so they don't bite again)
| Symptom we hit | Cause | Prevention (now in place) |
|---|---|---|
| Retrieval returns garbage | random nomic weights (transformers 5.x) | 1.8.18 pins + build-time `cos` assertion |
| `KeyError: 'query'` on embed | `prompt_name` vs empty prompts dict | literal `search_document:`/`search_query:` prefixes |
| "File not found" batch retries | ephemeral `/app/_data` | named volume `preproc_batch_data` |
| 7 "stalled" failures, slow drain | 120-min stall-timeout vs OpenAI latency | `--stall-timeout` defaults to 0 |
| 429 / failed batches | exceeded gpt-4o-mini BQL | size `--max-concurrent = floor(BQL/0.43M)` |
| Lost results on completed batches | output files gone | `recover_batch_results.py` re-pulls from OpenAI |
