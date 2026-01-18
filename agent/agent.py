import asyncio
import os
import sys
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.genai import types as genai_types
import types
import re
import collections.abc

# Wrapper class to make MCP tools return Part objects for GCS URIs
class GCSAwareMcpToolset(McpToolset):
    async def get_tools(self, *args, **kwargs) -> collections.abc.Iterable[Any]:
        tools = await super().get_tools(*args, **kwargs)
        # tools is an iterable (list), but type hint says Iterable.
        # super implementation returns a list.
        
        for tool in tools:
            if tool.name == "capture_image":
                original_run_async = tool.run_async
                
                async def gcs_aware_run_async(self, *, args, tool_context):
                    result = await original_run_async(args=args, tool_context=tool_context)
                    
                    # Intercept output
                    if isinstance(result, dict) and 'content' in result:
                        for content in result['content']:
                            # Check for GCS URI in text
                            if content.get('type') == 'text' and 'gs://' in content.get('text', ''):
                                text = content['text']
                                match = re.search(r'gs://[^\s\.\)]+', text) # Basic regex
                                if match:
                                    uri = match.group(0)
                                    # Strip trailing punctuation if any
                                    uri = uri.rstrip('.,;')
                                    print(f"[Agent] Detected GCS URI: {uri}")
                                    return genai_types.Part.from_uri(file_uri=uri, mime_type="image/jpeg")
                    return result
                
                # Bind wrapper to instance
                tool.run_async = types.MethodType(gcs_aware_run_async, tool)
                
        return tools

from pydantic import ConfigDict, Field
from pydantic import ConfigDict, Field
from typing import List

# Vertex AI / Gemini 設定（値は環境変数で上書きしてください）
# Gemini 3 (2026年時点の最新標準: gemini-3-flash-preview)
MODEL_ID = "gemini-3-flash-preview"

class CustomLlmAgent(LlmAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: List[Any] = Field(default=[], exclude=True)

def create_agent():
    # MCP Toolset の設定 (Stdioモード)
    # MCP_SERVER_PATH 環境変数があればそれを使用し、なければコンテナ内のデフォルトパスを使用
    default_server_path = "/app/MCP/sensor_image_server.py"
    server_script_path = os.environ.get("MCP_SERVER_PATH", default_server_path)
    
    mcp_toolset = GCSAwareMcpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=[server_script_path],
                env=os.environ.copy()
            )
        ),
    )
    
    return CustomLlmAgent(
        name="sensor_gemini_agent",
        model=MODEL_ID,
        instruction=(
            "You are a multimodal assistant. "
            "Use the MCP tool 'capture_image' to fetch the latest sensor image. "
            "The tool returns a Google Cloud Storage (GCS) URI (gs://...). "
            "Use the MCP tool 'get_meter_data' to fetch current temperature and humidity. "
            "The meter tool returns JSON with temperature and humidity. "
            "Combine these inputs to answer user queries."
        ),
        tools=[mcp_toolset]
    )

root_agent = create_agent()
