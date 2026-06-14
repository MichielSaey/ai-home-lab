FROM python:3.11-slim

WORKDIR /app

COPY src/agents/agent_hub/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/agents/ /app/agents
COPY src/shared /app/shared
COPY src/agents/agent_hub/app.py /app/app.py

ENV PYTHONPATH=/app

EXPOSE 8001
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8001"]
