import base64
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

API_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "openai/gemma-3n"
MAX_TOKENS = 64
TIMEOUT = None  # No timeout (wait indefinitely)


def ensure_image(path: Path) -> Path:
    if path.exists():
        return path
    img = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 40, 216, 216), fill="blue")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def main() -> None:
    img_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tmp_gemma_cpu.png")
    img_path = ensure_image(img_path)

    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "この画像に写っている形と色を教えて。"},
                    {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }

    print(f"Sending request to {API_URL} with timeout={TIMEOUT}")
    start = time.monotonic()
    resp = requests.post(API_URL, json=payload, timeout=TIMEOUT)
    elapsed = time.monotonic() - start
    print(f"Status: {resp.status_code}")
    print(f"Elapsed: {elapsed:.2f} sec")
    try:
        print(resp.json())
    except Exception:
        print(resp.text)


if __name__ == "__main__":
    main()
