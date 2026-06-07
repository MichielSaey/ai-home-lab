FROM python:3.11-slim
WORKDIR /app
COPY agents/garmin-trainer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agents/garmin-trainer/app.py /app/app.py
COPY agents/garmin-trainer/agent.py /app/agent.py
COPY shared /app/shared
ENV PYTHONPATH=/app
EXPOSE 8001
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8001"]
