# MCP dev UI (Garmin testing)

Interactive testing for **garmin-mcp**. Enabled via Compose `dev` profile.

## Quick start

```bash
docker compose --profile dev up -d garmin-mcp mcp-inspector garmin-mcp-ui
```

Open **http://localhost:6280** — redirects to MCP Inspector with garmin-mcp pre-filled.

Then click **Connect** once. After that you can:

   - **Tools** → `get_weekly_stats`, `get_activities`, `get_weekly_report`, …

## URLs

| URL | What |
|-----|------|
| **http://localhost:6280** | Start here (garmin pre-configured) |
| http://localhost:6274/?transport=sse&serverUrl=http://garmin-mcp:8000/sse | Direct Inspector link (bookmark this) |
| http://localhost:5173 | MCP Workbench — **not** for garmin-mcp (see below) |

## Why not plain localhost:6274?

The Inspector defaults to a demo stdio server (`mcp-server-everything`). Garmin uses SSE on the Docker network (`garmin-mcp:8000/sse`). The proxy inside the Inspector container reaches that hostname; your browser cannot use `localhost:8000` for garmin because the MCP server is not published to the host.

Use the **6280** redirect or the query-param URL above.

## MCP Workbench

Workbench (`:5173`) is bundled for YAML test specs and its demo MCP. Its HTTP client does not yet work with FastMCP servers, so use **MCP Inspector** for Garmin.

## CLI (no browser)

```bash
docker run --rm --network ai-home-lab_edge \
  ghcr.io/modelcontextprotocol/inspector:0.14.1 --cli \
  http://garmin-mcp:8000/sse --method tools/list
```

## Rebuild garmin-mcp

```bash
docker compose --profile dev build garmin-mcp
docker compose --profile dev up -d garmin-mcp
```
