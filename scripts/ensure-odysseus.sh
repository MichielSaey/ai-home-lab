#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODYSSEUS_DIR="${ROOT}/services/odysseus"
ODYSSEUS_REPO="${ODYSSEUS_REPO:-https://github.com/pewdiepie-archdaemon/odysseus.git}"
ODYSSEUS_REF="${ODYSSEUS_REF:-main}"

if [[ -f "${ODYSSEUS_DIR}/docker-compose.yml" ]]; then
  echo "Odysseus already present at ${ODYSSEUS_DIR}"
  exit 0
fi

echo "Cloning Odysseus (${ODYSSEUS_REF}) into ${ODYSSEUS_DIR}..."
mkdir -p "$(dirname "${ODYSSEUS_DIR}")"
git clone --depth 1 --branch "${ODYSSEUS_REF}" "${ODYSSEUS_REPO}" "${ODYSSEUS_DIR}"

echo "Odysseus ready."
