#!/usr/bin/env bash
set -euo pipefail

log() { printf '>>> [install] %s\n' "$*"; }

log "start"

# Single-user, non-interactive — suitable for cloud agent containers
if ! command -v nix-env >/dev/null 2>&1; then
  log "installing Nix (single-user, non-interactive)"
  curl -L https://nixos.org/nix/install | sh -s -- --no-daemon --yes
fi

# Load Nix into this shell session
if [ -e "${HOME}/.nix-profile/etc/profile.d/nix.sh" ]; then
  # shellcheck disable=SC1091
  . "${HOME}/.nix-profile/etc/profile.d/nix.sh"
fi

if ! command -v nix-env >/dev/null 2>&1; then
  echo "ERROR: nix-env still not on PATH after install" >&2
  exit 127
fi

log "nix version: $(nix --version)"

if ! command -v devenv >/dev/null 2>&1; then
  log "installing devenv"
  nix-env -iA devenv -f https://github.com/NixOS/nixpkgs/tarball/nixpkgs-unstable
fi

log "devenv version: $(devenv --version)"

cd /workspace

log "running devenv test"
devenv test

log "complete"
