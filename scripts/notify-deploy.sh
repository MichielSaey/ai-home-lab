#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

status="${1:-success}"
message="${2:-Deploy finished}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

topic="${NTFY_DEPLOY_TOPIC:-}"
if [[ -z "${topic}" ]]; then
  exit 0
fi

base_url="${NTFY_BASE_URL:-http://127.0.0.1:8091}"
priority="default"
if [[ "${status}" != "success" ]]; then
  priority="high"
fi

curl -fsS \
  -H "Title: ai-home-lab deploy" \
  -H "Priority: ${priority}" \
  -d "${message}" \
  "${base_url%/}/${topic}"
