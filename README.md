# Edge Agent with Gemini 3 & MCP

このディレクトリには、Gemini 3 Pro/Flash を使用し、Model Context Protocol (MCP) を介してローカルセンサーから画像をキャプチャする AI エージェントが含まれています。

## 概要

- **Agent Framework**: Google ADK (Agent Development Kit)
- **Model**: `gemini-3-flash-preview` (Vertex AI)
- **Tooling**: MCP (Model Context Protocol) - Stdio transport
- **Features**:
    - 自律的なツール実行（画像キャプチャ、環境データ取得、デバイス制御）
    - マルチモーダル入力処理（GCS経由での画像処理）
    - 環境モニタリング（温度・湿度・土壌水分）
    - デバイス制御（エアコン・加湿器）
    - 植物健康診断と環境最適化

## 提供されるMCPツール

1. **capture_image**: カメラから画像をキャプチャしGCSにアップロード
2. **get_meter_data**: Switchbot温湿度計からデータ取得
3. **get_soil_moisture**: 土壌水分センサーからデータ取得
4. **control_air_conditioner**: 赤外線リモコン経由でエアコン制御
5. **control_humidifier**: 加湿器制御

詳細は `MCP/README.md` を参照してください。

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
   
   # Sensor API (sensor-node URL)
   SENSOR_API_BASE=http://192.168.11.226:8000
   
   # MCP Server Path (optional, for local execution)
   # MCP_SERVER_PATH=/absolute/path/to/MCP/sensor_image_server.py
   
   # Debug Options (optional)
   # DEBUG_MOCK_GCS=true  # GCSアップロードをモック化（開発用）
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
   Dockerを使わず、ローカル環境でエージェントを実行する場合のスクリプトです。
   ※ `requirements.txt` のインストールが必要です。
   
   ```bash
   # 依存関係のインストール
   pip install -r requirements.txt
   
   # エージェント起動（Web UI）
   ./run.sh
   ```
   
   起動後、ADKのデフォルトUIが利用可能になります。

## 動作確認 (Verification)

環境依存（MCPライブラリなど）の問題を回避してロジックを確認するためのモック・スクリプトを用意しています。

### MCP機能の検証
```bash
python3 scripts/verify_mcp_mocked.py
```
`get_meter_data` ツールのロジックをモックを使用して検証します。

### GCSアップロード機能の検証
```bash
python3 scripts/verify_gcs_mocked.py
```
`uploader.py` のGCSアップロードロジックをモックを使用して検証します。

## センサーデータロガー

定期的にセンサーデータを収集し、Firestoreに保存するバックグラウンドサービスです。

### 機能
- 1分間隔で温度・湿度・土壌水分を記録
- 30分間隔で画像をキャプチャしGCSにアップロード
- Firestoreにタイムスタンプ付きでデータを保存
- ログファイルへの記録（ローテーション機能付き）

### 起動・停止
```bash
# 起動
./scripts/start_logger.sh

# 停止
./scripts/stop_logger.sh
```

### 要件
- `agent/.env` に以下の環境変数が設定されていること:
  - `GOOGLE_APPLICATION_CREDENTIALS`
  - `GCS_BUCKET_NAME`
  - `SENSOR_API_BASE`
- Firestore データベース: `ai-agentic-hackathon-4-db`

## トラブルシューティング

- **404 Publisher Model Not Found**:
  - `agent/agent.py` 内の `MODEL_ID` (`gemini-3-flash-preview`) が、現在の GCP プロジェクトおよびリージョンで利用不可です。
  - GCP コンソールでモデルの利用状況を確認するか、コード内のモデルIDを変更してください。
  - 利用可能なモデル例: `gemini-1.5-flash`, `gemini-1.5-pro`

- **401 UNAUTHENTICATED**:
  - `.env` の `GOOGLE_APPLICATION_CREDENTIALS` が正しくない、またはサービスアカウントに適切な権限がありません。
  - 必要な権限: Vertex AI ユーザー (`roles/aiplatform.user`), Storage オブジェクト管理者 (`roles/storage.objectAdmin`)

- **GCS Upload Failed**:
  - `GCS_BUCKET_NAME` が正しく設定されているか確認してください。
  - サービスアカウントにバケットへの書き込み権限があるか確認してください。
  - バケットが存在し、適切なリージョンに作成されているか確認してください。

- **Sensor Connection Error**:
  - MCPサーバー内のデフォルトURL (`http://192.168.11.226:8000`) への疎通を確認してください。
  - `SENSOR_API_BASE` 環境変数で正しいURLを指定してください。
  - sensor-nodeが起動しており、ネットワーク経由でアクセス可能か確認してください。

- **MCP Server Launch Failed**:
  - `MCP_SERVER_PATH` が正しいパスを指しているか確認してください（デフォルト: `/app/MCP/sensor_image_server.py`）。
  - MCPサーバーの依存関係（`mcp`, `httpx` 等）がインストールされているか確認してください。

- **Air Conditioner Control Error**:
  - エラーメッセージにURLが含まれます。sensor-nodeのエンドポイントが正しく実装されているか確認してください。
  - モード (`mode`) と風量 (`fan_speed`) のパラメータが有効な値か確認してください。

## 技術的な実装詳細

### GCS統合とマルチモーダル処理
エージェントは、大きな画像データを効率的に扱うために以下の仕組みを実装しています:

1. **GCS アップロード**: `capture_image` ツールは、センサーから取得した画像をGoogle Cloud Storageにアップロードし、`gs://` URIを返します。
2. **GCSAwareMcpToolset**: MCP toolsetのラッパーで、`gs://` URIを検出し、`genai_types.Part.from_uri()` を使用してGeminiモデルが処理できる形式に自動変換します。
3. **Monkey Patch**: ADKのデフォルト実装は全ての戻り値をJSONに変換しようとするため、`Part` オブジェクトが壊れます。`__build_response_event` 関数にパッチを適用し、`Part` オブジェクトを保持します。

この仕組みにより、Geminiモデルは画像を直接GCSから読み込み、Base64エンコードのオーバーヘッドなしに処理できます。

### Stdio トランスポート
MCPサーバーは、エージェント起動時にサブプロセスとして自動的に起動されます（`StdioConnectionParams` 使用）。これにより、外部サーバーを別途起動する必要がなく、エージェントの起動が簡素化されます。

## ファイル構成

- **Dockerfile**: エージェント実行環境の定義
- **requirements.txt**: Python依存関係（ルートレベル）
- **run.sh**: ローカル実行用スクリプト（Web UI起動）
- **agent/**
  - `agent.py`: エージェント本体（Gemini 3 + MCP Toolset + GCS統合）
  - `README.md`: エージェント詳細ドキュメント
- **MCP/**
  - `sensor_image_server.py`: 5つのツールを提供するMCPサーバー
  - `uploader.py`: GCSアップロード機能
  - `requirements.txt`: MCP依存関係
  - `README.md`: MCPサーバー詳細ドキュメント
- **scripts/**
  - `sensor_logger.py`: Firestoreベースのセンサーデータロガー
  - `start_logger.sh` / `stop_logger.sh`: ロガー管理スクリプト
  - `verify_mcp_mocked.py` / `verify_gcs_mocked.py`: モック検証スクリプト
- **old/**: レガシーコード（Gemma 3n ローカルサーバー等）
