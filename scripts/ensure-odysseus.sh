#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODYSSEUS_DIR="${ROOT}/services/odysseus"
ODYSSEUS_REPO="${ODYSSEUS_REPO:-https://github.com/pewdiepie-archdaemon/odysseus.git}"
ODYSSEUS_REF="${ODYSSEUS_REF:-main}"

if [[ -f "${ODYSSEUS_DIR}/docker-compose.yml" ]]; then
  current_ref="$(git -C "${ODYSSEUS_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "Odysseus already present at ${ODYSSEUS_DIR} (${current_ref})"
  if [[ "${ODYSSEUS_UPDATE:-0}" == "1" ]]; then
    echo "Updating Odysseus to ${ODYSSEUS_REF}..."
    git -C "${ODYSSEUS_DIR}" fetch --depth 1 origin "${ODYSSEUS_REF}"
    git -C "${ODYSSEUS_DIR}" checkout FETCH_HEAD
  fi
  exit 0
fi

echo "Cloning Odysseus (${ODYSSEUS_REF}) into ${ODYSSEUS_DIR}..."
mkdir -p "${ODYSSEUS_DIR}"

# The repo tracks services/odysseus/.gitkeep, so the directory may exist but
# not be a clone yet. Keep persisted data/logs; remove everything else.
if [[ -d "${ODYSSEUS_DIR}" ]]; then
  shopt -s dotglob nullglob
  for entry in "${ODYSSEUS_DIR}"/*; do
    [[ -e "${entry}" ]] || continue
    base="$(basename "${entry}")"
    if [[ "${base}" == "data" || "${base}" == "logs" ]]; then
      continue
    fi
    rm -rf "${entry}"
  done
  shopt -u dotglob nullglob
fi

clone_dir="$(mktemp -d)"
trap 'rm -rf "${clone_dir}"' EXIT
git clone --depth 1 --branch "${ODYSSEUS_REF}" "${ODYSSEUS_REPO}" "${clone_dir}"
shopt -s dotglob
for entry in "${clone_dir}"/*; do
  mv "${entry}" "${ODYSSEUS_DIR}/"
done
shopt -u dotglob
trap - EXIT
rm -rf "${clone_dir}"

echo "Odysseus ready."
