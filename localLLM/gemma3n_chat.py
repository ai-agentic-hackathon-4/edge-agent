import sys
import os
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Llava15ChatHandler

# モデルパス設定 (セットアップガイドに合わせて調整してください)
MODEL_PATH = "./models/gemma-3n-e2b-it-q4_k_m.gguf"
# Vision用プロジェクター(mmproj)がある場合は指定 (Gemma 3nのサポート状況による)
MMPROJ_PATH = None # 例: "./models/gemma-3n-mmproj.gguf"

def main():
    if not os.path.exists(MODEL_PATH):
        print(f"Error: Model not found at {MODEL_PATH}")
        print("Please download the model first (see gemma3n_setup_guide.md)")
        return

    print(f"Loading model: {MODEL_PATH}...")
    
    # チャットハンドラーの設定 (Visionモデルの場合)
    # 注意: Gemma 3nのVisionサポートはllama.cppのバージョンに依存します。
    # 汎用的なハンドラーとしてLlava15ChatHandlerを使用する例ですが、
    # モデルによっては clip_model_path が必要な場合があります。
    chat_handler = None
    if MMPROJ_PATH and os.path.exists(MMPROJ_PATH):
        try:
             chat_handler = Llava15ChatHandler(clip_model_path=MMPROJ_PATH)
             print("Vision support enabled (via mmproj).")
        except Exception as e:
             print(f"Warning: Failed to load vision handler: {e}")

    # モデル読み込み (n_ctxは必要に応じて増やす)
    llm = Llama(
        model_path=MODEL_PATH,
        chat_handler=chat_handler,
        n_ctx=2048, 
        n_gpu_layers=-1, # Raspberry PiではCPU使用が基本ですが、Vulkan等が使える場合は調整
        verbose=True
    )

    print("\n--- Gemma 3n Chat (type 'quit' to exit) ---")
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant running on a Raspberry Pi."}
    ]

    while True:
        try:
            user_input = input("\nUser: ")
            if user_input.lower() in ["quit", "exit"]:
                break
            
            # 画像入力ロジックの例 (画像パスが入力された場合)
            # 形式: "image: /path/to/image.jpg Describe this."
            content = []
            if user_input.startswith("image:"):
                parts = user_input.split(" ", 2)
                if len(parts) >= 2:
                    img_path = parts[1]
                    text_query = parts[2] if len(parts) > 2 else "Describe this image."
                    
                    # 画像URL/Pathをメッセージに追加
                    content.append({"type": "image_url", "image_url": {"url": f"file://{img_path}"}})
                    content.append({"type": "text", "text": text_query})
                else:
                    content = user_input
            else:
                content = user_input

            messages.append({"role": "user", "content": content})

            # 推論実行
            response = llm.create_chat_completion(
                messages=messages,
                max_tokens=256,
                temperature=0.7
            )

            response_text = response['choices'][0]['message']['content']
            print(f"Gemma: {response_text}")
            
            messages.append({"role": "assistant", "content": response_text})

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
