import os
import sys

# Ensure agent-engine packages are found if running standalone
sys.path.append(os.path.join(os.path.dirname(__file__), "../agent-engine/venv/lib/python3.12/site-packages"))

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# Server settings
API_BASE = "http://localhost:8000/v1"
API_KEY = "sk-no-key-required"
MODEL_NAME = "openai/gemma-3n"

# 1. Configure the LLM Backend
llm = LiteLlm(
    model=MODEL_NAME,
    api_base=API_BASE,
    api_key=API_KEY
)

# 2. Create the Agent
# The 'agent' variable is what `adk run` or `adk api_server` will look for.
agent = LlmAgent(
    name="gemma_vision_agent",
    model=llm,
    instruction="You are a helpful assistant capable of vision tasks. Describe what you see in concise detail."
)

if __name__ == "__main__":
    print("This file is an ADK Agent definition.")
    print("To run interactively:")
    print("  adk run adk_gemma_agent:agent")
    print("To start API server:")
    print("  adk api_server adk_gemma_agent:agent")
