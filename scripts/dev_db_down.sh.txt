#!/usr/bin/env bash
# Tear down the isolated agent dev DB created by dev_db_up.sh.
# Stops + removes the container and deletes the named volume so the
# next dev_db_up.sh starts from a clean copy of the source.
#
# Honors the same env var overrides as dev_db_up.sh:
#   AGENT_TEST_CONTAINER (default softpower_db_agent_test)
#   AGENT_TEST_VOLUME    (default postgres_data_agent_test)

set -euo pipefail

TEST_CONTAINER="${AGENT_TEST_CONTAINER:-softpower_db_agent_test}"
TEST_VOLUME="${AGENT_TEST_VOLUME:-postgres_data_agent_test}"

log()  { printf "\033[1;34m[dev-db-down]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[dev-db-down]\033[0m %s\n" "$*"; }

command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }

if docker inspect "$TEST_CONTAINER" >/dev/null 2>&1; then
  log "stopping + removing container $TEST_CONTAINER"
  docker rm -f "$TEST_CONTAINER" >/dev/null
else
  warn "container '$TEST_CONTAINER' not found (already gone)"
fi

if docker volume inspect "$TEST_VOLUME" >/dev/null 2>&1; then
  log "removing volume $TEST_VOLUME"
  docker volume rm "$TEST_VOLUME" >/dev/null
else
  warn "volume '$TEST_VOLUME' not found (already gone)"
fi

log "done. Run scripts/dev_db_up.sh to recreate."
