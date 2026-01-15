
import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Union, Dict, Any
import torch
from transformers import AutoModelForCausalLM, AutoProcessor
from PIL import Image
import io
import base64
import requests

# --- Configuration ---
MODEL_ID = "google/gemma-3n-E2B-it"
PORT = 8000
HOST = "0.0.0.0"

app = FastAPI(title="Gemma 3n Vision Server (PC Optimized)")

model = None
processor = None

# --- Monkey Patch for Transformers (Gemma 3n E2B Fix) ---
def apply_gemma3n_patch():
    """
    Patches Gemma3nTextModel.get_per_layer_inputs to handle embedding size mismatch
    specifically for the E2B condensed model variant.
    """
    try:
        from transformers.models.gemma3n.modeling_gemma3n import Gemma3nTextModel
        
        print("Applying runtime patch to Gemma3nTextModel.get_per_layer_inputs...")
        
        original_method = Gemma3nTextModel.get_per_layer_inputs
        
        def patched_get_per_layer_inputs(self, input_ids: torch.LongTensor) -> torch.Tensor:
            embeddings = self.embed_tokens_per_layer(input_ids)
            expected_size = self.config.num_hidden_layers * self.hidden_size_per_layer_input
            
            # If embedding size doesn't match expected size (e.g. 2048 vs 7680)
            if embeddings.shape[-1] != expected_size:
                condensed_layers = embeddings.shape[-1] // self.hidden_size_per_layer_input
                if condensed_layers * self.hidden_size_per_layer_input == embeddings.shape[-1]:
                    # Reshape to [Batch, Seq, condensed, Hidden]
                    embeddings = embeddings.reshape(
                        *input_ids.shape,
                        condensed_layers,
                        self.hidden_size_per_layer_input,
                    )
                    # Repeat to fill all layers
                    target_layers = self.config.num_hidden_layers
                    num_repeats = (target_layers + condensed_layers - 1) // condensed_layers
                    embeddings = embeddings.repeat(1, 1, num_repeats, 1)
                    embeddings = embeddings[:, :, :target_layers, :]
                    return embeddings

            return embeddings.reshape(
                *input_ids.shape,
                self.config.num_hidden_layers,
                self.hidden_size_per_layer_input,
            )

        Gemma3nTextModel.get_per_layer_inputs = patched_get_per_layer_inputs
        print("Patch applied successfully.")
        
    except ImportError:
        print("Warning: Could not import Gemma3nTextModel. Patch skipped (transformers version mismatch?).")
    except Exception as e:
        print(f"Warning: Failed to apply patch: {e}")

# --- Models ---
class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Union[str, Dict[str, Any]]]]

class ChatCompletionRequest(BaseModel):
    model: str = "gemma-3n"
    messages: List[ChatMessage]
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: Dict[str, str]
    finish_reason: str

class ChatCompletionResponse(BaseModel):
    id: str = "chatcmpl-default"
    object: str = "chat.completion"
    created: int = 0
    model: str
    choices: List[ChatCompletionResponseChoice]

# --- Helpers ---
def process_image_input(image_input):
    if isinstance(image_input, str):
        if image_input.startswith("http"):
             return Image.open(requests.get(image_input, stream=True).raw)
        elif image_input.startswith("data:image"):
             # Base64
             header, encoded = image_input.split(",", 1)
             data = base64.b64decode(encoded)
             return Image.open(io.BytesIO(data))
        else:
             # Assume file path or raw base64
             try:
                 data = base64.b64decode(image_input)
                 return Image.open(io.BytesIO(data))
             except:
                 if os.path.exists(image_input):
                     return Image.open(image_input)
    return None

# --- Startup ---
@app.on_event("startup")
async def startup_event():
    global model, processor
    print("Starting Gemma 3n Vision Server (High Performance Mode)...")
    
    # 1. Apply Patch
    apply_gemma3n_patch()
    
    # 2. Load Processor
    print(f"Loading processor for {MODEL_ID}...")
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    
    # 3. Load Model
    print(f"Loading model {MODEL_ID}...")
    try:
        # Standard loading for 16GB+ RAM
        # device_map="auto" will use GPU if available, otherwise CPU RAM (which is fast enough if it fits)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, 
            torch_dtype=torch.float16,
            trust_remote_code=False, # Use patched library code
            device_map="auto" 
        )
        print(f"Model loaded successfully on {model.device}.")
        
    except Exception as e:
        print(f"CRITICAL ERROR loading model: {e}")
        raise e

# --- Endpoints ---
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    global model, processor
    if not model:
        raise HTTPException(status_code=500, detail="Model not loaded")

    conversation = []
    
    for msg in request.messages:
        content_obj = None
        if isinstance(msg.content, str):
            content_obj = msg.content
        elif isinstance(msg.content, list):
            content_parts = []
            for part in msg.content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        content_parts.append({"type": "text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url_field = part.get("image_url", {})
                        # Handle OpenAI format {"url": "..."}
                        val = url_field if isinstance(url_field, str) else url_field.get("url")
                        img = process_image_input(val)
                        if img:
                            content_parts.append({"type": "image", "image": img})
            content_obj = content_parts
        
        conversation.append({"role": msg.role, "content": content_obj})

    try:
        # Prompt Formatting
        prompt = processor.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
        
        # Extract Images
        all_images = []
        for msg in conversation:
            if isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if part.get("type") == "image":
                        all_images.append(part["image"])
        
        if not all_images:
            all_images = None

        # Process Inputs
        inputs = processor(text=prompt, images=all_images, return_tensors="pt")
        inputs = inputs.to(model.device)
        
        # Generate
        with torch.no_grad():
            outputs = model.generate(
                **inputs, 
                max_new_tokens=request.max_tokens,
                do_sample=(request.temperature > 0),
                temperature=request.temperature
            )
            
        # Decode
        input_len = inputs.input_ids.shape[1]
        generated_tokens = outputs[0][input_len:]
        response_text = processor.decode(generated_tokens, skip_special_tokens=True)

        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message={"role": "assistant", "content": response_text},
                    finish_reason="stop"
                )
            ]
        )

    except Exception as e:
        print(f"Generation Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
