import asyncio
import os
import sys

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from pydantic import ConfigDict, Field
from typing import Any, List

# Vertex AI / Gemini 設定（値は環境変数で上書きしてください）
# Gemini 3 (2026年時点の最新標準: gemini-3-flash-preview)
MODEL_ID = "gemini-3-flash-preview"

class CustomLlmAgent(LlmAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: List[Any] = Field(default=[], exclude=True)

def create_agent():
    # MCP Toolset の設定 (Stdioモード)
    # Dockerコンテナ内のパスを指定
    server_script_path = "/app/MCP/sensor_image_server.py"
    
    mcp_toolset = MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=[server_script_path],
                env=None
            )
        ),
    )
    
    return CustomLlmAgent(
        name="sensor_gemini_agent",
        model=MODEL_ID,
        instruction=(
            "You are a multimodal assistant. "
            "Use the MCP tool 'capture_image' to fetch the latest sensor image. "
            "Use the MCP tool 'get_meter_data' to fetch current temperature and humidity. "
            "The image tool returns base64 format; verify visuals. "
            "The meter tool returns JSON with temperature and humidity. "
            "Combine these inputs to answer user queries."
        ),
        tools=[mcp_toolset]
    )

root_agent = create_agent()
