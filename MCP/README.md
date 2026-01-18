# Sensor Image MCP Server

sensor-node の画像APIとSwitchbotデバイスをプロキシし、MCP toolsとして返す FastMCP サーバーです。

## ファイル構成
- `sensor_image_server.py`: 5つのMCPツールを提供するサーバー本体
- `uploader.py`: Google Cloud Storage (GCS) へのアップロード機能
- `requirements.txt`: 必要な依存パッケージ

## 使い方
1) 依存をインストール（仮想環境推奨）:
```bash
pip install -r requirements.txt
```

2) 環境変数の設定:
```bash
export SENSOR_API_BASE=http://192.168.11.226:8000  # センサーノードのURL
export GCS_BUCKET_NAME=your-bucket-name            # 画像アップロード先のGCSバケット
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json  # GCS認証情報
```

3) MCPサーバーを起動（通常はエージェントがStdio経由で自動起動します）:
```bash
python sensor_image_server.py
```

## 提供ツール

### 1. capture_image
画像をキャプチャしてGCSにアップロードします。

- **パラメータ**: 
  - `base_url` (Optional[str]): センサーAPIのベースURL（省略時は環境変数 `SENSOR_API_BASE` を使用）
  - `timeout_seconds` (float): タイムアウト秒数（デフォルト: 30.0）
- **返り値**: GCS URI (`gs://bucket/path`) を含む TextContent
- **動作**: センサーから画像を取得し、GCSにアップロード後、`gs://` URIを返します

### 2. get_meter_data
温度・湿度データを取得します（Switchbot温湿度計）。

- **パラメータ**:
  - `base_url` (Optional[str]): センサーAPIのベースURL
  - `timeout_seconds` (float): タイムアウト秒数（デフォルト: 5.0）
- **返り値**: 温度・湿度データを含む TextContent
- **エンドポイント**: `GET {base_url}/sensor/meter`

### 3. get_soil_moisture
土壌水分データを取得します。

- **パラメータ**:
  - `base_url` (Optional[str]): センサーAPIのベースURL
  - `timeout_seconds` (float): タイムアウト秒数（デフォルト: 5.0）
- **返り値**: 土壌水分データを含む TextContent
- **エンドポイント**: `GET {base_url}/sensor/soil`

### 4. control_air_conditioner
エアコンを制御します（赤外線リモコン経由）。

- **パラメータ**:
  - `temperature` (int): 設定温度（例: 25）
  - `mode` (str): 動作モード - "auto", "cool", "dry", "fan", "heat" のいずれか
  - `fan_speed` (str): 風量 - "auto", "low", "medium", "high" のいずれか
  - `is_on` (bool): 電源状態
  - `base_url` (Optional[str]): センサーAPIのベースURL
  - `timeout_seconds` (float): タイムアウト秒数（デフォルト: 10.0）
- **返り値**: 制御結果を含む TextContent
- **エンドポイント**: `POST {base_url}/control/air-conditioner/settings`

### 5. control_humidifier
加湿器を制御します。

- **パラメータ**:
  - `mode` (str): 動作モード - "auto", "low", "medium", "high" のいずれか
  - `is_on` (bool): 電源状態
  - `base_url` (Optional[str]): センサーAPIのベースURL
  - `timeout_seconds` (float): タイムアウト秒数（デフォルト: 10.0）
- **返り値**: 制御結果を含む TextContent
- **エンドポイント**: `POST {base_url}/control/humidifier/settings`

## GCS統合
`capture_image` ツールは、画像データをBase64で返す代わりに、Google Cloud Storageにアップロードし、`gs://` URIを返します。これにより、大きな画像データをコンテキストウィンドウから分離し、Geminiモデルが効率的に画像を処理できます。

アップロードには以下の環境変数が必要です:
- `GCS_BUCKET_NAME`: アップロード先のバケット名
- `GOOGLE_APPLICATION_CREDENTIALS`: サービスアカウントキーのパス

## 補足
- **ベースURLの優先順位**: 明示的な `base_url` 引数 > `SENSOR_API_BASE` 環境変数 > `http://192.168.11.226:8000` (デフォルト)
- **Stdioトランスポート**: このMCPサーバーはエージェント (`agent/agent.py`) によってStdio経由でサブプロセスとして起動されます
- **複数センサー対応**: 呼び出しごとに `base_url` を変更することで、複数のセンサーノードに対応可能です
