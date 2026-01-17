# Edge Agent: Gemma 3n Vision Server

このディレクトリには、Googleの最新マルチモーダルモデル **Gemma 3n (E2B-it)** をローカルPC上で動作させるための環境とサーバーが含まれています。

## 概要

FastAPIベースのサーバーを使用して、OpenAI互換のチャット完了API (`/v1/chat/completions`) を提供します。
テキスト入力に加え、画像入力（Base64またはURL）にも対応しており、Gemma 3nの強力な視覚認識機能を利用できます。

## 動作要件

Gemma 3n E2Bモデルを快適に動作させるため、以下の環境を推奨します。

- **OS**: Linux, Windows (WSL2), macOS
- **メモリ (RAM)**: **16GB以上** (必須)
- **GPU**: NVIDIA GPU (VRAM 6GB以上) 推奨。ない場合はCPUで動作しますが低速です。
- **Python**: 3.10以上

> **注記**: Raspberry Pi 4 (8GB) ではメモリ不足により動作が不安定であるため、PC環境での利用を強く推奨します。

## インストールと起動

このフォルダ (`edge-agent`) を対象のマシンに配置し、以下のスクリプトを実行してください。必要なライブラリのインストールとモデルのダウンロードが自動的に行われます。

```bash
cd edge-agent
./start_gemma_server.sh
```

初回起動時はモデル（約5GB）のダウンロードに時間がかかります。

## 使い方

サーバーは `http://localhost:8000` で起動します。

### API エンドポイント
`POST /v1/chat/completions`

### リクエスト例 (Python/Requests)

付属の `test_vision_input.py` を使用するか、以下のようにリクエストを送信してください。

```python
import requests
import base64

# 画像の準備
image_path = "example.png"
with open(image_path, "rb") as f:
    base64_image = base64.b64encode(f.read()).decode('utf-8')

payload = {
    "model": "google/gemma-3n-E2B-it",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "この画像には何が写っていますか？"},
                {"type": "image_url", "image_url": f"data:image/png;base64,{base64_image}"}
            ]
        }
    ],
    "max_tokens": 512
}

response = requests.post("http://localhost:8000/v1/chat/completions", json=payload)
print(response.json())
```

## 技術詳細

### 自動パッチ機能
Gemma 3n E2Bモデルと `transformers` ライブラリの間には既知の互換性問題（埋め込みサイズの不一致）がありますが、本サーバー (`localLLM/gemma3n_pytorch_server.py`) は起動時にこの問題を自動的に修正するパッチを適用します。ユーザーによる手動修正は不要です。

### 構成ファイル
- `localLLM/gemma3n_pytorch_server.py`: メインサーバーコード
- `start_gemma_server.sh`: 起動用スクリプト
- `venv/`: 仮想環境（スクリプト実行時に作成されます）
