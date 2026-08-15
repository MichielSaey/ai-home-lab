#!/usr/bin/env bash
# Source from deploy / local shells after loading .env.
# Enables optional Compose profiles when their secrets are present.
#
# Usage:
#   set -a && source .env && set +a
#   # shellcheck source=/dev/null
#   source scripts/compose-profiles.sh
#   docker compose up -d

# Todoist MCP — profile "todoist" (see src/mcp-servers/docker-compose.yml)
if [ -n "${TODOIST_API_KEY:-}" ]; then
  case ",${COMPOSE_PROFILES:-}," in
    *,todoist,*) ;;
    *)
      if [ -n "${COMPOSE_PROFILES:-}" ]; then
        COMPOSE_PROFILES="${COMPOSE_PROFILES},todoist"
      else
        COMPOSE_PROFILES="todoist"
      fi
      ;;
  esac
  export COMPOSE_PROFILES
  echo ">> compose profile todoist enabled (TODOIST_API_KEY set)"
else
  echo ">> compose profile todoist skipped (TODOIST_API_KEY empty)"
fi
