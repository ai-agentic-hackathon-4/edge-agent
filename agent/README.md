# Sensor Gemini Agent (ADK)

Vertex AI Gemini を使いつつ、MCP の `capture_image` ツールでセンサー画像を取得するエージェント定義です。

## ファイル
- sensor_gemini_agent.py: ADK の `root_agent` 定義と MCP 呼び出しヘルパー。
- requirements.txt: エージェント側の依存 (`google-adk`, `mcp`, `httpx`, `anyio`)。

## 前提
- Vertex AI API キー等は環境変数で指定する（値はこのファイル内で定義した変数を参照）。
- MCP サーバー（sensor_image_server.py）が `python sensor_image_server.py` などで起動していること。

## 主な環境変数
- `VERTEX_MODEL`: デフォルト `gemini-3-pro-preview`（Gemini 3 Pro プレビュー、グローバルエンドポイント）。必要に応じて公式IDを上書き。
- `VERTEX_API_KEY`: Vertex AI の API キー（必須）
- `VERTEX_API_BASE`: 例 `https://us-central1-aiplatform.googleapis.com`（必要に応じて）
- `VERTEX_PROJECT`: プロジェクトID（`x-goog-user-project` ヘッダを付けたい場合）
- `VERTEX_LOCATION`: デフォルト `global`（Gemini 3 Pro Preview はグローバルのみ）
- `SENSOR_MCP_SSE_URL`: MCP サーバーの SSE エンドポイント。デフォルト `http://127.0.0.1:8000/sse`
- `SENSOR_API_BASE`: センサーAPIのベースURL。`capture_image` に渡す既定値。デフォルト `http://192.168.11.226:8000`

## 使い方（例）
1) 依存インストール（仮想環境推奨）
```bash
cd edge-agent/agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) sensor-image-server を起動（別ターミナル）
```bash
cd ../MCP
source .venv/bin/activate
python sensor_image_server.py
```

3) エージェントを呼ぶ側の環境変数を設定
```bash
export VERTEX_API_KEY=...  # 必須
export VERTEX_PROJECT=your-project-id
export VERTEX_LOCATION=us-central1
export SENSOR_MCP_SSE_URL=http://127.0.0.1:8000/sse
export SENSOR_API_BASE=http://192.168.11.226:8000
```
4) ADK で実行（例）
```bash
cd edge-agent/agent
adk run sensor_gemini_agent
# または
adk api_server sensor_gemini_agent
```

## メモ
- MCP接続はSSEで行います。FastMCPのデフォルトパスは `/sse` です。
- 複数センサーがある場合、呼び出し側プロンプトで `base_url` を指定する運用にしてください。
