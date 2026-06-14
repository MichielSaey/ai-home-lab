# AI Home Lab

A pure Python monorepo for home lab agents, MCP microservices, and shared utilities. This repository contains a Garmin-focused coach UI, a local-only ADHD assistant placeholder, and a Garmin MCP server on an internal Docker network.

## Architecture
- Application code lives under `src/`.
- Agents live in `src/agents/` and expose Chainlit UIs.
- MCP servers live in `src/mcp-servers/` and are only reachable on the internal Docker network.
- Shared utilities live in `src/shared/` (SQLite profiles, Fernet encryption).

### Network and access model
- `garmin-trainer` listens on port 8001 and is intended for Cloudflare Tunnel exposure.
- `adhd-life-aid` listens on port 8002 and is intended for Tailscale-only access.
- MCP servers are attached to the `mcp-internal` network, which is marked `internal: true` so they are not reachable from the host.

### Zero-trust security model
- User credentials are symmetrically encrypted with `cryptography.Fernet` using `MASTER_KEY` from `.env`.
- Encrypted secrets are stored in SQLite and never hashed or logged.
- MCP servers do not publish ports to the host; only agents can reach them.
- Only the edge-facing agents bind host ports (8001 and 8002).

## Services
- `garmin-trainer`: Chainlit UI for coaching. Port 8001.
- `adhd-life-aid`: Local-only placeholder service. Port 8002.
- `garmin-mcp`: MCP server exposing Garmin Connect data. Internal network only.

## Running locally
1. Copy `.env.example` to `.env` and fill in values.
2. Generate a Fernet key and set `MASTER_KEY`:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. Start the stack:
   `docker compose up -d --build`

## LiteLLM proxy (optional)
If you use a self-hosted LiteLLM proxy, set these environment variables in `.env`:
- `LITELLM_API_BASE` (example: `http://your-proxy:4000/v1`)
- `LITELLM_API_KEY`
- `LITELLM_MODEL`
When set, the Garmin trainer routes requests through the LiteLLM proxy.

## Self-hosted GitHub Actions
1. Install a GitHub Actions runner on your host and register it to this repo.
2. Ensure the runner has the `self-hosted` and `linux` labels.
3. Make sure the runner user can run Docker.
4. Push to `main` or trigger the workflow manually to deploy via Docker Compose.

## Langflow migration note
The Garmin coach baseline mirrors the original Langflow graph by pulling a weekly Garmin report and combining it with user profile context inside a LangGraph `StateGraph`.
