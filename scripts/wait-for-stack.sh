#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

APP_PORT="${APP_PORT:-7000}"
APP_BIND="${APP_BIND:-127.0.0.1}"
TIMEOUT="${DEPLOY_WAIT_TIMEOUT:-300}"
INTERVAL=5
elapsed=0

echo "Waiting up to ${TIMEOUT}s for containers (best-effort compose --wait)..."
# Optional MCP sidecars may be unhealthy without API keys; do not fail the job here.
docker compose up --wait --wait-timeout "${TIMEOUT}" >/dev/null 2>&1 || \
  echo "docker compose --wait incomplete; falling back to Odysseus HTTP check"

odysseus_url="http://${APP_BIND}:${APP_PORT}/"
echo "Checking Odysseus at ${odysseus_url} ..."
while (( elapsed < TIMEOUT )); do
  if curl -sf --max-time 5 "${odysseus_url}" >/dev/null; then
    echo "Odysseus is responding."
    exit 0
  fi
  sleep "${INTERVAL}"
  elapsed=$((elapsed + INTERVAL))
done

echo "ERROR: Odysseus did not become ready within ${TIMEOUT}s" >&2
docker compose ps >&2
exit 1
