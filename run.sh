#!/bin/bash
set -e

# Ensure we are in the edge-agent directory
cd "$(dirname "$0")"

# Check if .env exists in agent/
if [ ! -f agent/.env ]; then
    echo "Error: agent/.env file not found. Please create it based on README."
    exit 1
fi

# Load environment variables from agent/.env
export $(grep -v '^#' agent/.env | xargs)

# Override GOOGLE_APPLICATION_CREDENTIALS for local execution if file exists
if [ -f "agent/ai-agentic-hackathon-4-97df01870654.json" ]; then
    export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/agent/ai-agentic-hackathon-4-97df01870654.json"
fi

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.

# Set MCP server path for local execution
export MCP_SERVER_PATH=$(pwd)/MCP/sensor_image_server.py

# Check for local venv ADK
if [ -f "env/bin/adk" ]; then
    ADK_CMD="./env/bin/adk"
else
    ADK_CMD="adk"
fi

echo "Starting Agent as API Server..."
# Run the agent as API
$ADK_CMD api_server agent --log_level DEBUG
