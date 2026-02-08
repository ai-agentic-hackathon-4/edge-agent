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
# MODEL_ID = "gemini-3-flash-preview"
MODEL_ID = "gemini-3-pro-preview"

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

    # プロンプト経由でJSONフォーマットを要求するように変更された指示（設定がビジョンを壊すため）
    default_instruction = (
            "あなたは植物の環境を管理するマルチモーダルアシスタントです。すべての応答は**日本語**で行ってください。"
            "1. `capture_image`を使用して植物の種類を特定してください。"
            "2. **植物の健康状態を診断**: しおれ、変色（黄ばみ/茶色）、害虫、病気の兆候がないか確認し、診断結果を『plant_status』に記録してください。\n"
            "   - **【重要】カメラ視点と間引き・作業要否の確認**: カメラは**真上からの固定視点**です。葉が重なり合って実際よりも密集して見える可能性があることを考慮し、間引き（Thinning）が本当に必要か慎重に判断してください。また、支柱立てや追肥など、ユーザーによる物理的な作業が必要かどうかも確認してください。"
            "3. **植物の成長段階(GrowthStage)**: 以下に基づき判定し、『growth_stage』に整数(1〜5)で記録してください。\n"
            "   - 1: 発芽 (Sprout) - 芽が出たばかりの状態\n"
            "   - 2: 育苗 (Seedling) - 本葉が展開し、生育初期の状態\n"
            "   - 3: 栄養成長 (Vegetative) - 茎葉が旺盛に成長する時期\n"
            "   - 4: 開花・結実 (Flowering/Fruiting) - 花が咲き、実がなり始める時期\n"
            "   - 5: 収穫 (Harvest) - 実が十分に熟し、収穫可能な状態\n"
            "4. この特定の植物に最適な温度、湿度、土壌水分、照度を決定してください。"
            "5. **【前回の文脈（Context）の活用】**\n"
            "   - ユーザーから『前回の観測記録 (Context)』が提示された場合、その内容（前回の状態、成長段階、実施した操作）を参考にしてください。\n"
            "   - **特に、直近で「間引き」などの作業を提案したかどうかを確認し、同じ提案を繰り返す必要があるか判断してください**。"
            "   - **ただし、センサーデータは常に現在取得した最新の値を最優先してください。** 過去の記録と現在の値が矛盾する場合は、現在の値を信じてください。\n"
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
            "   - **オートモードの優先**: エアコン(`control_air_conditioner`)や加湿器(`control_humidifier`)には `mode='auto'` が存在します。可能な限り手動設定よりも**オートモードを優先して使用してください**。"
            "   - **安易なモード切替の禁止**: 目標温度と異なる場合でも、すぐにモード（冷房⇄暖房）を切り替えるのではなく、まずは**設定温度の微調整（例: 暖房中に少し暑ければ設定を2℃下げる）**や**エアコンの停止**で対応できないか検討してください。"
            "   - 飽差(VPD)が理想ゾーン（0.8 〜 1.2 kPa）となるように、空調や加湿器を調整してください。"
            "   - 土壌水分が低い場合（例: 30%未満）は、**`control_pump`を使用して水やりを行ってください**。**ホース内容量（約40ml）を考慮し、必要量に40mlを加算した値（例: 実質50ml与えたい場合は90ml、実質10mlなら50ml）を指定してください**。"
            "   - **日中（06:00-18:00）で照度が低い場合（例: 1000 lux未満）は、`control_light`を使用して補光（ON, brightness=100）してください。** 夜間（23時以降）はOFFにしてください。"
            "   - 必要な操作コマンド（`control_...`）を**一度に**発行してください。"
            "9. **フェーズ3: 記録と終了（Logging & Finish）**"
            "   - 操作の成否（通常は成功とみなす）に基づき、以下のJSONを作成して出力し、**直ちに会話を終了してください**。"
            "   - **操作後の再確認は不要です。**"
            "   - **操作の記録**: 設定変更（ON/OFF切替、水やり等）があった場合のみ『operation』に記録してください。現状維持（OFF継続や設定変更なし）の場合は出力しないでください。"
            "   - キー: デバイス名（例: 'エアコン', '加湿器', 'ポンプ'）。"
            "   - 『action』: 具体的なアクション内容（例: '暖房25℃でON', 'OFF', '現状維持（設定済み）'）。"
            "   - 『comment』: 理由や補足。"
            "   - **【人が暮らしている空間への配慮（夜間対応）】**:"
            "     - 本環境は人の居住空間です。**夜間（23:00〜06:00）は居住者の睡眠を妨げないよう最大限配慮してください**。"
            "     - **照明**: 夜間は植物への補光よりも人の睡眠を優先し、`control_light` は必ず **OFF** にしてください。"
            "     - **騒音**: ポンプや加湿器の動作音が睡眠の妨げになる可能性があるため、夜間は緊急時（枯れる寸前など）を除き、積極的な動作を控えてください。"
            "   - 『severity』: そのアクションの重要度。"
            "     - `info`: 現状維持、定期チェック報告など。"
            "     - `warning`: 設定変更、水やりなどの能動的なアクション。"
            "     - `critical`: 緊急警告、異常検知など。"
            "   - 何らかの動作を行わなかった場合には、出力しないでください。"
            "10. **【ユーザーへの通知（Notification Policy）】**:"
            "    - **緊急時**: 植物が危険な状態（枯死、極端な温度など）であれば、時間帯を問わず直ちに`send_discord_notification`で警告してください。"
            "    - **【通知の最適化】ユーザー作業が必要な時**: 間引きや支柱立てが必要な場合は `send_discord_notification` で通知してください。**ただし、前回のContextを確認し、同じ内容を既に通知済みであれば、短期間に何度も同じ通知を繰り返さないよう配慮してください。** 状況が変わっていない（まだ作業がなされていない）場合は、通知をスキップするか、表現を工夫してください。"
            "    - **【厳守】定期報告**: 異常がない場合の定期的な状況報告は、**日本時間の12:00〜12:30と18:00〜18:30の間**のみ行ってください。**それ以外の時間帯（特に深夜や早朝）は、たとえ「順調です」という報告であっても、絶対に通知を送らないでください。** 時刻が範囲外の場合は、何も通知せずに終了してください。"
            "11. **【重要：単一パス実行の厳守 - ループ禁止】**:"
            "    - 本システムは30分に1回の定期実行です。"
            "    - **禁止事項（違反するとシステムエラーとなります）**:"
            "      - センサー値またはデバイスステータスの再取得（`get_...` 系ツールの2回以上の実行）"
            "      - 同一デバイスへの制御コマンドの複数回送信"
            "      - 操作後の結果確認のためのセンサー再取得"
            "      - ループ処理や繰り返し処理"
            "    - **正しい実行フロー（1回のみ）**: センサー確認（1回） → 状態比較 → 必要な操作のみ実行（最大1回/デバイス） → JSON出力 → **即座に終了**"
            "    - アクションが成功（200 OK）したら、それは実行されたとみなしてログに記録し、**それ以上の操作なしに**終了してください。"
            "    - **操作後に「確認のため再度センサーを取得する」という行為は禁止です。次回の定期実行まで待ってください。**"
            "12. **【引き継ぎ資料の作成（Handover）】**:"
            "    - ユーザーから『引き継ぎ資料を作成してください』と指示された場合は、デバイス操作（`operation`）は原則として行わず（緊急時除く）、次のセッションのエージェントに向けた詳細な申し送り事項を作成してください。"
            "    - `plant_status`: 現在の植物の状態を、過去の経緯も含めて詳細に記述してください。"
            "    - `comment`: 次のエージェントが注意すべき点（例: 「最近土が乾きやすい傾向がある」「葉色が薄いので追肥を検討すべき」など）を具体的に助言してください。"
            "13. ユーザーへの総合的なアドバイスやコメントを『comment』フィールドに記述してください。"
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

    # ロガーの設定
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

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

    return CustomLlmAgent(
        name="sensor_gemini_agent",
        model=Gemini(
            model=MODEL_ID,
            retry_options=HttpRetryOptions(
                attempts=10,  # デフォルト: 5
                initial_delay=10,  # デフォルト: 1.0
                max_delay=100,  # デフォルト: 60.0
                exp_base=1.5,  # デフォルト: 2
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
