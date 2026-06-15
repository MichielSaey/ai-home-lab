#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="${ROOT}/vendor/odysseus"
REPO="https://github.com/pewdiepie-archdaemon/odysseus.git"
BRANCH="${ODYSSEUS_GIT_REF:-dev}"

if [[ -d "${VENDOR}/.git" ]]; then
  echo "Odysseus vendor checkout already present at ${VENDOR}"
  exit 0
fi

mkdir -p "${ROOT}/vendor"
echo "Cloning Odysseus (${BRANCH}) into ${VENDOR}..."
git clone --depth 1 --branch "${BRANCH}" "${REPO}" "${VENDOR}"
