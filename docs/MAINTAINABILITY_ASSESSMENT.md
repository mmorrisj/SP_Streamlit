# Maintainability & Maintainer-Transition Assessment

**Date:** 2026-06-07
**Context:** Demo target **July 2026**; potential handoff to a new maintainer by **October 2026**.
**Scope:** Whole-repo review of code structure, documentation, tests/CI, and deployment, with prioritized recommendations to (a) de-risk the July demo and (b) make the codebase handoff-ready by October.

> **Status addendum (2026-07-14).** Several headline findings have since been resolved and
> this document should be read with those corrections:
> - §1(3)/§3: a plain **`docker-compose.yml` now exists** (zero-prerequisite default stack);
>   the quickstart is no longer broken. `DEPLOYMENT.md` provides the deployment decision
>   tree, and the quickstart fragmentation was consolidated in the July 2026 doc overhaul
>   (CI_CD_SUMMARY.md deleted into TESTING.md; DOCKERHUB_README re-pinned to current tags).
> - §1(1): `server/main.py` has begun router extraction (`server/routers/`: influencer,
>   ingestion, intel_reports) — partial, still large.
> - §9: compose files now use `pgvector:0.8.2-pg17` and app images through `1.8.26`;
>   newer `docker-compose.laptop*.yml` / `enterprise.yml` variants exist.
> - The coverage/CI findings (§1(4)) remain accurate and open.

---

## 1. Executive Summary

The application is **functionally rich and reasonably well-architected at the package level** (clean `shared` / `services` / `server` / `client` separation, SQLAlchemy 2.0, pgvector RAG, a real CI pipeline, and ~13K lines of documentation). It is **not yet handoff-ready**, primarily because of:

1. **A few very large "god" files** that concentrate risk and slow onboarding — most notably `server/main.py` (5,949 lines / 98 endpoints, no `APIRouter`) and the batch/report subsystems.
2. **Dead and orphaned code shipping in the repo** — `_archive/` (34 MB, including IDE artifacts and a 23 MB data file) and an incomplete experimental `agent/` subsystem (~8K lines, 21+ TODO stubs). (An earlier draft also flagged `services/publication/` as orphaned; that was incorrect — see §4 — it is invoked by the event pipeline.)
3. **Documentation that is broad but stale and fragmented** — the documented quickstart (`docker-compose up -d`) **does not work** because no plain `docker-compose.yml` exists, and five overlapping deployment docs give partially conflicting guidance.
4. **Very low automated test coverage (~4% of lines)** with the largest modules effectively untested, and **non-blocking CI lint/tests** so regressions can merge silently.

None of these block a July demo, but all of them block a clean October handoff. The recommendations below are sequenced accordingly: **demo-hardening first, then de-bloating, then modularization, then test/doc hardening.**

**Handoff readiness today: ~60/100.** Achievable by October with the roadmap in §7.

---

## 2. What's Healthy (keep doing this)

- **Package-level separation of concerns**: `shared/` (models, db, config, utils), `services/` (chat, pipeline, dashboard), `server/` (API), `client/` (React). Imports follow the documented convention.
- **Modern data layer**: SQLAlchemy 2.0 with centralized pooling in `shared/database/database.py`; Alembic migrations (21 versions); pgvector for embeddings.
- **No hardcoded secrets** in active code; auth via enterprise JWT with a clearly-flagged `DEV_AUTH_BYPASS` (`server/auth.py`).
- **A real CI pipeline** (`.github/workflows/ci.yml`): lint, Postgres+pgvector test service, coverage upload, Docker build, Trivy scan.
- **Defensive integration of experimental code**: the `agent/` router is mounted inside a `try/except` (`server/main.py:118-124`) so a broken agent import can't take down the core API — a good pattern.
- **Strong domain/pipeline documentation**: the event-processing two-stage architecture and pipeline references are genuinely detailed.

---

## 3. Monolithic Components to Break Out

| File | Size | Problem | Recommendation |
|---|---|---|---|
| `server/main.py` | **5,949 lines / 98 endpoints** | Single FastAPI file holding 16 concern-areas (auth, documents, events, summaries, influencer, metrics, bilateral, S3 proxy, chat/RAG, admin…). No `APIRouter` used at all. | **Split into `APIRouter` modules** under `server/routers/` (e.g. `documents.py`, `events.py`, `summaries.py`, `influencer.py`, `metrics.py`, `bilateral.py`, `chat.py`, `s3_proxy.py`, `admin.py`). Keep `main.py` as app assembly + middleware only. The `agent/router.py` already demonstrates the target pattern. |
| `services/pipeline/batch/batch_prepare.py` | **3,726 lines (146 KB)** | Largest pipeline module; **zero tests**; mixes schema definitions, job-type mapping, model tiering, and orchestration. | Extract `schemas`, `job_type_mapping`, and `model_selection` into separate modules (a `batch/schemas.py` already exists — consolidate there). Add unit tests for the pure-logic pieces first. |
| `services/pipeline/batch/batch_process_results.py` | 2,494 lines (96 KB) | Same family; parsing + DB writes intertwined. | Separate result parsing (pure) from persistence (I/O) to make it testable. |
| `server/report_generator.py` + `report_exporter.py` + `report_batch.py` + `report_validator.py` | **~5,755 lines across 4 files** | Whole reporting subsystem lives in `server/`, lazily imported inside endpoint bodies in `main.py`. Overlaps conceptually with `services/publication/` (a second, pipeline-invoked reporting path). | Move the reporting subsystem into `services/reporting/` as a cohesive package with a small public interface. Decide one canonical reporting path (see §4). |
| `services/chat/rag_service.py` | 2,029 lines | Large but **cohesive and well-tested** (46 tests). | Lower priority; optionally split retrieval vs. generation, but not urgent. |
| `shared/models/models.py` | 1,731 lines | All ORM models in one file. | Optional: split by domain (`documents`, `events`, `entities`, `summaries`) into a `shared/models/` package; manageable as-is. |

**Why this matters for handoff:** a new maintainer's first task is almost always "find where endpoint X is handled." With 98 routes in one file and lazy in-body imports, that is slow and error-prone. Router extraction is the single highest-leverage maintainability change.

---

## 4. Deprecated / Dead Code to Remove

| Item | Status | Evidence | Action |
|---|---|---|---|
| `_archive/` (34 MB) | **Dead** | No active code imports from it (verified). Contains Visual Studio `.suo`, `.vs/slnx.sqlite`, a **23 MB `processed.bak`**, `.pptx` decks, old Flask backend, legacy Streamlit. | **Delete from the working tree.** History is preserved in git; nothing should ship a 34 MB archive. If retention is required, move to a separate `-archive` repo or a tagged commit. |
| `services/publication/` | **In use (not orphaned)** | No *Python imports* outside itself, but `services/pipeline/events/run_full_pipeline.py` invokes `generate_publication.py` as a subprocess step, and it's documented in `README_EVENT_SUMMARIES.md`. Overlaps conceptually with `server/report_generator.py`. | **Do NOT delete.** Pick one canonical reporting path: either route the pipeline through the `server/reporting` package or keep `services/publication` as the batch/CLI path — but document which is authoritative. |
| `agent/` (~8K lines, 48 files) | **Experimental / incomplete** | Mounted defensively but **21+ `TODO` stubs**: LLM providers (`agent/llm/anthropic.py`), tool bodies (`agent/tools/*`), and `agent/router.py:67` ("tool execution … are TODO"). Not wired into either frontend. | **Decide explicitly before handoff:** (a) finish it as a roadmap feature, (b) move it to a feature branch / separate repo, or (c) keep it mounted-but-dormant **with a clear `EXPERIMENTAL` README and a feature flag**. Do not hand it off in an ambiguous half-state. |
| `coverage.xml` (572 KB) | **Stray artifact, git-tracked** | Generated file committed to repo (paths show a Windows dev machine). `.coverage` is gitignored but `coverage.xml` is not. | **Remove from git; add to `.gitignore`.** |
| `softpower_backup.sql` (0 bytes) | **Stray artifact** | Empty file committed at repo root. | Delete; add `*.sql` backups to `.gitignore`. |
| `_archive/.vs/*` (`.suo`, `slnx.sqlite`) | **IDE artifacts** | Tracked binary IDE state. | Delete; ensure `.vs/` is gitignored. |
| Duplicate `config.yaml` | **Drift risk** | Both `shared/config/config.yaml` and `services/dashboard/config.yaml` are tracked. | Consolidate to one source of truth (`shared/config/`) and have the dashboard read it, or document why two exist. |

**Estimated impact:** removing `_archive/` + stray artifacts cuts the tracked repo by ~34 MB and eliminates the single biggest source of "is this code live?" confusion for a new maintainer.

---

## 5. Documentation Gaps & Staleness

**Broken / stale (fix before demo):**
- **Quickstart is broken**: `CLAUDE.md` and `README.md` instruct `docker-compose up -d`, but **there is no `docker-compose.yml`** — only `docker-compose.dev.yml`, `.production.yml`, `.windows.yml`, `.preprocessing.yml`. Either add a default `docker-compose.yml` (symlink/copy of dev) or fix every command to name the file (`docker compose -f docker-compose.dev.yml up -d`).
- **`CLAUDE.md` references a `streamlit/` directory that does not exist** (it's `services/dashboard/`), including the "Adding New Dashboard Pages" instructions — a newcomer will create files in the wrong place.
- DB-access examples mix `localhost`, `127.0.0.1`, `host.docker.internal`, and `softpower_db` without explaining which applies in which context.

**Fragmented (consolidate before handoff):**
- **Five overlapping deployment docs** — `README.md`, `DOCKER_WORKFLOW.md`, `PRODUCTION_DOCKER_RUN.md`, `ENTERPRISE_MIGRATION.md`, `docs/deployment/PRODUCTION_INSTALL.md` — give partially conflicting guidance (e.g. `docker exec` patterns that are blocked on the hardened enterprise daemon). Collapse into **one `DEPLOYMENT.md` with a decision tree** (dev vs. permissive-prod vs. enterprise-hardened) that links out to specifics.

**Missing (create for handoff):**
- `LICENSE` (legal/IP clarity — currently absent).
- `RUNBOOK.md` — incident response, backup/restore, migrations, monitoring, escalation.
- `DATA_DICTIONARY.md` — `documents`, the `canonical_event` / `master_event` hierarchy, JSONB fields, embedding model/dimension, country/category taxonomies.
- `CONTRIBUTING.md` — code style, commit/PR conventions, how to add an endpoint/dashboard page/migration.
- `SECURITY.md` — vuln reporting, PII/classification handling, CVE-exception process (a template exists but no policy).
- An **ARCHITECTURE.md** with one current diagram (the two-frontend + API + pipeline topology) — today this is implicit across many files.

---

## 6. Testing, CI & Code Quality

**Current state:**
- 8 test files, 146 test functions — **real tests, not stubs**, with good fixtures and pytest markers.
- **But line coverage is ~4%** (638/15,727). `batch_prepare.py` (3,726 lines) has **no tests**; `server/main.py` business logic is largely untested (only exercised indirectly via HTTP).
- **CI lint and tests are non-blocking** (`continue-on-error`), so failures don't fail the build.
- No `mypy`, no `isort`, no pre-commit hooks. `ruff` + `black` are configured (good) but not enforced locally.

**Recommendations (in order):**
1. **Make CI blocking** for lint and the unit-test job — stop the bleeding so new regressions can't merge.
2. **Add a coverage floor** (start at a low bar, e.g. 20%, ratchet upward) rather than the current unset threshold.
3. **Target tests at the modules you're about to refactor**: `batch_prepare.py` schemas/mapping and the soon-to-be-extracted routers. Refactor + test together so coverage rises where risk is highest.
4. **Add a `.pre-commit-config.yaml`** (ruff, black, isort, end-of-file/trailing-whitespace) so contributors get local enforcement — important when a new maintainer joins.
5. Add `mypy` in a non-blocking job first, then tighten on new code only.

---

## 7. Prioritized Roadmap

### Phase 0 — Demo hardening (now → July)
*Goal: the demo path is reliable and reproducible from a clean checkout.*
- [ ] Fix the broken quickstart: add a default `docker-compose.yml` (or correct all `-f` references).
- [ ] Fix `CLAUDE.md` `streamlit/` → `services/dashboard/` paths.
- [ ] Make CI unit-test + lint jobs **blocking**; ensure `main` is green.
- [ ] Smoke-test the exact demo flow (ingest → analyze → events → dashboard/React) and write it up as `docs/DEMO_RUNBOOK.md`.
- [ ] Confirm `agent/` is either flagged-off or visibly labeled experimental so it isn't demoed by accident.

### Phase 1 — De-bloat & clarify (July → August)
*Goal: what's in the repo is what's alive.*
- [x] Remove `_archive/`, `coverage.xml`, `softpower_backup.sql`, `.vs/` artifacts; update `.gitignore`. *(done — repo working tree ~42 MB → ~8 MB; history preserved)*
- [ ] Decide and act on `agent/` (finish / branch / flag) and the dual reporting paths (`server/report_*` vs the pipeline-invoked `services/publication/` — pick one canonical path; do NOT just delete publication).
- [x] Consolidate the deployment docs behind one `DEPLOYMENT.md` decision tree. *(done — additive entry point; detailed docs retained as references)*
- [ ] Consolidate duplicate `config.yaml`. *(deferred — `shared/config/config.yaml` and `services/dashboard/config.yaml` have diverged; needs a careful merge + dashboard load-path change, not a blind dedup)*
- [x] Make the **production** DB external-capable (native Postgres 18 + extensions); keep the bundled `db` container as the dev/demo default only. *(done — `docker-compose.production.yml` gates `db` behind a `bundled-db` profile with `required: false` dependents and an overridable `DB_HOST`; documented in `DEPLOYMENT.md`. See §9.)*

### Phase 2 — Modularize the monoliths (August → September)
*Goal: no single file is a bottleneck to understanding.*
- [ ] Split `server/main.py` into `server/routers/*` `APIRouter` modules (mirror `agent/router.py`).
- [ ] Move the reporting subsystem into `services/reporting/`.
- [ ] Break up `batch_prepare.py` / `batch_process_results.py` into schema/logic/IO units **with tests**.

### Phase 3 — Handoff hardening (September → October)
*Goal: a new maintainer can operate and extend the system unaided.*
- [ ] Author `RUNBOOK.md`, `DATA_DICTIONARY.md`, `CONTRIBUTING.md`, `SECURITY.md`, `ARCHITECTURE.md`, `LICENSE`.
- [ ] Raise coverage floor on the now-modular code; add `pre-commit` + `mypy` (new-code).
- [ ] Decide the two-frontend question (see §8) and document the decision.
- [ ] Run a **dry-run handoff**: have someone unfamiliar provision from docs only and log every gap.

---

## 8. Strategic Decision: Two Frontends

The app ships **two UIs**: the React `client/` (primary, talks to the 98-endpoint API) and a **23-page Streamlit dashboard** (`services/dashboard/`, which bypasses the API and queries Postgres directly). Both are maintained, with overlapping analytics surfaces and **different data-access patterns** (API vs. direct DB).

For a small future maintenance team this is a meaningful ongoing burden. Before October, make an explicit decision:
- **Keep both** and document the division of responsibility (React = product UI, Streamlit = internal analytics), or
- **Converge** on React + API and retire/shrink Streamlit, or
- **Demote** Streamlit to clearly-labeled internal tooling.

The direct-DB access in Streamlit also means schema changes can silently break it (it shares no API contract). Whatever is chosen, it should be a conscious, documented decision rather than inherited ambiguity.

---

## 9. Infrastructure Simplification: Native Postgres 18 vs. the Bundled DB Container

**Update — validated:** Postgres 18 with the required extensions (including
`pgvector`) has been validated. This **removes the need to run the bundled custom
database container in production** — the `db` service uses
`mmorrisj/pgvector:0.8.1-pg17` (container `softpower_db`) across all three compose
files. Production deployments can instead point at a native/managed Postgres 18
via `DATABASE_URL` / `DB_HOST`.

**Development keeps the container.** Local/home development and the demo
quickstart continue to use the bundled container via `docker-compose.yml` and
`docker-compose.dev.yml` — no change for those workflows.

**Why this matters for maintainability & handoff:**
- **One fewer custom image** to build, patch, and CVE-scan (`docker/pgvector.Dockerfile`). The custom pgvector image has been a recurring maintenance + security-exception burden (see `docs/CVE_MITIGATION_REPORT.md` and the enterprise CVE-exception template).
- **Easier enterprise approval/operation**: a native or managed Postgres 18 is far simpler for an enterprise DBA team to run on a hardened host than a custom container.
- **Smaller production footprint**: drops a stateful container from the prod stack.

**Recommended actions:**
- [x] Make the `db` service **optional in the production compose** (behind the `bundled-db` Compose profile) so prod can set `DB_HOST`/creds to the external Postgres 18 and omit the container entirely; `db` remains the default in `docker-compose.yml` (dev/demo) and `docker-compose.dev.yml`. *(done)*
- [x] Document the external-Postgres path in `DEPLOYMENT.md`, including the **extensions that must be pre-installed** (`vector`/pgvector and `pg_trgm`). *(done)*
- Once production no longer depends on it, the custom `docker/pgvector.Dockerfile` / `mmorrisj/pgvector` image can be retired from the **production** path while remaining the dev/demo default.

---

## 10. Quick-Reference: Top 10 Actions by Leverage

1. Fix the broken `docker-compose` quickstart (demo blocker).
2. Make CI lint/tests blocking (stops new regressions).
3. Delete `_archive/` + stray artifacts (`coverage.xml`, empty `.sql`, `.vs/`).
4. Resolve `agent/` status (finish / branch / flag) and consolidate the dual reporting paths (`server/report_*` vs pipeline-invoked `services/publication/`).
5. Split `server/main.py` into routers.
6. Consolidate 5 deployment docs → 1 decision tree; fix `streamlit/` path in `CLAUDE.md`.
7. Add tests around `batch_prepare.py` while refactoring it.
8. Write `RUNBOOK.md` + `DATA_DICTIONARY.md`.
9. Add `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `pre-commit`.
10. Decide the two-frontend strategy and document it.
