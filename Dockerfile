FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment variables for ADK/Vertex AI
ENV PORT=8080
ENV GOOGLE_GENAI_USE_VERTEXAI=true

# Create data directory for session persistence
RUN mkdir -p /app/data

# Use adk run agent as the entrypoint for CLI interaction
# Default to using local SQLite for session persistence (mount /app/data to persist)
CMD ["adk", "api_server", "agent", "--session_service_uri", "sqlite:////app/data/sessions.db"]
