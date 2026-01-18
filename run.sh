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

# Add current directory to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.

echo "Starting Agent with Web UI..."
echo "Access the UI at http://localhost:8501 (default)"

# Run the agent with UI
# Assuming google-adk is installed
adk run agent --ui agent.agent:root_agent
