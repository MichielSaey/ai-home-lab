#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODYSSEUS_DIR="${ROOT}/services/odysseus"
ODYSSEUS_REPO="${ODYSSEUS_REPO:-https://github.com/pewdiepie-archdaemon/odysseus.git}"
ODYSSEUS_REF="${ODYSSEUS_REF:-main}"
# Odysseus still imports mcp.client.streamable_http.streamablehttp_client.
# Unpinned `mcp` resolves to 2.0+, which removed that name and Odysseus
# reports the ImportError as "mcp package not installed".
ODYSSEUS_MCP_PIN="${ODYSSEUS_MCP_PIN:-mcp>=1.9,<2}"

pin_odysseus_mcp_sdk() {
  local req="${ODYSSEUS_DIR}/requirements.txt"
  if [[ ! -f "${req}" ]]; then
    return 0
  fi
  python3 - "${req}" "${ODYSSEUS_MCP_PIN}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
pinned = sys.argv[2]
text = path.read_text()
new, n = re.subn(r"(?m)^mcp(?:\s*[<>=!~].*)?$", pinned, text, count=1)
if n == 0:
    new = text.rstrip() + f"\n{pinned}\n"
if new != text:
    path.write_text(new)
    print(f"Pinned Odysseus MCP SDK to {pinned}")
else:
    print(f"Odysseus MCP SDK already pinned ({pinned})")
PY
}

if [[ -f "${ODYSSEUS_DIR}/docker-compose.yml" ]]; then
  current_ref="$(git -C "${ODYSSEUS_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "Odysseus already present at ${ODYSSEUS_DIR} (${current_ref})"
  if [[ "${ODYSSEUS_UPDATE:-0}" == "1" ]]; then
    echo "Updating Odysseus to ${ODYSSEUS_REF}..."
    git -C "${ODYSSEUS_DIR}" fetch --depth 1 origin "${ODYSSEUS_REF}"
    git -C "${ODYSSEUS_DIR}" checkout FETCH_HEAD
  fi
  pin_odysseus_mcp_sdk
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
pin_odysseus_mcp_sdk
