#!/bin/sh
set -e

node /app/apps/api/dist/index.js &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd /app/apps/web
exec pnpm exec vite preview --host 0.0.0.0 --port "${MCP_WORKBENCH_WEB_PORT:-5173}"
