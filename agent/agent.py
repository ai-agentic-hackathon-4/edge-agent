import asyncio
import os
import sys
from typing import Any


from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, McpToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.genai import types as genai_types
from google.genai.types import HttpRetryOptions, ThinkingConfig
from google.adk.models.google_llm import Gemini
import types
import re
import collections.abc

# MCPツールがGCSのURIに対してPartオブジェクトを返すようにするためのラッパークラス
class GCSAwareMcpToolset(McpToolset):
    async def get_tools(self, *args, **kwargs) -> collections.abc.Iterable[Any]:
        tools = await super().get_tools(*args, **kwargs)
        # tools is an iterable (list), but type hint says Iterable.
        # toolsはイテラブル（リスト）ですが、型ヒントはIterableと記載されています。
        # super implementation returns a list.
        # superの実装はリストを返します。
        
        for tool in tools:
            if tool.name == "capture_image":
                original_run_async = tool.run_async
                
                async def gcs_aware_run_async(self, *, args, tool_context):
                    result = await original_run_async(args=args, tool_context=tool_context)
                    
                    # Intercept output
                    # 出力を傍受する
                    if isinstance(result, dict) and 'content' in result:
                        for content in result['content']:
                            # Check for GCS URI in text
                            # テキスト内のGCS URIを確認する
                            if content.get('type') == 'text' and 'gs://' in content.get('text', ''):
                                text = content['text']
                                # Allow dots in URI for file extensions
                                # ファイル拡張子のためにURI内のドットを許可する
                                match = re.search(r'gs://[^\s\)]+', text)
                                if match:
                                    uri = match.group(0)
                                    # Strip trailing punctuation if any (like . or , at end of sentence)
                                    # 文末の句読点（.や,など）がある場合は削除する
                                    uri = uri.rstrip('.,;')
                                    print(f"[Agent] Detected GCS URI: {uri}")
                                    return [genai_types.Part.from_uri(file_uri=uri, mime_type="image/jpeg")]
                    return result
                
                # ラッパーをインスタンスにバインドする
                tool.run_async = types.MethodType(gcs_aware_run_async, tool)
                
        return tools

from pydantic import ConfigDict, Field, BaseModel, field_validator
from pydantic import ConfigDict, Field
from typing import List, Optional

# Vertex AI / Gemini 設定（値は環境変数で上書きしてください）
# Gemini 3 (2026年時点の最新標準: gemini-3-flash-preview)
MODEL_ID = "gemini-3-flash-preview"
# MODEL_ID = "gemini-3-pro-preview"

# --- モンキーパッチ開始 ---
from google.adk.events.event import Event
from google.adk.agents.invocation_context import InvocationContext
from typing import AsyncGenerator
import google.adk.flows.llm_flows.functions as adk_functions

# ADKの __build_response_event にパッチを適用し、ツールからマルチモーダルなPartオブジェクトを返せるようにする。
# デフォルトのADK実装はすべてをJSON辞書に強制変換するため、Partオブジェクトが壊れてしまう。
original_build_response_event = adk_functions.__build_response_event

def custom_build_response_event(
    tool,
    function_result,
    tool_context,
    invocation_context,
) -> Event:
    # 仕様では結果は辞書型である必要がある。
    if not isinstance(function_result, dict):
        function_result = {'result': function_result}

    extra_parts = []
    # 'result' に Part のリストが含まれているか確認する (GCSAwareMcpToolset からのもの)
    if 'result' in function_result and isinstance(function_result['result'], list):
        if len(function_result['result']) > 0 and isinstance(function_result['result'][0], genai_types.Part):
            extra_parts = function_result['result']
            # JSONレスポンス内の Part リストをテキストのプレースホルダーに置き換える
            function_result = {'result': 'Multimodal content returned (see additional parts).'}

    # 標準の FunctionResponse パートを作成する (関数呼び出しを閉じるために必要)
    part_function_response = genai_types.Part.from_function_response(
        name=tool.name, response=function_result
    )
    part_function_response.function_response.id = tool_context.function_call_id

    # FunctionResponse と画像 Part の両方を含むコンテンツを作成する
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

# パッチを適用
adk_functions.__build_response_event = custom_build_response_event
# --- モンキーパッチ終了 ---

from google.adk.sessions.database_session_service import DatabaseSessionService

class CustomLlmAgent(LlmAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: List[Any] = Field(default=[], exclude=True)

    @field_validator('generate_content_config', mode='after')
    @classmethod
    def validate_generate_content_config(
        cls, generate_content_config: Optional[genai_types.GenerateContentConfig]
    ) -> genai_types.GenerateContentConfig:
        # generate_content_config で response_schema を許可するために親バリデータにオーバーライドする
        # これにより、親クラスが通常禁止しているツールの使用と同時に、構造化出力（JSONモード）を使用できるようになる。
        if not generate_content_config:
            return genai_types.GenerateContentConfig()
        return generate_content_config

from typing import Dict

class OperationDetails(BaseModel):
    action: str = Field(description="Action taken (e.g., 'Heating 25C ON')")
    comment: str = Field(description="Reason or additional info")
    severity: str = Field(description="Severity of the operation: 'info' (routine/check), 'warning' (action taken/adjustment), 'critical' (emergency)")

from enum import IntEnum

class GrowthStage(IntEnum):
    SPROUT = 1      # 発芽 (Sprout)
    SEEDLING = 2    # 育苗 (Seedling)
    VEGETATIVE = 3  # 栄養成長 (Vegetative)
    FLOWERING = 4   # 開花・結実 (Flowering/Fruiting)
    HARVEST = 5     # 収穫 (Harvest)

class AgentOutput(BaseModel):
    logs: List[str] = Field(description="List of operation logs (e.g., 'Air conditioner set to 25C', 'Checked sensor data')")
    plant_status: str = Field(description="Current status of the plant (e.g., 'Healthy', 'Wilting', 'Dry')")
    growth_stage: GrowthStage = Field(description="Growth stage of the plant from 1 to 5 (1: Sprout, 2: Seedling, 3: Vegetative, 4: Flowering, 5: Harvest)")
    operation: Dict[str, OperationDetails] = Field(description="Details of operations performed on devices")
    comment: str = Field(description="Message or advice to the user")

def create_agent():
    # ロガーの設定
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # プロジェクトルートと相対パスを動的に計算する
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_mcp_path = os.path.join(project_root, "MCP", "sensor_image_server.py")
    local_key_path = os.path.join(project_root, "agent", "ai-agentic-hackathon-4-97df01870654.json")

    # --- MCPサーバーパスの処理 ---
    # 環境変数がDockerパス（例: /app/...）に設定されている可能性がある
    env_mcp_path = os.environ.get("MCP_SERVER_PATH")
    
    if env_mcp_path and os.path.exists(env_mcp_path):
        server_script_path = env_mcp_path
    else:
        # 環境変数のパスが見つからないか無効な場合、ローカルの相対パスにフォールバックする
        server_script_path = local_mcp_path
        # 可視性のために環境変数を更新する（オプション）
        os.environ["MCP_SERVER_PATH"] = server_script_path
        if env_mcp_path:
             logger = logging.getLogger(__name__) # ロガーはまだ設定されていない可能性があるが、通常は問題ない、または単にprintする
             print(f"Warning: MCP_SERVER_PATH '{env_mcp_path}' not found. Falling back to: {server_script_path}")

    # --- 認証情報の処理 ---
    # .env経由でDockerパスに設定されている可能性がある
    env_cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    
    if env_cred_path and not os.path.exists(env_cred_path):
        # 明示的なパスが設定されているが無効（例: /app/...）な場合、ローカルフォールバックを試行する
        if os.path.exists(local_key_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_key_path
            print(f"Warning: Credential file '{env_cred_path}' not found. Falling back to: {local_key_path}")
        else:
             print(f"Warning: Credential file '{env_cred_path}' not found and local fallback '{local_key_path}' also missing.")
    elif not env_cred_path:
        # Not set at all, try local fallback
        if os.path.exists(local_key_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_key_path
            print(f"Set GOOGLE_APPLICATION_CREDENTIALS to: {local_key_path}")

    # google.auth が変更を認識するように、可能であればデフォルトの認証情報をリロードする
    # 通常は環境変数を設定するだけで十分。
    # 最終的に設定された値を確認する。
    final_cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    print(f"Debug: Final GOOGLE_APPLICATION_CREDENTIALS = {final_cred_path}")

    
    MCP_TIMEOUT = float(os.environ.get("MCP_TIMEOUT", "300.0"))
    
    # サブプロセスのための環境変数
    env = os.environ.copy()
    # `from MCP import ...` が動作するように、プロジェクトルートを PYTHONPATH に追加する
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

    # instructions.py からベースの指示を読み込む
    try:
        from .instructions import get_base_instruction
        default_instruction = get_base_instruction()
    except ImportError:
        # 相対インポートが失敗した場合（スクリプトとして実行時など）
        from instructions import get_base_instruction
        default_instruction = get_base_instruction()

    # Firestore の指示があれば追加する
    firestore_instruction = os.environ.get("FIRESTORE_INSTRUCTION")
    
    if not firestore_instruction:
        # Firestore から取得する
        try:
            from google.cloud import firestore
            # 認証情報またはプロジェクト環境変数の確認（標準チェック）
            if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ or "GOOGLE_CLOUD_PROJECT" in os.environ:
                 # 接続試行（デフォルトプロジェクトまたは推論されたプロジェクト）
                 # 必要に応じて明示的なデータベースを使用、またはデフォルトを使用
                 db = firestore.Client(database="ai-agentic-hackathon-4-db")
                 
                 # 1. Edge Agent設定の取得
                 doc = db.collection("configurations").document("edge_agent").get()
                 if doc.exists:
                     data = doc.to_dict()
                     if "instruction" in data:
                         firestore_instruction = data["instruction"]
                         logger.info("Loaded FIRESTORE_INSTRUCTION from Firestore.")

                 # 2. キャラクター設定の取得 (growing_diaries/Character)
                 char_doc = db.collection("prod_growing_diaries").document("Character").get()
                 character_instruction = ""
                 if char_doc.exists:
                     char_data = char_doc.to_dict()
                     char_name = char_data.get("name")
                     char_personality = char_data.get("personality")
                     
                     if char_name and char_personality:
                         character_instruction = (
                             f"\n\n14. **【キャラクター設定（Persona）】**:\n"
                             f"    - あなたは「{char_name}」というキャラクターとして振る舞ってください。**自己紹介は不要です。**\n"
                             f"    - 性格・口調: {char_personality}\n"
                             f"    - 『comment』フィールドの出力は、必ずこのキャラクターの口調で記述してください。それ以外のフィールドの出力は、標準語で記述してください。\n"
                             f"    - **【重要：自然な発話】**: キャラクター設定を守りつつも、**わざとらしい演技や過剰なキャラ作りは避けてください**。ユーザーの役に立つアドバイスを、そのキャラクターらしい自然な言葉選びで伝えてください。\n"
                             f"    - **【数値の言い換え】**: 気温（◯℃）、湿度（◯%）、飽差（◯kPa）などの具体的な数値は言わずに、**必ず「少し肌寒い」「湿度はちょうど良い」「乾燥してきている」のように、体感や状態を表す言葉に言い換えて伝えてください。**\n"
                             f"    - **【禁止事項】**: 「（湿度が低め）」のような**括弧書きの補足説明は絶対に出力しないでください**。セリフの中で自然に状況を伝えてください。"
                         )
                         logger.info(f"Loaded Character persona: {char_name}")

        except Exception as e:
            logger.warning(f"Failed to fetch instruction/character from Firestore: {e}")
            character_instruction = "" # エラー時は空にする

    if firestore_instruction:
        default_instruction += "\n\n" + "**以下は今回の植物に関する追加情報および育成ガイドです:**\n" + firestore_instruction
    
    if character_instruction:
        default_instruction += character_instruction

    logger.info("=== Full Agent Instruction ===")
    logger.info(default_instruction)
    logger.info("==============================")

    return CustomLlmAgent(
        name="sensor_gemini_agent",
        model=Gemini(
            model=MODEL_ID,
            retry_options=HttpRetryOptions(
                attempts=500,  # "Ultra High Frequency" strategy
                initial_delay=1,  # デフォルト: 1.0
                max_delay=5,  # Cap at 5s
                exp_base=1.1,  # Slow exponential growth
                jitter=0.5  # デフォルト: 1
                # http_status_codes=[429],  # デフォルト: [408, 429, 500, 502, 503, 504]
            )
        ),
        instruction=default_instruction,
        tools=[mcp_toolset],
        generate_content_config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=ThinkingConfig(include_thoughts=True)
        ),
    )

root_agent = create_agent()
