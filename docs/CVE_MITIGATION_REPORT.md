# CVE Mitigation Report: SoftPower Analytics Docker Stack

**Date**: February 24, 2026
**Scanner**: Docker Scout v1.19.0
**Platform**: linux/amd64

| Image | Tag | Base | Purpose |
|-------|-----|------|---------|
| `mmorrisj/softpower-analytics` | 1.5.4 | `python:3.13-slim` (Debian Trixie) | Application (FastAPI + Streamlit + React + ML) |
| `mmorrisj/pgvector` | 0.8.1-pg16 | `postgres:16-trixie` (Debian Trixie) | PostgreSQL 16 + pgvector extension |

---

## Executive Summary

A comprehensive vulnerability scan and remediation was performed on both Docker images in the SoftPower Analytics stack. Combined results:

### Application Image (`softpower-analytics:1.5.4`)

**61 of 95 identified CVEs were eliminated** through base image upgrades, package version bumps, build-tool removal, Debian package removal, and supervisor migration to pip. All CRITICAL and HIGH severity vulnerabilities have been resolved. Supply chain attestations (SBOM + max-mode provenance) are attached to the image.

| Metric | Before (v1.0.0) | After (v1.5.4) | Change |
|--------|:---:|:---:|:---:|
| Critical | 2 | 0 | -2 |
| High | 5 | 0 | -5 |
| Medium | 6 | 1 | -5 |
| Low | 81 | 33 | -48 |
| Unknown | 1 | 0 | -1 |
| **Total** | **95** | **34** | **-61 (64% reduction)** |
| Packages Scanned | 418 | 331 | -87 removed |

**Version History**:
- **v1.1.0**: Base image upgrade (3.11->3.13), package upgrades, build-tool removal (95->36 CVEs)
- **v1.2.0**: Added non-root user (`appuser`) for Docker Scout health score compliance
- **v1.3.0**: Fixed CVE-2026-23949 (HIGH, jaraco.context Zip Slip), added supply chain attestations (SBOM + provenance)
- **v1.5.0-1.5.2**: Deployment hardening (admin user creation, production compose, SQLAlchemy bump)
- **v1.5.3**: Supervisor via pip (eliminates Debian python3.13 package chain — 5 CVEs cleared, 36 packages removed)
- **v1.5.4**: curl + rmt binary + postgresql-client removed; langchain upgraded to 1.x (closes CVE-2026-26013); pgvector SHA supply-chain pinning; runtime cap_drop + no-new-privileges hardening

**Risk Assessment**: The 34 remaining vulnerabilities are all LOW severity (33) or MEDIUM (1) with no available upstream fix. None are exploitable in this application's deployment context. See Section 2 for detailed analysis.

### Database Image (`pgvector:0.8.1-pg16`)

The previous database image (`ankane/pgvector:latest`) had **337 CVEs** due to a stale, unmaintained base. A custom image was built from `postgres:16-trixie` with pgvector 0.8.1 compiled from source, build tools removed, and runtime packages hardened.

| Metric | Before (ankane/pgvector) | After (mmorrisj/pgvector) | Change |
|--------|:---:|:---:|:---:|
| Critical | 9 | 1 | -8 |
| High | 96 | 6 | -90 |
| Medium | 87 | 10 | -77 |
| Low | 145 | 34 | -111 |
| **Total** | **337** | **51** | **-286 (85% reduction)** |
| Packages Scanned | 224 | 190 | -34 removed |

**Risk Assessment**: The 51 remaining CVEs are all inherited from the official `postgres:16-trixie` base image. The 1 CRITICAL and 6 HIGH are in Go stdlib (bundled by the PostgreSQL Docker maintainers, not by PostgreSQL itself) and affect every `postgres:16` image on Docker Hub. See Section 5 for detailed analysis.

---

## 1. Remediation Actions Taken

### 1.1 Base Image Upgrade
| Change | Detail |
|--------|--------|
| Previous base | `python:3.11-slim` (Debian Bookworm) |
| New base | `python:3.13-slim` (Debian Trixie) |
| Impact | Eliminated all Python 3.11-specific CVEs and inherited newer Debian package versions |

### 1.2 Application Package Upgrades

| Package | Previous Version | New Version | CVEs Fixed |
|---------|:---:|:---:|:---:|
| PyTorch (`torch`) | 2.5.1 | >=2.6.0 (CPU-only) | CVE-2025-32434 (CRITICAL: arbitrary code exec via `torch.load`) |
| PyArrow | 17.0.0 | >=18.0.0 | CVE-2024-52338 (CRITICAL: arbitrary code exec via IPC deserialization) |
| FastAPI | 0.112.x | >=0.115.0 | CVE-2024-24762 (HIGH: ReDoS in multipart), CVE-2025-24750 (HIGH) |
| Starlette | 0.37.x | >=0.40.0 (via FastAPI) | CVE-2024-47874 (HIGH: multipart DoS), CVE-2025-24750 (HIGH), CVE-2024-24762 (MEDIUM) |
| Pillow | not pinned | >=12.1.1 | CVE-2025-3043 (HIGH: buffer overflow in TIFF) |
| wheel | not pinned | >=0.46.2 | CVE-2025-33685 (HIGH: path traversal in wheel extraction) |
| setuptools | 70.2.0 (base) | >=78.1.1 | CVE-2025-47273 (HIGH: path traversal in package install) |
| pip | 24.x (base) | >=26.0 | CVE-2026-1703 (LOW: path traversal) |
| filelock | not pinned | >=3.20.3 | CVE-2025-23207, CVE-2025-23016 (MEDIUM: symlink attacks) |
| pandas | 2.1.4 | >=2.2.0 | Python 3.13 compatibility |
| numpy | not pinned | >=2.1.0 | Python 3.13 compatibility |
| psycopg2-binary | 2.9.9 | >=2.9.10 | Python 3.13 wheel availability |
| matplotlib | not pinned | >=3.9.0 | Python 3.13 compatibility |

### 1.3 Build Tool Removal (Attack Surface Reduction)

`build-essential` (gcc, g++, binutils, make, dpkg-dev) is required during `pip install` for compiling C extensions but is not needed at runtime. These packages were:

1. **Purged via `apt-get purge -y build-essential && apt-get autoremove -y`** -- removes binaries
2. **Deep-cleaned via `dpkg --purge --force-all`** -- removes residual package metadata that scanners flag

This eliminated **39 binutils-related LOW CVEs** and reduced the package count from 418 to 370.

### 1.4 Supervisor via pip (v1.5.x)

Starting with v1.5.0, `supervisor` is installed from PyPI instead of the Debian `supervisor` package. This eliminates the Debian `python3-jaraco.context` dependency chain entirely, removing the need for the dpkg purge + symlink workaround used in v1.3.0.

### 1.5 Non-Root User (v1.2.0)

The container now runs as a non-root user (`appuser`) for Docker Scout health score compliance:
- `groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser`
- All application directories owned by `appuser`
- `supervisord` runs as `appuser` (not root)

### 1.6 Supply Chain Attestations (v1.3.0)

SBOM (Software Bill of Materials) and provenance attestations are now attached to the image using Docker BuildKit's built-in attestation support:
- **SBOM**: Generated by `docker/buildkit-syft-scanner` during build
- **Provenance**: Build provenance metadata attached to the image manifest (max mode)
- **Builder**: `docker-container` driver (required for attestation export and push)

### 1.7 Python 3.13 Compatibility Fixes

Application code was updated for Python 3.13 deprecations:

| File | Change |
|------|--------|
| `server/main.py` | `datetime.utcnow()` -> `datetime.now(timezone.utc)` (5 locations) |
| `server/main.py` | Pydantic `regex=` -> `pattern=` (5 locations) |
| `server/auth.py` | `datetime.utcnow()` -> `datetime.now(timezone.utc)` (2 locations) |
| `server/report_validator.py` | `datetime.utcnow()` -> `datetime.now(timezone.utc)` (2 locations) |

---

## 2. Remaining Vulnerabilities (34 total)

### 2.1 Summary

All 34 remaining CVEs have **no upstream fix available** from Debian or PyPI maintainers (with one exception noted below). They fall into two categories:

- **33 LOW** -- Minimal severity, no known active exploitation
- **1 MEDIUM** -- `tar` vulnerability with limited attack surface

### 2.2 MEDIUM Severity (1)

| CVE | Package | Description | Relevance to Deployment |
|-----|---------|-------------|------------------------|
| CVE-2025-45582 | tar 1.35 | Vulnerability in GNU tar archive handling | **Not relevant.** `tar` is not used by the application at runtime. It exists as a base OS utility in the Debian image. No user-supplied archives are processed with `tar`. No fix available from Debian. |

### 2.3 LOW Severity by Package (35)

#### glibc 2.41 -- 7 LOWs

| CVE | Year | Description | Relevance |
|-----|:---:|-------------|-----------|
| CVE-2019-9192 | 2019 | Stack exhaustion in regex matching | **Not exploitable.** Requires attacker-controlled regex patterns. Application uses hardcoded regex. |
| CVE-2019-1010025 | 2019 | ASLR weakness in `__libc_memalign` | **Not exploitable.** Theoretical information leak; requires local code execution. Container isolation mitigates. |
| CVE-2019-1010024 | 2019 | ASLR information leak via `/proc` | **Not exploitable.** Requires access to `/proc/self/maps`. Container restricted. |
| CVE-2019-1010023 | 2019 | ASLR bypass in `__realpath` | **Not exploitable.** Theoretical; requires local code execution already. |
| CVE-2019-1010022 | 2019 | Stack guard bypass | **Not exploitable.** Theoretical; requires existing code execution. |
| CVE-2018-20796 | 2018 | Stack exhaustion in regex with backrefs | **Not exploitable.** Requires attacker-controlled regex. Application uses fixed patterns. |
| CVE-2010-4756 | 2010 | `glob()` resource consumption | **Not exploitable.** Application does not call `glob()` on user-supplied paths. |

**Assessment**: These are long-standing theoretical issues in glibc that Debian has assessed as LOW impact. All require local code execution or attacker-controlled inputs to paths the application does not expose. **No action needed.**

#### openldap 2.6.10 -- 5 LOWs

| CVE | Year | Description | Relevance |
|-----|:---:|-------------|-----------|
| CVE-2026-22185 | 2026 | OpenLDAP vulnerability | **Not relevant.** Application does not use LDAP. `libldap` is a transitive dependency of `curl`. |
| CVE-2020-15719 | 2020 | Certificate hostname validation issue | **Not relevant.** No LDAP connections made. |
| CVE-2017-17740 | 2017 | `slapd` (LDAP server) memory leak | **Not relevant.** `slapd` is not installed; only client library present. |
| CVE-2017-14159 | 2017 | `slapd` daemon issue | **Not relevant.** `slapd` not installed. |
| CVE-2015-3276 | 2015 | Incorrect certificate DN matching | **Not relevant.** No LDAP connections. |

**Assessment**: OpenLDAP client libraries are pulled in as a transitive dependency of `postgresql-client` (`libpq` optional LDAP auth chain), not `curl`/`libcurl`. The application makes no LDAP connections. Three of five CVEs apply only to `slapd` (the LDAP server), which is not installed. **No action needed in current architecture.**

#### systemd 257.9 -- 4 LOWs

| CVE | Year | Description | Relevance |
|-----|:---:|-------------|-----------|
| CVE-2023-31439 | 2023 | systemd-resolved DNS issue | **Not relevant.** `systemd` is not the init system in the container. Only `libsystemd0` library is present. |
| CVE-2023-31438 | 2023 | systemd-resolved issue | **Not relevant.** Same as above. |
| CVE-2023-31437 | 2023 | systemd-resolved issue | **Not relevant.** Same. |
| CVE-2013-4392 | 2013 | TOCTOU race condition | **Not relevant.** Requires running systemd as PID 1; container uses supervisord. |

**Assessment**: Only `libsystemd0` (a shared library) is present in the image -- the systemd service manager and systemd-resolved are not installed or running. These CVEs are not applicable. **No action needed.**

#### krb5 (Kerberos) 1.21.3 -- 3 LOWs

| CVE | Year | Description | Relevance |
|-----|:---:|-------------|-----------|
| CVE-2024-26461 | 2024 | Memory leak in Kerberos client | **Not relevant.** Application does not use Kerberos authentication. Library is a transitive dependency. |
| CVE-2024-26458 | 2024 | Memory leak in GSS-API | **Not relevant.** GSS-API not used. |
| CVE-2018-5709 | 2018 | Integer overflow in kadmin | **Not relevant.** `kadmin` (admin tool) not installed; library only. |

**Assessment**: Kerberos libraries are transitive dependencies. The application uses JWT-based authentication, not Kerberos. **No action needed.**

#### coreutils 9.7 -- 2 LOWs

| CVE | Year | Description | Relevance |
|-----|:---:|-------------|-----------|
| CVE-2025-5278 | 2025 | coreutils vulnerability | **Not exploitable.** Coreutils commands not invoked on user-supplied input. |
| CVE-2017-18018 | 2017 | `chown` following symlinks | **Not exploitable.** No `chown` on user-supplied paths. |

**Assessment**: Standard OS utilities. Not invoked with untrusted input. **No action needed.**

#### Other Packages -- 1 LOW each (8 packages)

| CVE | Package | Description | Relevance |
|-----|---------|-------------|-----------|
| CVE-2021-45346 | sqlite3 3.46.1 | Memory leak via `UPDATE` | **Not relevant.** SQLite not used; PostgreSQL is the database. Library present as a transitive dependency. |
| CVE-2011-4116 | perl 5.40.1 | Temp file race condition | **Not relevant.** Perl not invoked by the application. Present as an OS utility dependency. |
| CVE-2026-26013 | langchain-core 0.3.83 | SSRF in URL handling | **Low risk.** Fix requires langchain-core >=1.2.11 which is a breaking major version change from our pinned 0.3.x. CVSS 3.7 (LOW). The SSRF vector requires crafted URLs in chain inputs; our RAG service uses controlled document sources. See Section 3 for mitigation plan. |
| CVE-2011-3374 | apt 3.0.3 | Repository signature check issue | **Not relevant.** `apt` is not used at runtime; package lists are deleted in the build. |
| CVE-2022-0563 | util-linux 2.41 | `chfn`/`chsh` info leak | **Not relevant.** These utilities are not used by the application. |
| CVE-2007-5686 | shadow 4.17.4 | `/etc/login.defs` info leak | **Not relevant.** No interactive logins in the container. |
| CVE-2010-0928 | openssl 3.5.4 | Theoretical plaintext recovery | **Not exploitable.** CVSS score of 2.6. Requires specific conditions unlikely in modern TLS. |
| CVE-2024-2236 | libgcrypt20 1.11.0 | Side-channel in RSA decryption | **Not exploitable.** Requires local access and precise timing measurements. Container isolation mitigates. |

---

## 3. Actionable Items for Future Releases

| Priority | Item | Detail | Timeline |
|----------|------|--------|----------|
| Medium | Remove `postgresql-client` from application image (if unused at runtime) | Current `softpower-analytics` runtime stack (`supervisord` + FastAPI + Streamlit) does not require `psql`/`pg_isready`. Removing `postgresql-client` can reduce residual OpenLDAP/Kerberos exposure inherited via `libpq` optional auth dependencies. | Validate in next image build and adopt if no runtime regressions |
| Complete | Pin pgvector source to immutable commit | SHA `778dacf` pinned in `docker/pgvector.Dockerfile` via `ARG PGVECTOR_SHA`; build fails on mismatch. | Done as of v1.5.4 |
| Medium | Lock and hash-pin Python dependencies | Current requirements primarily use `>=` ranges. Adopt lock/constraints with hashes (`--require-hashes`) for deterministic builds and tighter supply-chain control. | Next dependency refresh cycle |
| Complete | langchain-core SSRF | CVE-2026-26013 closed — langchain upgraded to 1.x ecosystem (langchain-1.2.10, langchain-core-1.2.15, langchain-openai-1.1.10). | Done as of v1.5.4 |
| Monitor | tar MEDIUM | CVE-2025-45582 -- no fix available. Monitor Debian security tracker for an updated `tar` package. Not exploitable in current deployment (no user-supplied archives processed). | Watch for Debian fix |
| Complete | curl removal | `curl` was removed from production images and health checks were migrated to Python probes. Keep scanner evidence current to prevent stale report carryover. | Done as of image line (`softpower-analytics:1.5.3`) |

---

## 4. Deployment Risk Assessment

### Architecture Mitigations

The deployment architecture provides multiple layers of protection beyond individual CVE remediation:

1. **Container Isolation**: The application runs in a Docker container with no privileged access. OS-level CVEs (glibc, systemd, shadow, coreutils) require local code execution that container boundaries prevent.

2. **No Interactive Shell Access**: The container runs `supervisord` as PID 1 managing FastAPI and Streamlit. There is no SSH, no login shell, and no interactive user access.

3. **Network Segmentation**: The container exposes only ports 8000 (FastAPI API + React UI) and 8501 (Streamlit dashboard). Internal services communicate via localhost only.

4. **Minimal Package Footprint**: Build tools (`build-essential`, binutils, gcc) are removed after compilation. Supervisor is installed from PyPI (not the Debian package) to avoid pulling in Debian python3.13 runtime packages. The final image contains 331 packages -- only what is needed for runtime.

5. **Offline ML Model**: The HuggingFace sentence-transformer model is baked into the image at build time. `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1` prevent any runtime network calls to HuggingFace, eliminating a potential supply-chain vector.

6. **No User-Supplied File Processing**: The containerized application serves a web API and dashboard. Document ingestion runs separately on the host, not in this container. Users cannot upload arbitrary files (tar archives, wheel packages, etc.) that would trigger the remaining CVEs.

### Conclusion

**The `softpower-analytics:1.5.4` image is suitable for production deployment.** All CRITICAL and HIGH vulnerabilities have been resolved. The 34 remaining vulnerabilities (1 MEDIUM, 33 LOW) are either:

- In OS packages not used by the application (systemd, openldap, krb5, sqlite3, perl, shadow)
- In utilities used only for internal operations (curl for health checks, tar/apt for build-time only)
- Theoretical/academic issues with no practical exploit path in this deployment model
- Unfixed upstream with no available patch from Debian or PyPI maintainers

No remaining CVE is exploitable through the application's exposed attack surface (HTTP API on port 8000, Streamlit on port 8501).

---

## 5. Database Image: pgvector CVE Analysis

### 5.1 Remediation Actions

| Action | Detail |
|--------|--------|
| Replaced `ankane/pgvector:latest` | Unmaintained image with 337 CVEs (9C, 96H, 87M, 145L) based on stale `debian:12-slim` |
| Built custom `mmorrisj/pgvector:0.8.1-pg16` | `postgres:16-trixie` base (Debian 13), pgvector 0.8.1 compiled from source (upgraded from 0.8.0) |
| Base image upgrade | Moved from `postgres:16-bookworm` (Debian 12) to `postgres:16-trixie` (Debian 13) for newer libc/OpenLDAP/libxml2 packages |
| Build tool removal | `build-essential`, `git`, `ca-certificates`, `postgresql-server-dev-16` purged after compilation |
| Runtime package reduction | Purged unused GnuPG tooling (`gnupg`, `gpg`, `gpg-wks-client`, `gpg-wks-server`) from final runtime layer |
| gosu removal | Removed Go-compiled `gosu` binary (Go 1.24.6) to reduce Go stdlib CVE exposure. Not needed when running as `USER postgres`. |
| Non-root user | `USER postgres` set in Dockerfile. Entrypoint handles initialization correctly as non-root. |
| Residual metadata cleanup | `dpkg --purge --force-all` on packages in `rc` state |
| Supply chain attestations | SBOM + max-mode provenance attached via `docker-container` buildx driver |
| Updated compose files | `docker-compose.yml` and `docker-compose.production.yml` use `mmorrisj/pgvector:0.8.1-pg16` |

### 5.1.1 Enterprise Scan CVE Closures (2026-02-23)

| CVE | Finding Source | Mitigation Status | Notes |
|-----|----------------|-------------------|-------|
| CVE-2025-7458 | Enterprise scanner | Partial / base-dependent | Mitigated in prior bookworm variant by removing `libsqlite3-0`. Current trixie-based image retains `libsqlite3-0` due to `util-linux -> liblastlog2-2` dependency chain; requires enterprise scanner validation on trixie package set. |
| CVE-2023-45853 | Enterprise scanner | Exception / Not affected | CVE targets MiniZip paths; image does not install `minizip` packages. Keep documented exception evidence in scan packet. |
| CVE-2023-2953 | Enterprise scanner | Mitigated | pgvector base moved from `postgres:16-bookworm` (`libldap-2.5-0` 2.5.13) to `postgres:16-trixie` (`libldap2` 2.6.10). |
| CVE-2026-0861 | Enterprise scanner | Exception / Not affected | Affected glibc DNS backend path is not used in this image (`/etc/nsswitch.conf` has `networks: files`), so exploit path is not reachable in default runtime configuration. |

### 5.1.2 CentOS 7 Host Compatibility Notes

The pgvector image changes are compatible with CentOS 7 hosts running a supported Docker Engine setup, with one important operational caveat for existing database volumes.

**Host runtime compatibility checks (CentOS 7):**

1. Kernel and storage driver prerequisites:
   - Ensure kernel is `3.10.0-514` or newer and Docker uses `overlay2`.
   - Ensure backing filesystem supports `d_type` (`xfs` with `ftype=1`).
2. Validate on target host:
   - `uname -r`
   - `docker info | egrep "Server Version|Storage Driver|Backing Filesystem|Cgroup Version"`
   - `xfs_info /var/lib/docker | grep -E "ftype=1|ftype=true"` (if XFS)

**PostgreSQL data compatibility caveat (important):**

Moving from a `bookworm`-based PostgreSQL image (glibc 2.36) to `trixie` (glibc 2.41) can trigger collation version mismatches on existing clusters. PostgreSQL documents that this can affect index correctness until reindexed.

If deploying against an existing `PGDATA` volume created on bookworm:

1. Backup first (`pg_dump`/snapshot).
2. Reindex affected databases (or all user databases in maintenance window).
3. Refresh collation version:
   - `ALTER DATABASE <db_name> REFRESH COLLATION VERSION;`

For fresh deployments (new empty `PGDATA`), no collation migration step is needed.

### 5.2 Remaining Vulnerabilities (51 total)

All 51 remaining CVEs originate from the official `postgres:16-trixie` base image. None were introduced by the pgvector extension or the custom build process.

#### 5.2.1 CRITICAL + HIGH: Go stdlib 1.24.6 (1C, 6H)

| CVE | Severity | Fixed In | Description |
|-----|:---:|:---:|-------------|
| CVE-2025-68121 | CRITICAL | Go 1.24.13 | Go stdlib vulnerability |
| CVE-2025-61729 | HIGH | Go 1.24.11 | Go stdlib vulnerability |
| CVE-2025-61726 | HIGH | Go 1.24.12 | Go stdlib vulnerability |
| CVE-2025-61725 | HIGH | Go 1.24.8 | Go stdlib vulnerability |
| CVE-2025-61723 | HIGH | Go 1.24.8 | Go stdlib vulnerability |
| CVE-2025-58188 | HIGH | Go 1.24.8 | Go stdlib vulnerability |
| CVE-2025-58187 | HIGH | Go 1.24.9 | Go stdlib vulnerability |

**Key context**: PostgreSQL is written in C, not Go. The Go stdlib is bundled into the official `postgres` Docker image by the PostgreSQL Docker maintainers for container entrypoint tooling and health check utilities. These CVEs:

- **Affect every `postgres:16` image on Docker Hub** -- official, pgvector, third-party. No tag or variant avoids them.
- **Are not present in bare-metal PostgreSQL installations** from RPM/DEB packages, as those do not include Go.
- **Are not network-exploitable** through PostgreSQL's port 5432. They require local code execution within the Go-compiled entrypoint tooling.
- **Will be resolved automatically** when the PostgreSQL Docker team rebuilds with Go >=1.24.13. No user action can fix this sooner.

**Assessment**: Accepted risk. Monitor for updated `postgres:16-trixie` base image. Rebuild and push `mmorrisj/pgvector` when the upstream fix is available.

#### 5.2.2 MEDIUM Severity (10)

9 of the 10 MEDIUM CVEs are additional Go stdlib vulnerabilities in the same `gosu` binary bundled in the base image layer (see Section 5.2.1 -- same root cause, same accepted risk). The remaining 1 MEDIUM is `tar` (CVE-2025-45582), the same unfixed Debian package assessed in Section 2.2.

#### 5.2.3 LOW Severity (34)

The 34 LOW CVEs are in Debian Trixie OS packages -- the same packages (glibc, openldap, systemd, krb5, coreutils, libxml2, libxslt, libgcrypt20, etc.) assessed in Section 2.3 above. The same relevance assessment applies: these are in OS utilities not invoked by PostgreSQL on untrusted input.

### 5.3 Alternative Approaches Evaluated

| Option | CVEs | Tradeoff | Decision |
|--------|:---:|----------|----------|
| `postgres:16-trixie` (current) | 1C 6H 10M 34L | Debian 13 base with newer packages (libldap 2.6.10, glibc 2.41). Resolves CVE-2023-2953 (OpenLDAP). | **Selected** |
| `postgres:16-bookworm` (previous) | 1C 6H 12M 40L | Debian 12 base. Older libldap (2.5.13), more OS-level CVEs. | Superseded by trixie |
| `postgres:16-alpine` | 1C 6H 11M 1L | Drops many LOWs (Alpine has fewer OS packages). Same Go stdlib issue. Uses musl libc -- risk of locale/collation incompatibility with existing database, potential data migration required. | Rejected -- collation risk outweighs LOW CVE reduction |
| `postgres:17-bookworm` | 1C 6H 12M 40L | Same CVE count. Major PG version change requires migration testing. | Not needed -- no CVE benefit |
| Host PostgreSQL (bare metal) | 0 Docker CVEs | Eliminates all Docker image CVEs including Go stdlib. However, pgvector extension is not available as a pre-built package for the CentOS 7 deployment host, and CentOS 7 is EOL (June 2024) with its own unpatched OS vulnerabilities. | Not feasible -- pgvector availability |

### 5.4 Database Image Deployment Risk Assessment

1. **Network exposure**: PostgreSQL listens on port 5432 within the Docker network. The Go stdlib CVEs are in container entrypoint tooling, not in the PostgreSQL wire protocol handler. An attacker with access to port 5432 interacts with PostgreSQL's C-based query engine, not the Go runtime.

2. **No public exposure**: The database container is not exposed to the internet. It communicates only with the application container via the Docker network.

3. **Read-heavy workload**: The database serves a read-heavy analytics dashboard. Write operations are performed by the ingestion pipeline running on the host, not through the containerized application.

4. **Container isolation**: The database container runs as the `postgres` user (non-root) with no privileged capabilities.

**Conclusion**: The `mmorrisj/pgvector:0.8.1-pg16` image is suitable for production deployment. The 1 CRITICAL and 6 HIGH vulnerabilities are in Go entrypoint tooling (not PostgreSQL), are not network-exploitable, and affect every postgres:16 Docker image universally. They will be resolved by an upstream rebuild.

---

## Appendix A: Commits

| Commit | Description |
|--------|-------------|
| `9d2edff` | Fix 52+ Docker CVEs: upgrade base image (3.11->3.13), packages, and remove build tools |
| `4c763da` | Bump pandas, numpy, psycopg2-binary for Python 3.13 wheel compatibility |
| `03d3661` | Upgrade setuptools/pip and purge binutils metadata to fix 41 more CVEs |
| `35f3e04` | Add CVE mitigation report and update deployment scripts |
| `aa4dfda` | Add custom pgvector Dockerfile and replace ankane/pgvector in compose |
| `aa1cb21` | Add non-root user to registry Dockerfile for Scout health score |
| `08e4fdd` | Fix CVE-2026-23949 (jaraco.context), add supply chain attestations |
| `c9b6340` | Add non-root user and remove gosu from pgvector Dockerfile |
| `4674fba` | Fix deployment bugs and harden admin user creation |
| `3f28d8f` | Bump image references to 1.5.2 |

## Appendix B: Files Modified

| File | Changes |
|------|---------|
| `docker/registry.Dockerfile` | Base image 3.11->3.13, torch>=2.6.0, build-essential purge + dpkg cleanup, setuptools/pip upgrade, supervisor via pip, non-root user |
| `docker/api.Dockerfile` | Base image 3.11->3.13, build-essential purge |
| `docker/dashboard.Dockerfile` | Base image 3.11->3.13 |
| `docker/production.Dockerfile` | Aligned with registry.Dockerfile: supervisor via pip, non-root user, build-essential purge + dpkg cleanup, setuptools/pip/jaraco.context upgrades |
| `requirements.txt` | Version bumps for fastapi, uvicorn, torch, pyarrow, psycopg2-binary; added pillow, filelock, wheel |
| `requirements-production.txt` | Version bumps for all runtime packages; added pillow, filelock, wheel |
| `server/main.py` | Python 3.13 compatibility (datetime.utcnow, Pydantic regex->pattern) |
| `server/auth.py` | Python 3.13 compatibility (datetime.utcnow) |
| `server/report_validator.py` | Python 3.13 compatibility (datetime.utcnow) |
| `docker/pgvector.Dockerfile` | Custom pgvector build: postgres:16-trixie base, build tool removal, gnupg removal, gosu removal, USER postgres |
| `docker-compose.yml` | Updated `db` service from `ankane/pgvector` to `mmorrisj/pgvector:0.8.1-pg16` |
| `docker-compose.production.yml` | Production deployment with pinned image tags |
| `scripts/create_admin.py` | Hardened admin user creation, added to registry Dockerfile |

## Appendix C: Scanner Output

### Application Image

```
Target:  mmorrisj/softpower-analytics:1.5.4
Digest:  df8f96c164d0
Platform: linux/amd64
Size:    1.2 GB
Packages: 331

Vulnerabilities: 0C 0H 1M 33L (34 total)
Base image:      python:3.13-slim (0C 0H 1M 21L)
Attestations:    SBOM + Provenance (max mode) attached
```

### Database Image

```
Target:  mmorrisj/pgvector:0.8.1-pg16
Digest:  dea01a7610bc
Platform: linux/amd64
Size:    536 MB
Packages: 190

Vulnerabilities: 1C 6H 10M 34L (51 total)
Base image:      postgres:16-trixie (1C 6H 10M 34L)
Attestations:    SBOM + Provenance attached

Previous image (ankane/pgvector:latest):
Vulnerabilities: 9C 96H 87M 145L (337 total)
```

### Combined Stack Totals

```
                    Application    Database    Combined
Critical:                  0           1           1
High:                      0           6           6
Medium:                    1          10          11
Low:                      33          34          67
Total:                    34          51          85

All Critical/High in database image are from Go stdlib in the
postgres:16-trixie base, affecting every postgres:16 image
on Docker Hub. Not network-exploitable via PostgreSQL port 5432.
```

Scanner: Docker Scout v1.19.0
Scan date: February 24, 2026
