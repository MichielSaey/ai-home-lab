FROM node:22-bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@9 --activate

WORKDIR /src
ARG MCP_WORKBENCH_REF=main
RUN git clone --depth 1 --branch "${MCP_WORKBENCH_REF}" https://github.com/raeseoklee/mcp-workbench.git .

RUN pnpm install --frozen-lockfile
RUN pnpm build

FROM node:22-bookworm-slim

RUN corepack enable && corepack prepare pnpm@9 --activate

WORKDIR /app
COPY --from=build /src /app

COPY mcp-servers/mcp-workbench/start.sh /start.sh
COPY mcp-servers/mcp-workbench/garmin-mcp.yaml /specs/garmin-mcp.yaml
RUN chmod +x /start.sh

ENV PORT=3001
ENV MCP_WORKBENCH_WEB_PORT=5173

EXPOSE 5173 3001

CMD ["/start.sh"]
