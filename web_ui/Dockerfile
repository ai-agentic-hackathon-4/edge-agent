FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server py to web_ui directory to preserve relative path logic
RUN mkdir -p web_ui
COPY server.py web_ui/

# We expect logs and envs to be mounted at /app/scripts/logs and /app/agent/.env
ENV FIRESTORE_DATABASE="ai-agentic-hackathon-4-db"

# Run from /app to ensure relative paths work if CWD matters, or use absolute path
WORKDIR /app
CMD ["python", "web_ui/server.py", "--host", "0.0.0.0", "--port", "8001"]
