# AI Home Lab

Pure Python monorepo for home lab MCP microservices, shared utilities, and tools. Chat and agents run on [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus); domain logic lives in MCP servers under `src/mcp-servers/`.

Further reading: [docs/DESIGN.md](docs/DESIGN.md) (architecture), [docs/PLAN.md](docs/PLAN.md) (execution and issues).

## Quick start

```bash
cp .env.example .env          # GARMIN_EMAIL, GARMIN_PASSWORD, etc.
./scripts/ensure-odysseus.sh
docker compose up -d --build
```

1. Open `http://localhost:7000`
2. Admin password: `docker compose logs odysseus | grep -i password`
3. Odysseus admin → MCP → add `http://garmin-mcp:8000/sse`
4. Configure models in Odysseus (or `OLLAMA_BASE_URL` / `LLM_HOST` in `.env`)

## Services

| Service | Port | Role |
|---------|------|------|
| Odysseus | 7000 | Chat, agents, MCP client, memory |
| garmin-mcp | 8000 (internal) | Garmin Connect tools + weekly report |
| chromadb / searxng / ntfy | bundled with Odysseus | Vector store, search, notifications |

Expose Odysseus via Tailscale or Cloudflare Tunnel. MCP ports stay internal (`edge` / `mcp-internal` networks).

## Python tools (devenv)

```bash
devenv shell
```

For epub2audiobook and Jupyter — not the Docker stack. See [docs/epub2audiobook.md](docs/epub2audiobook.md).

## Deploy

Self-hosted GitHub Actions runner (`self-hosted`, `linux`) runs `ensure-odysseus.sh` and `docker compose up -d --build` on push to `main`.
