FROM ghcr.io/astral-sh/uv:python3.14-trixie
WORKDIR /app
COPY mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
COPY mcp-servers/garmin-mcp/build.sh /app/build.sh
COPY mcp-servers/garmin-mcp/post-build.sh /app/post-build.sh
RUN if [ -f /app/build.sh ]; then chmod +x /app/build.sh && /app/build.sh; fi

# Install Python requirements early so layers are cached when requirements don't change
COPY mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY mcp-servers/garmin-mcp/server.py /app/server.py
COPY mcp-servers/garmin-mcp/zones.py /app/zones.py
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000
CMD ["/bin/sh", "-c", "if [ -f /app/post-build.sh ]; then chmod +x /app/post-build.sh && /app/post-build.sh; fi"]