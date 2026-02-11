# CVE Review and Remediation Plan

## SoftPower Analytics — Air-Gapped Docker Deployment

| Field              | Value                                       |
|--------------------|---------------------------------------------|
| **Date**           | 2026-02-11                                  |
| **Prepared By**    | SoftPower Analytics Development Team        |
| **Deployment Type** | Air-gapped, demonstration/pilot            |
| **Target OS**      | CentOS 7 / RHEL 7+                         |
| **Audience**       | Limited — controlled demo to small group    |
| **Classification** | Non-production, not enterprise-wide release |

---

## 1. Executive Summary

This document provides a CVE vulnerability assessment and remediation plan for the
Docker container images used in the SoftPower Analytics air-gapped deployment. The
deployment consists of two containers (database and application) transferred as tar
files to an isolated CentOS 7 system with no outbound internet access.

**Deployment context**: This is a **demonstration/pilot deployment** for a small,
controlled audience. The application will not be released as a production service to
the broader enterprise. Access to the application is restricted to authorized demo
participants only. The air-gapped network has **no inbound internet access** and the
system is physically or logically isolated from production infrastructure.

---

## 2. Container Image Inventory

Three public registry images are required. Images #2 and #3 are consumed only during
the build phase on an internet-connected machine and are **not** transferred to the
air-gapped target.

### 2.1 Images Loaded on Air-Gapped Target

| # | Image                        | Tag    | Source                                           | Purpose                                |
|---|------------------------------|--------|--------------------------------------------------|----------------------------------------|
| 1 | `pgvector/pgvector`          | `pg16` | [Docker Hub](https://hub.docker.com/r/pgvector/pgvector) | PostgreSQL 16 + pgvector extension (database) |

- **Base**: Official `postgres:16` (Debian Bookworm)
- **Maintainer**: pgvector project (successor to deprecated `ankane/pgvector`)
- **Runs as**: `postgres` user (UID 999) — non-root
- **Exposed port**: 5432 (PostgreSQL)
- **Volume**: `/var/lib/postgresql/data` (persistent named volume)

### 2.2 Images Used During Build Only (Internet-Connected Machine)

| # | Image     | Tag         | Source                                        | Purpose                                     |
|---|-----------|-------------|-----------------------------------------------|---------------------------------------------|
| 2 | `python`  | `3.11-slim` | [Docker Hub](https://hub.docker.com/_/python) | Runtime base for FastAPI + Streamlit app     |
| 3 | `node`    | `20-slim`   | [Docker Hub](https://hub.docker.com/_/node)   | Multi-stage build: compiles React frontend   |

- **python:3.11-slim**: Debian Bookworm-based. Used as the runtime layer of the final
  `softpower-app-airgap:latest` image.
- **node:20-slim**: Debian Bookworm-based. Used only in Stage 1 of the multi-stage
  Dockerfile to run `npm ci && npm run build`. The Node.js runtime and all build
  artifacts except `client/dist/` are discarded — **Node.js is not present in the
  final image**.

### 2.3 Image Provenance Summary

| Image              | Official/Verified | Maintainer                | Update Cadence         |
|--------------------|-------------------|---------------------------|------------------------|
| `pgvector/pgvector`| Yes (Docker Hub Verified) | pgvector OSS project | Follows PostgreSQL releases |
| `python`           | Yes (Docker Official Image) | Docker / Python community | Monthly patch releases |
| `node`             | Yes (Docker Official Image) | Docker / Node.js project  | Monthly patch releases |

All three images are Docker Official or Verified Publisher images with established
security response processes and regular patch cadences.

---

## 3. Known Vulnerabilities by Image

The following CVEs are based on public vulnerability databases as of February 2026.
Actual scan results should be generated using `docker scout`, `trivy`, or `snyk` on
the exact image digests at time of package creation.

### 3.1 pgvector/pgvector:pg16 (Base: postgres:16 / Debian Bookworm)

| CVE               | Component | Severity | CVSS | Description                                              | Fixed Version | Exploitable in Context? |
|-------------------|-----------|----------|------|----------------------------------------------------------|---------------|------------------------|
| CVE-2026-0861     | glibc     | Medium   | TBD  | `getnetbyaddr` stack content leak via DNS backend        | None (Debian) | **No** — air-gapped, no DNS queries to external resolvers |
| CVE-2025-15281    | glibc     | Medium   | TBD  | `memalign` integer overflow → heap corruption            | None (Debian) | **No** — requires attacker control of `memalign` args    |
| CVE-2026-0915     | glibc     | Low      | TBD  | `regexec.c` uncontrolled recursion (disputed)            | None (Debian) | **No** — disputed; requires crafted regex input          |
| CVE-2005-2541     | tar       | Low      | TBD  | No setuid/setgid warning on extract                      | None (Debian) | **No** — no user-supplied tar extraction in container    |

**PostgreSQL-specific CVEs**: Check [postgresql.org/support/security](https://www.postgresql.org/support/security/)
for the exact PG 16.x minor version included in the image at build time. Pin to the
latest `pg16` tag and rebuild if a PostgreSQL CVE is published.

### 3.2 python:3.11-slim (Debian Bookworm) — Baked into App Image

| CVE               | Component | Severity | CVSS | Description                                              | Fixed Version | Exploitable in Context? |
|-------------------|-----------|----------|------|----------------------------------------------------------|---------------|------------------------|
| CVE-2026-0861     | glibc     | Medium   | TBD  | Same as above — stack content leak via DNS                | None (Debian) | **No** — air-gapped    |
| CVE-2025-15281    | glibc     | Medium   | TBD  | Same as above — memalign overflow                         | None (Debian) | **No** — no attacker-controlled allocations |
| CVE-2026-0915     | glibc     | Low      | TBD  | Same as above — regexec recursion (disputed)              | None (Debian) | **No** — disputed      |
| CVE-2005-2541     | tar       | Low      | TBD  | Same as above — tar setuid warning                        | None (Debian) | **No**                 |

**Python-specific CVEs**: The app uses Python 3.11. Check [python.org/downloads/security](https://www.python.org/downloads/security/)
for the exact 3.11.x patch level. The `-slim` variant minimizes the OS package surface.

### 3.3 node:20-slim (Debian Bookworm) — Build-Only, Not on Target

| CVE               | Component | Severity | CVSS | Description                                              | Exploitable in Context? |
|-------------------|-----------|----------|------|----------------------------------------------------------|------------------------|
| CVE-2025-59465    | Node.js   | High     | TBD  | HTTP/2 HEADERS crash via malformed HPACK data             | **No** — build-only; Node.js not in final image |
| CVE-2025-59466    | Node.js   | Medium   | TBD  | Uncatchable stack overflow with `async_hooks`             | **No** — build-only    |
| CVE-2025-59464    | Node.js   | Medium   | TBD  | TLS client certificate memory leak                        | **No** — build-only    |
| CVE-2026-21636    | Node.js   | Medium   | TBD  | Unix Domain Socket permission model bypass                | **No** — build-only    |
| CVE-2026-21637    | Node.js   | Medium   | TBD  | TLS PSK/ALPN callback DoS                                 | **No** — build-only    |
| CVE-2025-55132    | Node.js   | Low      | TBD  | `fs.futimes()` permission model bypass                    | **No** — build-only    |
| CVE-2026-0861     | glibc     | Medium   | TBD  | Stack content leak via DNS backend                        | **No** — build-only    |
| CVE-2025-15281    | glibc     | Medium   | TBD  | memalign integer overflow                                 | **No** — build-only    |
| CVE-2025-13151    | libtasn1  | Medium   | TBD  | Stack buffer overflow in `asn1_expand_octet_string`       | **No** — build-only    |

**Note**: The `node:20-slim` image is used exclusively in a multi-stage Docker build.
The final application image does not contain Node.js, npm, or any Node.js runtime
dependencies. All Node.js CVEs are therefore **not present on the air-gapped target**.

---

## 4. Risk Classification

### 4.1 Risk Assessment Matrix

| Risk Factor                           | Assessment       | Justification                                                |
|---------------------------------------|------------------|--------------------------------------------------------------|
| **Network exposure**                  | Minimal          | Air-gapped system, no inbound/outbound internet              |
| **Attack surface**                    | Limited          | Only ports 8000, 8501, 5432 exposed on local network         |
| **User base**                         | Restricted       | Controlled demo audience; not enterprise-wide                 |
| **Data sensitivity**                  | Low–Medium       | Analytical data for demonstration; no PII/PHI                 |
| **Blast radius if compromised**       | Isolated         | Air-gapped host is isolated from production infrastructure    |
| **Persistence of deployment**         | Temporary        | Demo/pilot duration; not a permanent production system        |
| **Attacker access to container args** | None             | No external users can supply container parameters             |
| **DNS resolution (CVE-2026-0861)**    | Not applicable   | No external DNS resolvers reachable from air-gapped network   |
| **Node.js runtime CVEs**              | Not applicable   | Node.js is not present in any image on the target system      |

### 4.2 Overall Risk Rating: **LOW**

All identified CVEs are either:
1. **Not exploitable** in the air-gapped deployment context (no network path, no attacker-controlled input)
2. **Disputed** by upstream maintainers
3. **Present only in the build environment**, not on the air-gapped target
4. **Low severity** with no practical exploit path in a containerized PostgreSQL/Python workload

---

## 5. Compensating Controls

The following controls mitigate residual risk beyond what patching alone addresses:

### 5.1 Network Isolation
- **Air-gapped deployment**: The target system has no route to the internet. CVEs
  requiring network-based exploitation (DNS, HTTP/2, TLS) have no viable attack vector.
- **Docker bridge network**: Containers communicate over an isolated Docker bridge
  network (`softpower_net`). Only explicitly published ports are reachable from the host.
- **Firewall rules**: Only ports 8000 (Web App), 8501 (Streamlit), and 5432
  (PostgreSQL) are exposed, restricted to authorized demo participants.

### 5.2 Access Control
- **Limited audience**: Access is restricted to a small, known group of demo participants.
- **No public-facing endpoints**: The system is not exposed to the internet or to the
  broader enterprise network.
- **Database credentials**: PostgreSQL requires username/password authentication for all
  non-local connections (`pg_hba.conf` uses `md5` for network connections).

### 5.3 Container Hardening
- **Non-root database**: `pgvector/pgvector:pg16` runs PostgreSQL as the `postgres` user (UID 999).
- **Read-only model cache**: The HuggingFace model cache (`/app/.cache/huggingface`) is
  baked into the image at build time with `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1`,
  preventing any outbound model download attempts.
- **No package managers at runtime**: The `-slim` base images have minimal OS packages.
  `apt` repositories are unreachable on the air-gapped system.
- **Restart policy**: Containers use `--restart unless-stopped` for availability without
  requiring orchestration.
- **Shared memory**: `--shm-size=1g` is set for PostgreSQL to prevent shared memory
  exhaustion without over-allocating.

### 5.4 Data Protection
- **Persistent volumes**: Database data is stored in a named Docker volume
  (`softpower_pgdata`), surviving container restarts.
- **Backup/restore**: The deployment script includes `backup` and `restore` commands for
  `pg_dump`/`pg_restore` operations.
- **No secrets in images**: Credentials are passed via environment variables from a `.env`
  file on the host, not baked into images.

---

## 6. Remediation Actions

### 6.1 Pre-Deployment (Before Transfer to Air-Gapped System)

| # | Action                                    | Status   | Notes                                        |
|---|-------------------------------------------|----------|----------------------------------------------|
| 1 | Pin images to latest patch tags           | Required | Use exact digest or dated tags, not `latest`  |
| 2 | Run `docker scout cves` or `trivy image`  | Required | Generate scan report for each image           |
| 3 | Verify no CRITICAL CVEs with known exploits| Required | Cross-reference with CISA KEV catalog         |
| 4 | Archive scan reports with package          | Required | Include in deployment package for audit trail |
| 5 | Build app image from latest base          | Required | `docker build --pull` to get latest patches   |

### 6.2 Scan Command Reference

```bash
# Option A: Docker Scout (requires Docker Desktop or Hub login)
docker scout cves pgvector/pgvector:pg16
docker scout cves python:3.11-slim
docker scout cves node:20-slim
docker scout cves softpower-app-airgap:latest

# Option B: Trivy (open source, no login required)
trivy image pgvector/pgvector:pg16
trivy image python:3.11-slim
trivy image node:20-slim
trivy image softpower-app-airgap:latest

# Save reports for audit
trivy image --format json -o scan-pgvector.json pgvector/pgvector:pg16
trivy image --format json -o scan-app.json softpower-app-airgap:latest
```

### 6.3 Post-Deployment

| # | Action                                    | Frequency | Notes                                        |
|---|-------------------------------------------|-----------|----------------------------------------------|
| 1 | Monitor PostgreSQL security announcements  | Ongoing   | https://www.postgresql.org/support/security/  |
| 2 | Monitor Python security announcements      | Ongoing   | https://www.python.org/downloads/security/    |
| 3 | Rebuild and re-transfer if Critical CVE    | As needed | Only for CVEs with known exploits applicable to this deployment |
| 4 | Review CISA KEV catalog for listed CVEs    | Monthly   | https://www.cisa.gov/known-exploited-vulnerabilities-catalog |

---

## 7. Image Update Procedure

When a CVE requires updating an image on the air-gapped system:

```
Internet-Connected Machine                Air-Gapped Target
========================                  ==================
1. docker pull pgvector/pgvector:pg16
2. docker build --pull -f airgap.Dockerfile
3. Run vulnerability scan
4. ./scripts/docker/airgap-build.sh
5. Transfer .tar.gz via approved media -> 6. ./airgap-deploy.sh load ./images
                                          7. ./airgap-deploy.sh restart
                                          8. ./airgap-deploy.sh migrate
```

Estimated update cycle time: ~1 hour (build + scan + transfer + restart).

---

## 8. Approval Request Summary

### Images Requested for Approval

| # | Image                   | Tag         | Registry   | Used On Target? | Official Image? |
|---|-------------------------|-------------|------------|-----------------|-----------------|
| 1 | `pgvector/pgvector`     | `pg16`      | Docker Hub | Yes             | Yes (Verified Publisher) |
| 2 | `python`                | `3.11-slim` | Docker Hub | Yes (baked in)  | Yes (Docker Official) |
| 3 | `node`                  | `20-slim`   | Docker Hub | No (build-only) | Yes (Docker Official) |

### Justification

- **pgvector/pgvector:pg16**: Required for PostgreSQL with vector similarity search
  (pgvector extension). This is the official, maintained image from the pgvector project
  and the designated successor to the deprecated `ankane/pgvector`. No equivalent
  capability exists in the base PostgreSQL image without compiling the extension from
  source.

- **python:3.11-slim**: Required as the runtime base for the application server
  (FastAPI, Streamlit, scikit-learn, sentence-transformers). The `-slim` variant
  minimizes the OS package surface area compared to the full Debian image.

- **node:20-slim**: Required to compile the React TypeScript frontend (`npm ci && npm
  run build`). Used only during the Docker multi-stage build on the internet-connected
  machine. The Node.js runtime is **not present** in the final application image
  transferred to the air-gapped system. This image is requested because the build
  machine does not have a working local Node.js installation.

### Risk Acceptance Statement

Given that:
1. The deployment is **air-gapped** with no internet connectivity
2. The audience is a **small, controlled group** of demo participants
3. The system is **not a production release** to the enterprise
4. All identified CVEs are **not exploitable** in this deployment context
5. All images are from **official, verified publishers** with active maintenance
6. **Compensating controls** (network isolation, access restriction, non-root
   containers) further reduce residual risk

We request approval to use the above three Docker images for the SoftPower Analytics
demonstration deployment.

---

## Appendix A: Network Architecture

```
┌──────────────────────────────────────────────────┐
│              Air-Gapped Host (CentOS 7)          │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │         Docker Network: softpower_net       │ │
│  │                                             │ │
│  │  ┌─────────────────┐  ┌──────────────────┐ │ │
│  │  │  softpower_db   │  │  softpower_app   │ │ │
│  │  │  pgvector/      │  │  softpower-app-  │ │ │
│  │  │  pgvector:pg16  │  │  airgap:latest   │ │ │
│  │  │                 │  │                  │ │ │
│  │  │  Port: 5432     │  │  Port: 8000 (API)│ │ │
│  │  │  User: postgres │  │  Port: 8501 (UI) │ │ │
│  │  │  Vol: pgdata    │  │                  │ │ │
│  │  └─────────────────┘  └──────────────────┘ │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  Exposed to local network:                       │
│    :8000 → React Web App + API                   │
│    :8501 → Streamlit Dashboard                   │
│    :5432 → PostgreSQL (optional, can restrict)   │
│                                                  │
│  No internet connectivity (inbound or outbound)  │
└──────────────────────────────────────────────────┘
```

## Appendix B: Python Dependency Packages (in App Image)

Key packages with security-relevant surface area:

| Package              | Purpose                     | Notes                              |
|----------------------|-----------------------------|------------------------------------|
| `fastapi` 0.104.1   | Web framework               | Only local network exposure        |
| `uvicorn` 0.24.0    | ASGI server                 | Binds to container port 8000       |
| `sqlalchemy` 2.0.23 | Database ORM                | Connects to local PostgreSQL only  |
| `psycopg2-binary` 2.9.9 | PostgreSQL driver       | Local connection only              |
| `openai` ≥2.14.0    | LLM API client              | Non-functional in air-gap (no API) |
| `boto3`             | AWS S3 client                | Non-functional in air-gap (no AWS) |
| `torch`             | PyTorch ML framework         | Local inference only               |
| `sentence-transformers`| Embedding model           | Offline mode (`HF_HUB_OFFLINE=1`)  |
| `bcrypt` ≥4.0.0     | Password hashing             | Local auth only                    |
| `PyJWT` ≥2.8.0      | JWT tokens                   | Local auth only                    |
| `requests`          | HTTP client (Streamlit)       | Internal container-to-container    |

## Appendix C: Scan Report Attachment

> **Action Required**: Before submitting this document for approval, attach the actual
> scan reports generated by running the commands in Section 6.2. The reports should be
> generated on the same image digests that will be packaged for transfer.
>
> Attach as:
> - `scan-pgvector-pg16.json` — Database image scan
> - `scan-softpower-app.json` — Application image scan (includes python:3.11-slim base)
> - `scan-node-20-slim.json` — Build-only image scan (for completeness)

---

*Document generated 2026-02-11. Re-scan and update before each deployment transfer.*
