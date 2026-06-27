#!/bin/sh
# Start the MCP server directly. Authentication is non-interactive: server.py
# logs in from GARMIN_EMAIL / GARMIN_PASSWORD lazily on the first tool call, so
# the SSE server binds port 8000 immediately and the healthcheck passes.
# (The upstream `garmin-mcp-auth` helper is intentionally NOT used here — it
# prompts for credentials/MFA and would block container startup forever.)
set -eu
exec python server.py
