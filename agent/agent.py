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
    
    MCP_TIMEOUT = float(os.environ.get("MCP_TIMEOUT", "300.0"))
    
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
            timeout=MCP_TIMEOUT
        ),
    )

    # Updated instruction to request JSON format via prompt (since config breaks vision)
    default_instruction = (
            "あなたは植物の環境を管理するマルチモーダルアシスタントです。すべての応答は**日本語**で行ってください。"
            "1. `capture_image`を使用して植物の種類を特定してください。"
            "2. **植物の健康状態を診断**: しおれ、変色（黄ばみ/茶色）、害虫、病気の兆候がないか確認し、診断結果を『plant_status』に記録してください。"
            "3. 植物の成長段階（1:発芽〜5:収穫）を推定し、『growth_stage』に整数で記録してください。"
            "4. この特定の植物に最適な温度、湿度、土壌水分、照度を決定してください。"
            "6. **フェーズ1: 状況確認（Observation）**"
            "   - `get_meter_data`（温度/湿度）、`get_soil_moisture`（土壌）、`get_bh1750_data`（照度）を一括で実行して確認してください。"
            "   - `get_air_conditioner_status` と `get_humidifier_status` を実行してデバイス設定を確認してください。"
            "   - `get_current_time` で時刻を確認してください。"
            "   - 取得した値を使って `calculate_vpd` を実行してください。"
            "   - **このフェーズですべての情報を集めきってください。後から再取得しないでください。**"
            "   - **センサー/ステータス取得は各デバイスにつき1回のみ実行してください。繰り返し取得は禁止です。**"
            "8. **フェーズ2: 判断と実行（Action）**"
            "   - フェーズ1の情報に基づき、必要な操作を決定してください。"
            "   - **【重要：状態比較による操作スキップ】**:"
            "     - 制御コマンドを送信する**前に**、フェーズ1で取得した現在のデバイス状態（Current State）と、これから設定しようとする目標状態（Target State）を比較してください。"
            "     - **エアコン**: `get_air_conditioner_status` で取得した `temperature`, `mode`, `fan_speed`, `is_on` が、設定しようとする値と**完全に一致**する場合は、`control_air_conditioner` を**呼び出さないでください**。『operation』には『現状維持（設定済み）』と記録してください。"
            "     - **加湿器**: `get_humidifier_status` で取得した `mode`, `is_on` が目標と一致する場合は、`control_humidifier` を**呼び出さないでください**。"
            "     - **照明**: 既にON/OFFの状態が目標と一致している場合は、`control_light` を**呼び出さないでください**。"
            "     - **すでに目標状態にあるデバイスへの制御コマンド送信は無駄なAPIコールであり、禁止されています。**"
            "   - **空調設定の注意点**: 30分に1回の制御であることを考慮し、30分後を見越した設定にしてください。**暖房で低温（例: 20℃以下）や冷房で高温（例: 28℃以上）など、効果の薄い設定は避けてください。**"
            "   - **安易なモード切替の禁止**: 目標温度と異なる場合でも、すぐにモード（冷房⇄暖房）を切り替えるのではなく、まずは**設定温度の微調整（例: 暖房中に少し暑ければ設定を2℃下げる）**や**エアコンの停止**で対応できないか検討してください。"
            "   - 飽差(VPD)が理想ゾーン（0.8 〜 1.2 kPa）となるように、空調や加湿器を調整してください。"
            "   - 土壌水分が低い場合（例: 30%未満）は、**`control_pump`を使用して水やり（例: 50ml）を行ってください**。"
            "   - **日中（06:00-18:00）で照度が低い場合（例: 1000 lux未満）は、`control_light`を使用して補光（ON, brightness=100）してください。** 夜間はOFFにしてください。"
            "   - 必要な操作コマンド（`control_...`）を**一度に**発行してください。"
            "9. **フェーズ3: 記録と終了（Logging & Finish）**"
            "   - 操作の成否（通常は成功とみなす）に基づき、以下のJSONを作成して出力し、**直ちに会話を終了してください**。"
            "   - **操作後の再確認は不要です。**"
            "   - **操作の記録**: 操作を行った場合、または現状維持の判断についても『operation』フィールドに詳細を記録してください。"
            "   - キー: デバイス名（例: 'エアコン', '加湿器', 'ポンプ'）。"
            "   - 『action』: 具体的なアクション内容（例: '暖房25℃でON', 'OFF', '現状維持（設定済み）'）。"
            "   - 『comment』: 理由や補足。**状態比較でスキップした場合は「既に目標状態のため操作不要」と明記してください。**"
            "   - 『severity』: そのアクションの重要度。"
            "     - `info`: 現状維持、定期チェック報告など。"
            "     - `warning`: 設定変更、水やりなどの能動的なアクション。"
            "     - `critical`: 緊急警告、異常検知など。"
            "10. 植物の状態が**緊急**である場合、`send_discord_notification`を使用して警告し、その旨を『logs』に記録してください。"
            "11. **【重要：単一パス実行の厳守 - ループ禁止】**:"
            "    - 本システムは30分に1回の定期実行です。"
            "    - **禁止事項（違反するとシステムエラーとなります）**:"
            "      - センサー値の再取得（`get_...` の2回以上の実行）"
            "      - デバイスステータスの再確認（`get_air_conditioner_status`, `get_humidifier_status` の2回以上の実行）"
            "      - 同一デバイスへの制御コマンドの複数回送信"
            "      - 操作後の結果確認のためのセンサー再取得"
            "      - ループ処理や繰り返し処理"
            "    - **正しい実行フロー（1回のみ）**: センサー確認（1回） → 状態比較 → 必要な操作のみ実行（最大1回/デバイス） → JSON出力 → **即座に終了**"
            "    - アクションが成功（200 OK）したら、それは実行されたとみなしてログに記録し、**それ以上の操作なしに**終了してください。"
            "    - **操作後に「確認のため再度センサーを取得する」という行為は禁止です。次回の定期実行まで待ってください。**"
            "12. ユーザーへの総合的なアドバイスやコメントを『comment』フィールドに記述してください。"
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

    # Configure logger
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # --- Credential Setup ---
    # Try to load credentials from default file if not in env
    if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        # Default path in Docker/Repo structure
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        key_path = os.path.join(project_root, "agent", "ai-agentic-hackathon-4-97df01870654.json")
        if os.path.exists(key_path):
             os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
             logger.info(f"Loaded credentials from file: {key_path}")
        else:
             logger.warning(f"Credential file not found at: {key_path}")

    # Append Firestore instruction if available
    firestore_instruction = os.environ.get("FIRESTORE_INSTRUCTION")
    
    if not firestore_instruction:
        # Fetch from Firestore
        try:
            from google.cloud import firestore
            # Check creds or project env (standard checks)
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ or "GOOGLE_CLOUD_PROJECT" in os.environ:
                 # Attempt to connect (default project or inferred)
                 # Using explicit database if needed, or default
                 db = firestore.Client(database="ai-agentic-hackathon-4-db")
                 doc = db.collection("configurations").document("edge_agent").get()
                 if doc.exists:
                     data = doc.to_dict()
                     if "instruction" in data:
                         firestore_instruction = data["instruction"]
                         logger.info("Loaded FIRESTORE_INSTRUCTION from Firestore.")
        except Exception as e:
            logger.warning(f"Failed to fetch instruction from Firestore: {e}")

    if firestore_instruction:
        default_instruction += "\n\n" + "**以下は今回の植物に関する追加情報および育成ガイドです:**\n" + firestore_instruction

    logger.info("=== Full Agent Instruction ===")
    logger.info(default_instruction)
    logger.info("==============================")

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
