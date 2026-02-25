# Enterprise CVE Exception Request

Date: February 24, 2026
System: SoftPower Analytics container deployment (enterprise network)  
Prepared for: Security review and deployment approval

## Scope

This exception request covers HIGH and medium-severity CVEs that may still be reported by enterprise scanners after rebuilding/publishing current images.

Target images for this exception package (replace with exact scanned digests):

- `mmorrisj/softpower-analytics:1.5.4` (application image)
- `mmorrisj/pgvector:0.8.1-pg16` (database image)

## Required Attachments

Attach scanner output generated from the exact deployed image digests:

- Enterprise scan report (full)
- CVE-level evidence report for listed CVEs only
- Image digest evidence (`docker inspect` output)

## CVEs Requested for Exception

The entries below are the current exception candidates based on package presence and dependency constraints in Debian-based runtime images.

| CVE | Severity | Package Family | Image(s) | Disposition | Rationale |
|---|---|---|---|---|---|
| CVE-2026-0861 | HIGH | `glibc` (`libc-bin`, `libc6`, `libc-l10n`, `locales`) | app (2), pgvector (4) | Exception | Integer overflow in memalign requires attacker control of both size (near PTRDIFF_MAX) and alignment (>=2^62) arguments — not reachable from application code or network input. Debian classified as "minor issue / no-dsa". Fix in glibc 2.42-8+ (sid), not yet in trixie (2.41-12+deb13u1). |
| CVE-2025-10911 | MEDIUM | `libxslt` | pgvector | Exception | Runtime dependency in base image; removal would remove PostgreSQL package chain. |
| CVE-2025-14104 | MEDIUM | `util-linux` | app, pgvector | Exception | Core OS utility package; not safely removable from runtime base. |
| CVE-2025-15281 | MEDIUM | `glibc` / `libc` | app, pgvector | Exception | Core C runtime; requires upstream distro update, not application-layer remediation. |
| CVE-2025-7709 | MEDIUM | `sqlite` (`libsqlite3-0`) | app, pgvector | Exception (if scanner still flags) | Required dependency chain on Debian trixie (`util-linux -> liblastlog2-2 -> libsqlite3-0`). |
| CVE-2026-0915 | MEDIUM | `glibc` / `libc` | app, pgvector | Exception | Core libc path; requires upstream distro fix. |
| CVE-2026-0990 | MEDIUM | `libxml2` | pgvector | Exception | Transitive runtime dependency; removing it removes PostgreSQL dependencies. |
| CVE-2026-27171 | MEDIUM | `zlib` | app, pgvector | Exception | Foundational OS dependency required by package manager/runtime stack. |

## Python-Binary CVEs (Grype MEDIUM — Not Actionable)

These appear in Grype scans against the CPython binary shipped in the `python:3.13-slim` base image. They are **not exploitable** in this application because the affected stdlib modules are never imported.

| CVE | Module | Exploitable? | Rationale |
|---|---|---|---|
| CVE-2025-15366 | `imaplib` | No | IMAP command injection via newline chars. Application does not import or use `imaplib`. No IMAP connections made. |
| CVE-2025-15367 | `poplib` | No | POP3 command injection. Application does not import or use `poplib`. No POP3 connections made. |
| CVE-2026-1299 | `email` headers | No | Email header injection via unquoted newlines. Application does not import or use `email` module for header construction. |

**Action**: No exception needed. Document as "not applicable — affected code paths unused" if scanner requires explicit disposition.

## CVEs Not Requested for Exception (Expected Closed)

These should be validated as closed by the enterprise scan after image refresh:

| CVE | Expected Status | Notes |
|---|---|---|
| CVE-2023-50495 | Closed | `ncurses` on current Debian 13 package line. |
| CVE-2024-10041 | Closed | `pam` on current Debian 13 package line. |
| CVE-2025-13151 | Eliminated | `libtasn1` removed from app image: `postgresql-client` removed → `libpq5` removed → `libldap2` / Kerberos chain removed → `libtasn1` removed. `psycopg2-binary` bundles its own `libpq`; no CLI tools used at runtime. |
| CVE-2025-14831 | Closed | `gnutls` package line updated. |
| CVE-2025-30258 | Closed | `gnupg` removed from runtime images. |
| CVE-2025-68972 | Closed / Not present | `gnupg2` package not installed in runtime images. |
| CVE-2025-9820 | Closed | `gnutls` package line updated. |

## Technical Constraints

1. Base image inherited dependencies:
- Remaining CVEs are primarily in base OS/runtime packages required by Debian and PostgreSQL packaging.

2. Safe-removal limits:
- Attempted package purges for these libraries remove or break core runtime dependencies (PostgreSQL/app startup risk).

3. Upstream-fix dependency:
- Several CVEs require upstream Debian package updates rather than application code changes.

## Compensating Controls

1. Network isolation and least exposure:
- Only required service ports are exposed (8000, 8501).
- Database is internal to Docker network (not exposed to host in production compose).
- No direct user input reaches glibc allocation functions with attacker-controlled alignment.

2. Non-root container execution:
- App container: runs as `appuser` (non-root) via `USER appuser`.
- Database container: runs as `postgres` (non-root) via `USER postgres`.
- gosu binary removed from pgvector image (eliminates Go stdlib attack surface).

3. Minimal runtime footprint:
- Build-time tooling (`build-essential`, `git`, `gnupg`) removed from all runtime images.
- `dpkg --purge` on residual configs prevents scanners from flagging removed packages.
- Supervisor installed from PyPI (not Debian apt) to avoid pulling 36 extra packages.
- `postgresql-client` removed from app image: `psycopg2-binary` bundles its own `libpq`; eliminates `libpq5` → `libldap2` → `libtasn1` and Kerberos library chains from the app image.
- `locales` / `libc-l10n` retained in pgvector only because postgresql-16 hard-depends on them.

4. Deployment controls:
- Image tags/digests are pinned for release approval.
- Re-scan required before each production promotion.
- Weekly base image rebuild cadence to pick up upstream fixes.
- `no-new-privileges:true` set on all production containers (prevents SUID/SGID privilege escalation).
- `cap_drop: ALL` on all production containers (eliminates all Linux capability escalation paths).
- pgvector source SHA verified at build time (`778dacf`) against pinned `ARG PGVECTOR_SHA` (supply-chain hardening).

## Operational Risk Statement

Residual risk is accepted for the listed CVEs because:

- No safe package-level mitigation exists without destabilizing required runtime dependencies, and
- Applicable fixes are pending from upstream distribution maintainers, and
- Compensating controls materially reduce practical exploitability in this deployment model.

## Revalidation Plan

- Re-scan cadence: every release and at least monthly while exceptions remain open.
- Trigger for early reassessment:
  - Upstream fix published for an excepted CVE
  - CVE enters CISA KEV or equivalent exploited-in-the-wild catalog
  - Architecture change that increases attack surface

## Evidence Commands (for Approval Packet)

```bash
# Replace tags with exact release tags/digests used in deployment
docker pull mmorrisj/softpower-analytics:1.5.4
docker pull mmorrisj/pgvector:0.8.1-pg16

docker inspect --format='{{index .RepoDigests 0}}' mmorrisj/softpower-analytics:1.5.4
docker inspect --format='{{index .RepoDigests 0}}' mmorrisj/pgvector:0.8.1-pg16

# Package evidence snapshots
docker run --rm mmorrisj/softpower-analytics:1.5.4 dpkg -l > app-dpkg.txt
docker run --rm mmorrisj/pgvector:0.8.1-pg16 dpkg -l > db-dpkg.txt
```

## Approval Sign-Off

Security reviewer: ____________________  
Date: ____________________  
Decision: Approved / Rejected  
Conditions (if any): ______________________________________________

