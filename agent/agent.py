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
                                # Allow dots in URI for file extensions
                                match = re.search(r'gs://[^\s\)]+', text)
                                if match:
                                    uri = match.group(0)
                                    # Strip trailing punctuation if any (like . or , at end of sentence)
                                    uri = uri.rstrip('.,;')
                                    print(f"[Agent] Detected GCS URI: {uri}")
                                    return [genai_types.Part.from_uri(file_uri=uri, mime_type="image/jpeg")]
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

from google.adk.events.event import Event
import google.adk.flows.llm_flows.functions as adk_functions

# --- Monkey Patch Start ---
# Patch ADK's __build_response_event to allow returning multimodal Parts from tools.
# Default ADK implementation forces everything into a JSON dict, which breaks Part objects.
original_build_response_event = adk_functions.__build_response_event

def custom_build_response_event(
    tool,
    function_result,
    tool_context,
    invocation_context,
) -> Event:
    # Specs requires the result to be a dict.
    if not isinstance(function_result, dict):
        function_result = {'result': function_result}

    extra_parts = []
    # Check if 'result' contains a list of Parts (from our GCSAwareMcpToolset)
    if 'result' in function_result and isinstance(function_result['result'], list):
        if len(function_result['result']) > 0 and isinstance(function_result['result'][0], genai_types.Part):
            extra_parts = function_result['result']
            # Replace the list of Parts in the JSON response with a textual placeholder
            function_result = {'result': 'Multimodal content returned (see additional parts).'}

    # Create the standard FunctionResponse part (required to close the function call)
    part_function_response = genai_types.Part.from_function_response(
        name=tool.name, response=function_result
    )
    part_function_response.function_response.id = tool_context.function_call_id

    # Create content with BOTH the FunctionResponse and the Image Parts
    all_parts = [part_function_response] + extra_parts
    
    content = genai_types.Content(
        role='user',
        parts=all_parts,
    )

    function_response_event = Event(
        invocation_id=invocation_context.invocation_id,
        author=invocation_context.agent.name,
        content=content,
        actions=tool_context.actions,
        branch=invocation_context.branch,
    )
    return function_response_event

# Apply patch
adk_functions.__build_response_event = custom_build_response_event
# --- Monkey Patch End ---

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
