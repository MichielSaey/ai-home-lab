# actual-mcp with @actual-app/api matched to actual-server 26.5.x.
# Upstream image ships API 26.3.0, which fails against server 26.5.2
# (out-of-sync-migrations).
FROM sstefanov/actual-mcp:latest

WORKDIR /app
RUN npm install @actual-app/api@26.5.2
