#!/bin/bash

# Gemma 3n PyTorch Server Startup Script
# Usage: ./start_gemma_server.sh

# Activate venv if exists
if [ -d "../agent-engine/venv" ]; then
    source ../agent-engine/venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Ensure dependencies are installed (basic check)
if ! python -c "import torch; import transformers" &> /dev/null; then
    echo "Installing required packages..."
    pip install torch transformers accelerate pillow uvicorn fastapi
fi

echo "Starting Gemma 3n PyTorch Server..."
echo "Model: google/gemma-3n-E2B-it (via Transformers)"
echo "Address: http://0.0.0.0:8000"

# Run server
python localLLM/gemma3n_pytorch_server.py
