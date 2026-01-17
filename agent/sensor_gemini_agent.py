import asyncio
import os
from typing import Optional

from google.adk.agents.llm_agent import LlmAgent
from mcp.client.session_group import ClientSessionGroup, SseServerParameters
from mcp.types import CallToolResult, ImageContent, TextContent

# Vertex AI / Gemini 設定（値は環境変数で上書きしてください）
# Gemini 3 Pro プレビュー（グローバルエンドポイント）を既定モデルに設定。
# 公開ドキュメント記載のモデルID: gemini-3-pro-preview
MODEL_ID = "gemini-3-flash-preview"

# MCP (sensor-image-server) 接続先
SENSOR_MCP_SSE_URL = os.getenv("SENSOR_MCP_SSE_URL", "http://127.0.0.1:8000/sse")
DEFAULT_SENSOR_API_BASE = os.getenv("SENSOR_API_BASE", "http://192.168.11.226:8000")


async def fetch_sensor_image(
    width: int = 800,
    height: int = 600,
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
    mcp_sse_url: Optional[str] = None,
) -> CallToolResult:
    """MCP の capture_image ツールを呼び出して画像を取得する。"""
    target_mcp = (mcp_sse_url or SENSOR_MCP_SSE_URL).rstrip("/")
    args = {
        "width": width,
        "height": height,
        "timeout_seconds": timeout_seconds,
    }
    if base_url or DEFAULT_SENSOR_API_BASE:
        args["base_url"] = base_url or DEFAULT_SENSOR_API_BASE

    server_params = SseServerParameters(url=target_mcp)
    async with ClientSessionGroup() as group:
        await group.connect_to_server(server_params)
        return await group.call_tool("capture_image", arguments=args)


def summarize_tool_result(result: CallToolResult) -> str:
    """画像とテキストコンテンツの概要を文字列化（ログ/デバッグ用）。"""
    parts: list[str] = []
    for block in result.content or []:
        if isinstance(block, ImageContent):
            parts.append(f"ImageContent bytes={len(block.data)} mime={block.mimeType}")
        elif isinstance(block, TextContent):
            text_preview = block.text[:120].replace("\n", " ")
            parts.append(f"TextContent: {text_preview}")
        else:
            parts.append(f"Other content: {type(block).__name__}")
    return " | ".join(parts)


# ADK が参照するエージェント定義
root_agent = LlmAgent(
    name="sensor_gemini_agent",
    model=MODEL_ID,
    instruction=(
        "You are a multimodal assistant. "
        "Use the MCP tool 'capture_image' to fetch the latest sensor image when a visual check is needed. "
        "Ask for base_url when multiple sensors exist. Keep replies concise."
    ),
)


async def _demo() -> None:
    """単体デモ: MCPから画像を取得し、メタ情報を表示。"""
    result = await fetch_sensor_image()
    print(summarize_tool_result(result))


if __name__ == "__main__":
    asyncio.run(_demo())
