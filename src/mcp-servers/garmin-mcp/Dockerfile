FROM ghcr.io/astral-sh/uv:python3.14-trixie
WORKDIR /app
COPY src/mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
COPY src/mcp-servers/garmin-mcp/build.sh /app/build.sh
COPY src/mcp-servers/garmin-mcp/post-build.sh /app/post-build.sh
RUN if [ -f /app/build.sh ]; then chmod +x /app/build.sh && /app/build.sh; fi

# Install Python requirements early so layers are cached when requirements don't change
COPY src/mcp-servers/garmin-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src/mcp-servers/garmin-mcp/errors.py /app/errors.py
COPY src/mcp-servers/garmin-mcp/hr_zones.py /app/hr_zones.py
COPY src/mcp-servers/garmin-mcp/nutrition_matrix.py /app/nutrition_matrix.py
COPY src/mcp-servers/garmin-mcp/rest_shim.py /app/rest_shim.py
COPY src/mcp-servers/garmin-mcp/server.py /app/server.py
COPY src/mcp-servers/garmin-mcp/training_plan.py /app/training_plan.py
COPY src/mcp-servers/garmin-mcp/training_status.py /app/training_status.py
COPY src/mcp-servers/garmin-mcp/workout_builder.py /app/workout_builder.py
COPY src/mcp-servers/garmin-mcp/workout_templates.py /app/workout_templates.py
COPY src/mcp-servers/garmin-mcp/zones.py /app/zones.py
COPY src/mcp-servers/garmin-mcp/prompts/ /app/prompts/
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000
CMD ["/bin/sh", "-c", "if [ -f /app/post-build.sh ]; then chmod +x /app/post-build.sh && /app/post-build.sh; fi"]
