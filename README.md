# Edge Agent with Gemini 3 & MCP

このディレクトリには、Gemini 3 Pro/Flash を使用し、Model Context Protocol (MCP) を介してローカルセンサーから画像をキャプチャする AI エージェントが含まれています。

## 概要

- **Agent Framework**: Google ADK (Agent Development Kit)
- **Model**: `gemini-3-flash-preview` (Vertex AI)
- **Tooling**: MCP (Model Context Protocol)
- **Transport**: Stdio (エージェントがMCPサーバーをサブプロセスとして起動)
- **Features**:
    - 自律的なツール実行 (`capture_image`)
    - マルチモーダル入力処理 (Base64テキスト形式での画像受け渡し)

## 前提条件

- **Docker**: 最新版がインストールされていること。
- **Google Cloud Project**:
    - Vertex AI API が有効化されていること。
    - 使用するモデル (`gemini-3-flash-preview`) が利用可能なリージョンであること。
- **API Key**: `GOOGLE_API_KEY` (または Vertex AI 用の `GOOGLE_APPLICATION_CREDENTIALS`)。

## セットアップ

1. **環境変数の設定**
   `agent/.env` ファイルを作成し、以下の内容を設定してください。
   ```env
   GOOGLE_API_KEY=your_api_key_here
   GOOGLE_GENAI_USE_VERTEXAI=true
   SENSOR_MCP_SSE_URL=http://mcp-server:8000/sse  # (Stdioモードでは未使用だが念のため)
   ```

2. **Dockerネットワークの作成** (初回のみ)
   ```bash
   docker network create edge-agent-net
   ```

## ビルドと実行

1. **Dockerイメージのビルド**
   カレントディレクトリ (`ai-agentic-hackathon-4`) から実行します。
   ```bash
   docker build -t edge-agent ./edge-agent
   ```

2. **エージェントの実行**
   以下のコマンドで実行します。`edge-agent/data` ディレクトリがホストに作成され、会話履歴 (`sessions.db`) が自動的に保存されます。
   
   ```bash
   # データディレクトリの作成（なければ）
   mkdir -p edge-agent/data
   
   # 実行（会話履歴は自動保存されます）
   docker run -i --rm \
     --network edge-agent-net \
     --env-file edge-agent/agent/.env \
     -v $(pwd)/edge-agent/data:/app/data \
     edge-agent
   ```
   
   終了後も `.db` ファイルが残るため、次回起動時に前回の会話の続きから再開できます。
   
   起動後、プロンプトに以下のように入力してください：
   ```
   capture image
   ```

## トラブルシューティング

- **404 Publisher Model Not Found**:
  - `agent.py` 内の `MODEL_ID` (`gemini-3-flash-preview`) が、現在の GCP プロジェクトおよびリージョンで利用不可です。
  - GCP コンソールでモデルの利用状況を確認するか、コード内のモデルIDを変更してください。

- **401 UNAUTHENTICATED**:
  - `.env` の `GOOGLE_API_KEY` が正しくない、または `GOOGLE_GENAI_USE_VERTEXAI` の設定と矛盾しています。

- **Sensor Connection Error**:
  - MCPサーバー (`MCP/sensor_image_server.py`) 内のデフォルトURL (`http://192.168.11.226:8000`) への疎通を確認してください。

## ファイル構成

- `Dockerfile`: エージェント実行環境の定義
- `agent/agent.py`: エージェント定義 (Gemini 3 + MCP Toolset)
- `MCP/sensor_image_server.py`: センサー操作用 MCP サーバー
- `requirements.txt`: Python依存関係
