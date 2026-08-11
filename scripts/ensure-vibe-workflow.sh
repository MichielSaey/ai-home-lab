#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIBE_DIR="${ROOT}/services/vibe-workflow"
VIBE_REPO="${VIBE_WORKFLOW_REPO:-https://github.com/SamurAIGPT/Vibe-Workflow.git}"
VIBE_REF="${VIBE_WORKFLOW_REF:-main}"

if [[ -f "${VIBE_DIR}/docker-compose.yml" ]]; then
  current_ref="$(git -C "${VIBE_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "Vibe-Workflow already present at ${VIBE_DIR} (${current_ref})"
  if [[ "${VIBE_WORKFLOW_UPDATE:-0}" == "1" ]]; then
    echo "Updating Vibe-Workflow to ${VIBE_REF}..."
    git -C "${VIBE_DIR}" fetch --depth 1 origin "${VIBE_REF}"
    git -C "${VIBE_DIR}" checkout FETCH_HEAD
  fi
  exit 0
fi

echo "Cloning Vibe-Workflow (${VIBE_REF}) into ${VIBE_DIR}..."
mkdir -p "${VIBE_DIR}"

if [[ -d "${VIBE_DIR}" ]]; then
  shopt -s dotglob nullglob
  for entry in "${VIBE_DIR}"/*; do
    [[ -e "${entry}" ]] || continue
    base="$(basename "${entry}")"
    if [[ "${base}" == "data" ]]; then
      continue
    fi
    rm -rf "${entry}"
  done
  shopt -u dotglob nullglob
fi

clone_dir="$(mktemp -d)"
trap 'rm -rf "${clone_dir}"' EXIT
git clone --depth 1 --branch "${VIBE_REF}" "${VIBE_REPO}" "${clone_dir}"
shopt -s dotglob
for entry in "${clone_dir}"/*; do
  mv "${entry}" "${VIBE_DIR}/"
done
shopt -u dotglob
trap - EXIT
rm -rf "${clone_dir}"

echo "Vibe-Workflow ready."
