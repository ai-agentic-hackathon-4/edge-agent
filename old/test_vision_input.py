import asyncio
import os
import sys
import traceback

# Ensure agent-engine packs are found
sys.path.append(os.path.join(os.path.dirname(__file__), "../agent-engine/venv/lib/python3.12/site-packages"))

from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

# Define image path
IMAGE_PATH = "/home/nakahara/.gemini/antigravity/brain/426eb039-c907-47e6-8860-e29a87abe7a5/blue_circle_test_1768486111356.png"

# Server settings
API_BASE = "http://localhost:8000/v1"
API_KEY = "sk-no-key-required"
MODEL_NAME = "openai/gemma-3n"

async def main():
    print(f"Testing Vision Input with: {IMAGE_PATH}")
    
    if not os.path.exists(IMAGE_PATH):
        print("Error: Image file not found.")
        return

    # Initialize LLM
    llm = LiteLlm(
        model=MODEL_NAME,
        api_base=API_BASE,
        api_key=API_KEY
    )

    # Read Image
    with open(IMAGE_PATH, "rb") as f:
        image_bytes = f.read()

    # Construct Content with Image
    content = types.Content(
        role="user",
        parts=[
            types.Part.from_text(text="What is in this image? Describe it detail."),
            types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        ]
    )

    print("Sending request to Gemma 3n...")
    try:
        request = LlmRequest(contents=[content])
        print("\n--- Response ---")
        async for response in llm.generate_content_async(request):
            if response.content and response.content.parts:
                 for part in response.content.parts:
                     if part.text:
                         print(part.text, end="", flush=True)
        print("\n----------------")
    except Exception as e:
        print(f"\nError during generation: {e}")
        # traceback.print_exc() 
        print("(Note: This is expected if the server is running in Text-Only mode without mmproj)")

if __name__ == "__main__":
    asyncio.run(main())
