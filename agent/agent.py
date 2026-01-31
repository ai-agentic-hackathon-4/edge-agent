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

from pydantic import ConfigDict, Field, BaseModel, field_validator
from pydantic import ConfigDict, Field
from typing import List, Optional

# Vertex AI / Gemini 設定（値は環境変数で上書きしてください）
# Gemini 3 (2026年時点の最新標準: gemini-3-flash-preview)
MODEL_ID = "gemini-3-flash-preview"

# --- Monkey Patch Start ---
from google.adk.events.event import Event
import google.adk.flows.llm_flows.functions as adk_functions

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

class CustomLlmAgent(LlmAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: List[Any] = Field(default=[], exclude=True)

    @field_validator('generate_content_config', mode='after')
    @classmethod
    def validate_generate_content_config(
        cls, generate_content_config: Optional[genai_types.GenerateContentConfig]
    ) -> genai_types.GenerateContentConfig:
        # Override parent validator to allow response_schema in generate_content_config
        # This allows us to use structured output (JSON mode) WHILE also using tools,
        # which the parent class normally forbids.
        if not generate_content_config:
            return genai_types.GenerateContentConfig()
        return generate_content_config

from typing import Dict

class OperationDetails(BaseModel):
    action: str = Field(description="Action taken (e.g., 'Heating 25C ON')")
    comment: str = Field(description="Reason or additional info")
    severity: str = Field(description="Severity of the operation: 'info' (routine/check), 'warning' (action taken/adjustment), 'critical' (emergency)")

class AgentOutput(BaseModel):
    logs: List[str] = Field(description="List of operation logs (e.g., 'Air conditioner set to 25C', 'Checked sensor data')")
    plant_status: str = Field(description="Current status of the plant (e.g., 'Healthy', 'Wilting', 'Dry')")
    growth_stage: int = Field(description="Growth stage of the plant from 1 to 5 (1: Sprout, 5: Harvest)")
    operation: Dict[str, OperationDetails] = Field(description="Details of operations performed on devices")
    comment: str = Field(description="Message or advice to the user")

def create_agent():
    # MCP Toolset (Stdio mode)
    # MCP_SERVER_PATH 環境変数があればそれを使用し、なければコンテナ内のデフォルトパスを使用
    default_server_path = "/app/MCP/sensor_image_server.py"
    server_script_path = os.environ.get("MCP_SERVER_PATH", default_server_path)
    
    # Env for subprocess
    env = os.environ.copy()
    # Add project root to PYTHONPATH so `from MCP import ...` works
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    mcp_toolset = GCSAwareMcpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[server_script_path],
                env=env
            ),
            timeout=120.0
        ),
    )

    # Updated instruction to request JSON format via prompt (since config breaks vision)
    default_instruction = (
            "あなたは植物の環境を管理するマルチモーダルアシスタントです。すべての応答は**日本語**で行ってください。"
            "1. `capture_image`を使用して植物の種類を特定してください。"
            "2. **植物の健康状態を診断**: しおれ、変色（黄ばみ/茶色）、害虫、病気の兆候がないか確認し、診断結果を『plant_status』に記録してください。"
            "3. 植物の成長段階（1:発芽〜5:収穫）を推定し、『growth_stage』に整数で記録してください。"
            "4. この特定の植物に最適な温度、湿度、土壌水分、照度を決定してください。"
            "5. `get_current_time`を使用して現在時刻を確認してください。夜間かどうか判断材料にしてください。"
            "6. `get_meter_data`（温度/湿度）、`get_soil_moisture`（土壌）、`get_bh1750_data`（照度）を使用して、現在の状況を確認してください。また、`get_meter_data`で得た温度と湿度を用いて`calculate_vpd`を実行し、飽差(VPD)を確認してください。"
            "7. **デバイスの状態確認**: `get_air_conditioner_status` と `get_humidifier_status` を使用して、現在のデバイス設定を確認してください。"
            "8. 調整が必要な場合："
            "   - **空調設定の注意点**: 30分に1回の制御であることを考慮し、30分後を見越した設定にしてください。**暖房で低温（例: 20℃以下）や冷房で高温（例: 28℃以上）など、効果の薄い設定は避けてください。**"
            "   - **安易なモード切替の禁止**: 目標温度と異なる場合でも、すぐにモード（冷房⇄暖房）を切り替えるのではなく、まずは**設定温度の微調整（例: 暖房中に少し暑ければ設定を2℃下げる）**や**エアコンの停止**で対応できないか検討してください。"
            "   - 飽差(VPD)が理想ゾーン（0.8 〜 1.2 kPa）となるように、空調や加湿器を調整してください。"
            "   - 操作を行った場合、その内容を『logs』リストに追加してください。"
            "   - 土壌水分が低い場合（例: 30%未満）は、**`control_pump`を使用して水やり（例: 50ml）を行ってください**。"
            "   - **ポンプを使用した場合は、必ずその内容（水量など）を『logs』リストに追加してください。**"
            "9. **操作の記録**: 操作を行った場合、または現状維持の判断についても『operation』フィールドに詳細を記録してください。"
            "   - キー: デバイス名（例: 'エアコン', '加湿器', 'ポンプ'）。"
            "   - 『action』: 具体的なアクション内容（例: '暖房25℃でON', 'OFF', '現状維持'）。"
            "   - 『comment』: 理由や補足。"
            "   - 『severity』: そのアクションの重要度。"
            "     - `info`: 現状維持、定期チェック報告など。"
            "     - `warning`: 設定変更、水やりなどの能動的なアクション。"
            "     - `critical`: 緊急警告、異常検知など。"
            "10. 植物の状態が**緊急**である場合、`send_discord_notification`を使用して警告し、その旨を『logs』に記録してください。"
            "11. ユーザーへの総合的なアドバイスやコメントを『comment』フィールドに記述してください。"
            "\n"
            "**出力フォーマット**:\n"
            "以下のJSONスキーマに従って、**JSONオブジェクトのみ**を出力してください。Markdownコードブロック（```json ... ```）は使用しないでください。\n"
            "{\n"
            "  \"logs\": [\"ログメッセージ1\", \"ログメッセージ2\"],\n"
            "  \"plant_status\": \"健康状態の説明\",\n"
            "  \"growth_stage\": 3,\n"
            "  \"operation\": {\n"
            "    \"エアコン\": {\n"
            "      \"action\": \"暖房25℃でON\",\n"
            "      \"comment\": \"寒いため設定温度を上げました\",\n"
            "      \"severity\": \"warning\"\n"
            "    }\n"
            "  },\n"
            "  \"comment\": \"ユーザーへのメッセージ\"\n"
            "}"
    )

    # Append Firestore instruction if available
    firestore_instruction = os.environ.get("FIRESTORE_INSTRUCTION")
    if firestore_instruction:
        default_instruction += "\n\n" + "**以下は今回の植物に関する追加情報および育成ガイドです:**\n" + firestore_instruction

    print("=== Full Agent Instruction ===", flush=True)
    print(default_instruction, flush=True)
    print("==============================", flush=True)

    return LlmAgent(
        name="sensor_gemini_agent",
        model=MODEL_ID,
        instruction=default_instruction,
        tools=[mcp_toolset],
        generate_content_config=genai_types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

root_agent = create_agent()
