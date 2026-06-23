# AI Home Lab

Pure Python monorepo for home-lab MCP microservices, Odysseus integration, shared utilities, and tools. Chat and agents run on [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus); domain logic lives in MCP servers under `src/mcp-servers/`.

Further reading: [docs/DESIGN.md](docs/DESIGN.md) (architecture), [docs/PLAN.md](docs/PLAN.md) (execution and issues).

## Architecture

- **Odysseus** (`services/odysseus`) — self-hosted agent UI for interactive work (chat, presets, MCP client).
- **MCP servers** (`src/mcp-servers/`) — domain logic exposed over SSE on the internal Docker network.
- **Shared utilities** (`src/shared/`) — CUDA bootstrap and ffmpeg helpers for epub2audiobook.

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
| chromadb / searxng | bundled with Odysseus | Vector store, search |

## Running locally

1. Copy `.env.example` to `.env` and fill in values.
2. Vendor Odysseus (first run only):
   ```bash
   ./scripts/ensure-odysseus.sh
   ```
3. Start the full stack:
   ```bash
   docker compose up -d --build
   ```
4. Open `http://localhost:7000`
5. Admin password: `docker compose logs odysseus | grep -i password`
6. Odysseus admin → MCP → add `http://garmin-mcp:8000/sse`
7. Configure models in Odysseus (or `OLLAMA_BASE_URL` in `.env`)

### Spin up sections independently

```bash
# MCP servers only
docker compose -f src/mcp-servers/docker-compose.yml up -d --build

# Odysseus stack only (run ensure-odysseus.sh first)
docker compose -f services/docker-compose.yml up -d --build
```

## Python tools (devenv)

```bash
devenv shell
```

For epub2audiobook and Jupyter — not the Docker stack. See [docs/epub2audiobook.md](docs/epub2audiobook.md).

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
docker-compose.yml                    # root — includes mcp + services
src/mcp-servers/docker-compose.yml    # garmin-mcp (code lives alongside)
services/docker-compose.yml           # Odysseus stack (includes vendored compose)
casaos/docker-compose.yml             # optional CasaOS dashboard import
services/odysseus/                    # cloned by scripts/ensure-odysseus.sh (gitignored except .gitkeep)
```
