FROM ghcr.io/astral-sh/uv:python3.14-trixie
WORKDIR /app
COPY src/mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
COPY src/mcp-servers/garmin-mcp/build.sh /app/build.sh
COPY src/mcp-servers/garmin-mcp/post-build.sh /app/post-build.sh
RUN if [ -f /app/build.sh ]; then chmod +x /app/build.sh && /app/build.sh; fi

# Install Python requirements early so layers are cached when requirements don't change
COPY src/mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
# Copy all Python modules in one step so new files (e.g. weather.py) cannot be
# forgotten individually and break container health on startup.
COPY src/mcp-servers/garmin-mcp/*.py /app/
COPY src/mcp-servers/garmin-mcp/prompts/ /app/prompts/
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000
ENV MCP_TRANSPORT=streamable-http
CMD ["/bin/sh", "-c", "if [ -f /app/post-build.sh ]; then chmod +x /app/post-build.sh && /app/post-build.sh; fi"]
