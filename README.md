# AI Home Lab

A Python monorepo for home-lab MCP microservices, Odysseus integration, and shared utilities.

## Architecture

- **Odysseus** (`services/odysseus`) — self-hosted agent UI for interactive work (chat, presets, MCP client).
- **MCP servers** (`mcp-servers/`) — domain logic exposed over SSE on the internal Docker network.
- **Shared utilities** (`shared/`) — SQLite profiles, Fernet encryption, audiobook helpers.

See [docs/DESIGN.md](docs/DESIGN.md) for the full system design.

### Network and access model

- **edge** — Odysseus, MCP servers (SSE endpoint); internal service discovery.
- **mcp-internal** — MCP servers only; `internal: true`, not reachable from the host.
- Expose **Odysseus** (port 7000) and **ntfy** (port 8091) via Tailscale. Do not publish MCP ports publicly.

## Services

| Service | Port | Description |
|---------|------|-------------|
| Odysseus | 7000 | Agent UI, memory, MCP client |
| ntfy | 8091 | Push notifications (bundled with Odysseus) |
| garmin-mcp | 8000 (internal) | Garmin Connect MCP server |

## Running locally

1. Copy `.env.example` to `.env` and fill in values.
2. Generate a Fernet key and set `MASTER_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Vendor Odysseus (first run only):
   ```bash
   ./scripts/ensure-odysseus.sh
   ```
4. Start the full stack:
   ```bash
   docker compose up -d --build
   ```

### Spin up sections independently

```bash
# MCP servers only
docker compose -f mcp-servers/docker-compose.yml up -d --build

# Odysseus stack only (run ensure-odysseus.sh first)
docker compose -f services/docker-compose.yml up -d --build
```

## Odysseus setup

After the stack is running:

1. Open Odysseus at `http://localhost:7000` (or your Tailscale address).
2. Configure LLM provider in Settings.
3. Add MCP server: `http://garmin-mcp:8000/sse` (Admin → MCP Servers).

## Self-hosted GitHub Actions (CasaOS)

1. Install a GitHub Actions runner on your CasaOS server and register it to this repo.
2. Ensure the runner has the `self-hosted` and `linux` labels.
3. Make sure the runner user can run Docker.
4. Place a `.env` file in the repo checkout directory on the server (the workflow does not create secrets).
5. Push to `master` or trigger the workflow manually to deploy via Docker Compose.

The deploy workflow vendors Odysseus, starts the stack, waits for health checks, and optionally sends an ntfy ping when `NTFY_DEPLOY_TOPIC` is set in `.env`.

### CasaOS dashboard (optional)

To add a CasaOS tile pointing at Odysseus, import `casaos/docker-compose.yml` via **App Store → Custom app → Install a customized app**. The GitHub Actions runner deploy is the primary path; the CasaOS import is optional for dashboard access.

### Pinning Odysseus

Set `ODYSSEUS_REF` in `.env` to a branch, tag, or commit SHA. To update an existing clone:

```bash
ODYSSEUS_UPDATE=1 ./scripts/ensure-odysseus.sh
```

### Backups

Persisted data lives outside git:

| Path | Contents |
|------|----------|
| `services/odysseus/data/` | Odysseus DB, uploads, SSH keys, model cache |
| `services/odysseus/logs/` | Odysseus logs |
| Docker volumes | ChromaDB, SearXNG, ntfy (created by Odysseus compose) |

Include these paths in your CasaOS or homelab backup routine.

## Compose layout

```
docker-compose.yml              # root — includes mcp + services
mcp-servers/docker-compose.yml  # garmin-mcp
services/docker-compose.yml     # includes vendored Odysseus compose
casaos/docker-compose.yml       # optional CasaOS dashboard import
services/odysseus/              # cloned by scripts/ensure-odysseus.sh (gitignored)
```
