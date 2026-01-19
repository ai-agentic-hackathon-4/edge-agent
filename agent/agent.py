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

from google.adk.sessions.database_session_service import DatabaseSessionService

def create_agent():
    # MCP Toolset の設定 (Stdioモード)
    # MCP_SERVER_PATH 環境変数があればそれを使用し、なければコンテナ内のデフォルトパスを使用
    default_server_path = "/app/MCP/sensor_image_server.py"
    server_script_path = os.environ.get("MCP_SERVER_PATH", default_server_path)
    
    mcp_toolset = GCSAwareMcpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[server_script_path],
                env=os.environ.copy()
            ),
            timeout=120.0
        ),
    )

    # Session Service Setup
    # Use SQLite for persistence. Default to /app/data/sessions.db
    # Must use async driver: sqlite+aiosqlite
    session_db_uri = os.environ.get("SESSION_DB_URI", "sqlite+aiosqlite:////app/data/sessions.db")
    session_service = DatabaseSessionService(db_url=session_db_uri)
    

    # Default instruction
    default_instruction = (
            "あなたは植物の環境を管理するマルチモーダルアシスタントです。すべての応答は**日本語**で行ってください。"
            "1. まず、`capture_image`を使用して植物の種類を特定してください。"
            "2. **植物の健康状態を診断**: しおれ、変色（黄ばみ/茶色）、害虫、病気の兆候がないか確認し、診断結果を明確に報告してください。"
            "3. この特定の植物に最適な温度、湿度、土壌水分を決定してください。"
            "4. `get_meter_data`（温度/湿度）と`get_soil_moisture`（土壌）を使用して、現在の状況を確認してください。"
            "5. **デバイスの状態確認**: `get_air_conditioner_status` と `get_humidifier_status` を使用して、現在のデバイス設定（電源ON/OFFなど）を確認してください。"
            "6. 現在の状況、デバイスの状態、および最適な条件を比較してください。"
            "7. 調整が必要な場合："
            "   - 空調には`control_air_conditioner`または`control_humidifier`を使用してください。**注意**: すでに適切な設定で稼働している場合は、無駄な操作を避けてください。"
            "   - 土壌水分が低い場合は、**ユーザーに水やりをするようアドバイス**してください（直接水を制御することはできません）。"
            "8. **重要**: 植物の状態が**緊急**（重度のしおれ、乾燥、病気、または害虫の蔓延）である場合、`send_discord_notification`を使用してユーザーに直ちに警告してください。"
            "9. 条件が満たされている場合は、省エネのためにデバイスの電源を切ってください。"
            "常に以下のフォーマットで報告してください："
            "**現在の状態**: [植物のID] -> [健康診断結果] -> [環境データ] -> [デバイス状態]"
            "**推奨アクション**: [実行したアクション / ユーザーへのアドバイス]"
    )

    return CustomLlmAgent(
        name="sensor_gemini_agent",
        model=MODEL_ID,
        instruction=os.environ.get("AGENT_INSTRUCTION", default_instruction),
        tools=[mcp_toolset]
    )

root_agent = create_agent()
