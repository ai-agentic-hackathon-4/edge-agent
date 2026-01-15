# Gemma 3n on Raspberry Pi 4 Setup Guide

Gemma 3n (Gemma 3 Nano) を Raspberry Pi 4 上の llama.cpp で動作させるための手順書です。

## 1. 前提条件

- **Hardware**: Raspberry Pi 4 Model B (推奨: RAM 8GB, 最小: 4GB)
- **OS**: Raspberry Pi OS (64-bit) Bookworm 推奨
- **Storage**: MicroSD 32GB以上 (モデルファイル保存用)

## 2. システムの準備

ターミナルを開き、パッケージを更新し、ビルドツールをインストールします。

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential git cmake curl
```

## 3. llama.cpp のインストール

Raspberry Pi 4 用に最適化してビルドします。

```bash
# クローン
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# ビルド (Raspberry Pi 4はNeon対応なのでデフォルトでOK、高速化のためにオプション追加も可)
cmake -B build
cmake --build build --config Release
```

## 4. Gemma 3n モデルのダウンロード

Hugging Face から GGUF 形式のモデルをダウンロードします。
Gemma 3n は `E2B` (Effective 2B) サイズが Raspberry Pi 4 に適しています。

```bash
# モデル保存用ディレクトリ作成
mkdir -p models

# ggml-org/gemma-3n-E2B-it-GGUF から Q4_K_M (バランスの良い量子化モデル) をダウンロード
# 注意: URLは変更される可能性があります。Hugging Faceのページを確認してください。
curl -L -o models/gemma-3n-e2b-it-q4_k_m.gguf https://huggingface.co/ggml-org/gemma-3n-E2B-it-GGUF/resolve/main/gemma-3n-e2b-it-q4_k_m.gguf
```

※ **画像入力 (Multimodal) について**:
Gemma 3n はネイティブでマルチモーダル対応ですが、llama.cpp での画像入力サポート状況は開発段階の場合があります。
もし画像入力を行う場合、対応する `mmproj` ファイルが必要になるか、または GGUF ファイル内に統合されている必要があります。
現状、安定して画像入力を行うなら **PaliGemma** や **Llava** も選択肢になりますが、Gemma 3n を試す場合は以下の手順参考にしてください。

## 5. 実行確認 (テキストチャット)

まずはテキストのみで動作確認します。

```bash
./build/bin/llama-cli -m models/gemma-3n-e2b-it-q4_k_m.gguf -p "自己紹介してください" -n 200
```

## 6. 画像入力の実行 (Python経由)

`llama-cpp-python` を使用してプログラムから制御します。

### Python環境セットアップ

```bash
sudo apt install -y python3-pip python3-venv
python3 -m venv venv
source venv/bin/activate
# llama-cpp-python のインストール (ビルド済み共有ライブラリを使用するか、再ビルド)
CMAKE_ARGS="-DGGML_NEON=ON" pip install llama-cpp-python
```

### 実行スクリプト

`gemma3n_chat.py` を使用してチャットを行います（画像入力ロジック含む）。
