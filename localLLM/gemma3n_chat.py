import os
import gradio as gr
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

MEMORY_LENGTH = 2
CONTEXT_SIZE = 2048
MAX_TOKENS = 512
REPO_ID = os.environ.get("GEMMA3N_REPO_ID", "")
GGUF_FILE = os.environ.get("GEMMA3N_GGUF_FILE", "")
N_GPU_LAYERS = int(os.environ.get("GEMMA3N_N_GPU_LAYERS", "0"))

if not REPO_ID or not GGUF_FILE:
    raise ValueError("Set GEMMA3N_REPO_ID and GEMMA3N_GGUF_FILE for the GGUF source.")

model_path = hf_hub_download(repo_id=REPO_ID, filename=GGUF_FILE)
llm = Llama(model_path, n_gpu_layers=N_GPU_LAYERS, n_ctx=CONTEXT_SIZE)


def construct_prompt(message, history):
    prompt_parts = []
    if history:
        for user_msg, assistant_msg in history[-MEMORY_LENGTH:]:
            prompt_parts.append("<start_of_turn>user\n" + user_msg + "<end_of_turn>\n<start_of_turn>model\n" + assistant_msg + "<end_of_turn>\n")
    prompt_parts.append("<start_of_turn>user\n" + message + "<end_of_turn>\n<start_of_turn>model\n")
    return "".join(prompt_parts)


def predict(message, history):
    prompt = construct_prompt(message, history)
    streamer = llm.create_completion(prompt, max_tokens=MAX_TOKENS, stream=True)
    answer = ""
    for msg in streamer:
        choice = msg["choices"][0]
        if "text" in choice:
            token = choice["text"]
            if token != "<":
                answer += token
                yield answer


gr.ChatInterface(predict).queue().launch()
