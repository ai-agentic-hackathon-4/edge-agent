FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment variables for ADK/Vertex AI
ENV PORT=8080
ENV GOOGLE_GENAI_USE_VERTEXAI=true

# Use adk run agent as the entrypoint for CLI interaction
CMD ["adk", "run", "agent"]
