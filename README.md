# Edge Agent with Gemini 3 & MCP

このディレクトリには、Gemini 3 Pro/Flash を使用し、Model Context Protocol (MCP) を介してローカルセンサーから画像をキャプチャする AI エージェントが含まれています。

## 概要

- **Agent Framework**: Google ADK (Agent Development Kit)
- **Model**: `gemini-3-flash-preview` (Vertex AI)
- **Tooling**: MCP (Model Context Protocol)
- **Transport**: Stdio (エージェントがMCPサーバーをサブプロセスとして起動)
- **Features**:
    - 自律的なツール実行 (`capture_image`, `get_meter_data`)
    - マルチモーダル入力処理 (Base64テキスト形式での画像受け渡し)
    - Switchbot 温湿度取得 (MCP経由)

## 前提条件

- **Docker**: 最新版がインストールされていること。
- **Google Cloud Project**:
    - Vertex AI API が有効化されていること。
    - 使用するモデル (`gemini-3-flash-preview`) が利用可能なリージョンであること。
- **API Key**: `GOOGLE_API_KEY` (または Vertex AI 用の `GOOGLE_APPLICATION_CREDENTIALS`)。

## セットアップ

3. **Google Cloud 認証情報の準備 (Service Account)**
   GCSへのアップロードとVertex AIの利用に必要です。
   
   1. GCPコンソールでサービスアカウントを作成し、以下のロールを付与します。
      - **Vertex AI ユーザー** (`roles/aiplatform.user`)
      - **Storage オブジェクト管理者** (`roles/storage.objectAdmin`) または作成者/閲覧者
   2. キーを作成（JSON形式）し、ダウンロードします（例: `credentials.json`）。
   3. `edge-agent/agent/` ディレクトリなどに配置します。

4. **環境変数の設定 (.env)**
   `agent/.env` ファイルを作成/更新します。
   ```env
   # Vertex AI & General
   GOOGLE_GENAI_USE_VERTEXAI=true
   GOOGLE_CLOUD_PROJECT=your-project-id
   GOOGLE_CLOUD_REGION=us-central1
   
   # Authentication
   GOOGLE_APPLICATION_CREDENTIALS=/app/agent/credentials.json  # Docker内パス
   # ローカル実行の場合は絶対パス指定を推奨:
   # GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/credentials.json
   
   # GCS Bucket for Images
   GCS_BUCKET_NAME=your-bucket-name
   
   # Switchbot
   SWITCHBOT_TOKEN=your_token
   SWITCHBOT_SECRET=your_secret
   SWITCHBOT_METER_DEVICE_ID=your_device_id
   ```

5. **Dockerネットワークの作成** (初回のみ)
   ```bash
   docker network create edge-agent-net
   ```

## ビルドと実行

1. **Dockerイメージのビルド**
   `edge-agent` ディレクトリ内で実行します。
   ```bash
   docker build -t edge-agent .
   ```

2. **エージェントの実行**
   以下のコマンドで実行します。`edge-agent/data` ディレクトリがホストに作成され、会話履歴 (`sessions.db`) が自動的に保存されます。
   
   ```bash
   # データディレクトリの作成（なければ）
   mkdir -p data
   
   # 実行
   # credentials.json が agent ディレクトリにあると仮定
   docker run -i --rm \
     --network edge-agent-net \
     --env-file agent/.env \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/agent/ai-agentic-hackathon-4-97df01870654.json:/app/agent/ai-agentic-hackathon-4-97df01870654.json \
     edge-agent
   ```
   
   終了後も `.db` ファイルが残るため、次回起動時に前回の会話の続きから再開できます。
   
   起動後、プロンプトに以下のように入力してください：
   ```
   capture image
   ```
   または
   ```
   今の部屋の温度は？
   ```

3. **簡易実行（Web UI）**
   Dockerを使わず、ローカル環境でWeb UIを使ってエージェントを実行する場合のスクリプトです。
   ※ `requirements.txt` のインストールが必要です。
   
   ```bash
   ./run.sh
   ```
   ブラウザで `http://localhost:8501` にアクセスして操作できます。

## 動作確認 (Verification)

環境依存（MCPライブラリなど）の問題を回避してロジックを確認するためのモック・スクリプトを用意しています。
```bash
python3 scripts/verify_mcp_mocked.py
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
