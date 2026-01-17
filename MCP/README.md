# Sensor Image MCP Server

sensor-node の画像APIをプロキシし、MCPのImageContentとして返す FastMCP サーバーです。

## ファイル構成
- sensor_image_server.py: `capture_image` ツールを提供する MCP サーバー本体。
- requirements.txt: 必要最小限の依存（`mcp`, `httpx`）。

## 使い方
1) 依存をインストール（仮想環境推奨）:
```bash
pip install -r requirements.txt
```
2) センサーノードのURLを必要に応じて指定:
```bash
export SENSOR_API_BASE=http://sensor-node.local:8000
```
3) MCPサーバーを起動:
```bash
python sensor_image_server.py
```

## ツール: capture_image
- パラメータ: `width` (int, デフォルト800), `height` (int, デフォルト600), `base_url` (呼び出しごとに上書き可能), `timeout_seconds` (float, デフォルト5.0)。
- 返り値: 1つの ImageContent（センサー応答の JPEG/PNG）と、メタ情報とソースURLを含む短い TextContent。

## 補足
- ベースURLの優先順位: 明示的な `base_url` 引数 > `SENSOR_API_BASE` 環境変数 > `http://localhost:8000` デフォルト。
- 期待するセンサーエンドポイント: `GET {base_url}/image?width=...&height=...` が `data_base64` と `format` を含むJSONを返すこと。
- 複数センサーノードを扱う場合は、呼び出しごとに `base_url` を変えることで1対多構成に対応できます。
