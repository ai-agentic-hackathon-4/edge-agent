# Sensor Gemini Agent (ADK)

Google ADK (Agent Development Kit) と Vertex AI Gemini 3 を使用し、Model Context Protocol (MCP) 経由でセンサー制御と画像処理を行うエージェントです。

## ファイル
- `agent.py`: ADK の `root_agent` 定義、GCS対応のMCPツールセットラッパー、マルチモーダルPart処理のためのmonkey patch実装
- `__init__.py`: パッケージ初期化ファイル

## アーキテクチャ

### MCPトランスポート: Stdio
このエージェントは **Stdio** トランスポートを使用してMCPサーバーと通信します。エージェント起動時に `sensor_image_server.py` をサブプロセスとして自動的に起動し、標準入出力経由で通信します。

### GCS対応ラッパー (`GCSAwareMcpToolset`)
`capture_image` ツールから返されるGCS URI (`gs://...`) を自動的に検出し、Geminiモデルが処理できる `genai_types.Part` オブジェクトに変換します。これにより、大きな画像データをBase64でエンコードせずに効率的に扱えます。

### Monkey Patch: マルチモーダルPart対応
ADKのデフォルト実装は、ツールの戻り値を強制的にJSON辞書に変換するため、`Part` オブジェクトが壊れてしまいます。この問題を解決するため、`__build_response_event` 関数にmonkey patchを適用し、`Part` オブジェクトをそのまま保持できるようにしています。

## 主な環境変数

### Vertex AI 設定
- `GOOGLE_GENAI_USE_VERTEXAI`: `true` に設定（Vertex AI使用）
- `GOOGLE_CLOUD_PROJECT`: GCPプロジェクトID（必須）
- `GOOGLE_CLOUD_REGION`: リージョン（例: `us-central1`）
- `GOOGLE_APPLICATION_CREDENTIALS`: サービスアカウントキーのパス（必須）

### GCS設定
- `GCS_BUCKET_NAME`: 画像アップロード先のバケット名（必須）

### センサーAPI設定
- `SENSOR_API_BASE`: センサーノードのベースURL（デフォルト: `http://192.168.11.226:8000`）

### MCP設定
- `MCP_SERVER_PATH`: MCPサーバースクリプトのパス（デフォルト: `/app/MCP/sensor_image_server.py`）

## モデル設定
現在のモデル: `gemini-3-flash-preview` (Gemini 3 Flash)
- 高速な応答と効率的なコスト
- マルチモーダル対応（テキスト + 画像）
- コード内の `MODEL_ID` 変数で変更可能

## エージェントの指示 (Instruction)
エージェントは植物環境管理アシスタントとして以下のワークフローを実行します:
1. `capture_image` で植物の種類を識別
2. 植物の健康状態を診断（しおれ、変色、害虫、病気）
3. 最適な温度・湿度・土壌水分を決定
4. `get_meter_data` と `get_soil_moisture` で現在の状態を取得
5. 現在値と最適値を比較
6. 必要に応じて `control_air_conditioner` または `control_humidifier` で調整
7. 土壌水分が低い場合はユーザーに水やりを助言
8. 条件が適切な場合は省エネのためデバイスをオフ

## 使い方（Docker）
推奨される実行方法です。詳細はルートの `README.md` を参照してください。

```bash
docker build -t edge-agent .
docker run -i --rm \
  --env-file agent/.env \
  -v $(pwd)/data:/app/data \
  edge-agent
```

## 使い方（ローカル）
開発やデバッグ用です。

1) 依存インストール:
```bash
pip install -r requirements.txt
```

2) 環境変数を設定（`.env` ファイル推奨）:
```bash
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_REGION=us-central1
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
export GCS_BUCKET_NAME=your-bucket-name
export MCP_SERVER_PATH=/absolute/path/to/MCP/sensor_image_server.py
```

3) エージェント実行:
```bash
adk run agent
```

## 提供される機能
エージェントは以下のMCPツールにアクセスできます:
- **capture_image**: 画像キャプチャ＋GCSアップロード
- **get_meter_data**: 温度・湿度取得
- **get_soil_moisture**: 土壌水分取得
- **control_air_conditioner**: エアコン制御
- **control_humidifier**: 加湿器制御

詳細は `MCP/README.md` を参照してください。
