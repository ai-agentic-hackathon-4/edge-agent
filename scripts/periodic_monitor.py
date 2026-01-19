import sys
import os
import asyncio
import logging

# Add project root to path to allow importing agent.agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

# Setup base dir
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load env vars from edge-agent/agent/.env
# Note: overrides=True (default false in python-dotenv, check usage... actually it defaults to False, so existing env wins. But here we want to load from file first?)
# Actually we want local override.
env_path = os.path.join(base_dir, "agent", ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

# Force overwrite credentials for local execution if key exists
key_filename = "ai-agentic-hackathon-4-97df01870654.json"
local_key_path = os.path.join(base_dir, "agent", key_filename)
if os.path.exists(local_key_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_key_path
    print(f"Set GOOGLE_APPLICATION_CREDENTIALS to: {local_key_path}")

# Set MCP server path
if "MCP_SERVER_PATH" not in os.environ or os.environ["MCP_SERVER_PATH"].startswith("/app"):
    mcp_path = os.path.join(base_dir, "MCP", "sensor_image_server.py")
    os.environ["MCP_SERVER_PATH"] = mcp_path
    print(f"Set MCP_SERVER_PATH to: {mcp_path}")

# Fetch instruction from Firestore
try:
    from google.cloud import firestore
    # Verify we have creds before connecting
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        db = firestore.Client(database="ai-agentic-hackathon-4-db")
        doc = db.collection("configurations").document("edge_agent").get()
        if doc.exists:
            data = doc.to_dict()
            if "instruction" in data:
                print("Loaded AGENT_INSTRUCTION from Firestore.")
                os.environ["AGENT_INSTRUCTION"] = data["instruction"]
    else:
        print("Warning: GOOGLE_APPLICATION_CREDENTIALS not set, skipping Firestore fetch.")
except Exception as e:
    print(f"Warning: Failed to fetch instruction from Firestore: {e}")

# Import after setting env vars
from agent.agent import create_agent
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.runners import Runner
from google.genai import types

async def main():
    # Setup Session Service
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "sessions.db")
    session_uri = f"sqlite+aiosqlite:///{db_path}"
    
    print(f"Using Session DB: {session_uri}")
    session_service = DatabaseSessionService(db_url=session_uri)
    
    # Create Agent
    print("Creating agent...")
    agent = create_agent()
    
    # Create Runner
    print("Creating runner...")
    runner = Runner(
        app_name="periodic_monitor_app",
        agent=agent,
        session_service=session_service,
    )
    
    user_id = "periodic_monitor_user"
    session_id = "periodic_monitor_session_v1" # Fixed session for persistence
    
    # Ensure session exists
    print(f"Checking session {session_id}...")
    session = await session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    if not session:
        print(f"Session {session_id} not found, creating new one...")
        await session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id
        )
    else:
        print(f"Found existing session {session_id}.")
    
    user_message = "現在の植物の状態を確認してください。"
    message_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    )
    
    print(f"Starting agent run for session {session_id}...")
    
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message_content
        ):
            # Process content
            if event.content:
                for part in event.content.parts:
                    if part.text:
                        print(f"[Agent]: {part.text}")
            
            # Debug: print logic for function calls if needed
            # if event.get_function_calls():
            #    print(f"[Tool Call]: {event.get_function_calls()}")
            
    except Exception as e:
        print(f"Error executing agent: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Setup logging
    # logging.basicConfig(level=logging.DEBUG) # Uncomment for debug
    asyncio.run(main())
