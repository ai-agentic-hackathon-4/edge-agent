
import os
import time
import requests
import schedule
import datetime
import sys

# Configuration
AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://agent:8080")
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "30"))
START_QUIET_HOUR = int(os.environ.get("START_QUIET_HOUR", "22")) # 22:00
END_QUIET_HOUR = int(os.environ.get("END_QUIET_HOUR", "7"))     # 07:00
PROMPT_MESSAGE = "定期モニタリングを実行してください。植物の状態、土壌水分、環境データ(温度/湿度/照度)を確認し、必要なら水やりや空調調整を行い、ログに残してください。"

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stdout, flush=True)

def is_quiet_time():
    now = datetime.datetime.now()
    hour = now.hour
    # Handle overnight range (e.g. 22 to 7)
    if START_QUIET_HOUR > END_QUIET_HOUR:
        return hour >= START_QUIET_HOUR or hour < END_QUIET_HOUR
    else:
        return START_QUIET_HOUR <= hour < END_QUIET_HOUR

def run_job():
    if is_quiet_time():
        log(f"Skipping execution: Quiet time ({START_QUIET_HOUR}:00 - {END_QUIET_HOUR}:00)")
        return

    log("Starting periodic monitoring job...")
    
    # 1. Create/Get Session (Agent API usually needs a session to track context, or we can use stateless?)
    # The ADK API usually exposes POST /agent/sessions to create a session
    # Then POST /agent/sessions/{session_id}/turns to invoke.
    
    try:
        # Create session
        session_url = f"{AGENT_API_URL}/apps/agent/users/default/sessions"
        resp = requests.post(session_url, json={})
        if resp.status_code != 200:
            log(f"Error creating session: {resp.status_code} {resp.text}")
            return
            
        session_id = resp.json().get("session_id") # Adjust if key is different based on ADK version
        # Some ADK versions return the object directly
        # Let's inspect response in real implementation or be robust.
        # Assuming ADK default response.
        
        # Actually, ADK 0.3+ (implied) might just use /agent/invoke if no session management needed?
        # But let's assume session-based for conversation history.
        # If response doesn't have session_id, maybe it's the ID itself?
        
        log(f"Created session: {session_id} (Response: {resp.json()})")
        if not session_id:
             # Fallback if response structure is different
             session_id = resp.json().get("name", "").split("/")[-1] # if resource name

        if not session_id:
            log("Could not extract session_id.")
            return

        # 2. Send Prompt
        turn_url = f"{AGENT_API_URL}/apps/agent/users/default/sessions/{session_id}/turns"
        payload = {
            "queries": [
                {"text": PROMPT_MESSAGE}
            ]
        }
        
        log(f"Sending prompt to {turn_url}...")
        resp = requests.post(turn_url, json=payload, timeout=120)
        
        if resp.status_code == 200:
            log("Job completed successfully.")
            data = resp.json()
            log(f"Agent Response: {data}")

            # --- Firestore Logging ---
            try:
                from google.cloud import firestore
                import json
                
                # Check authentication
                if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ or "GOOGLE_CLOUD_PROJECT" in os.environ:
                    # Initialize DB (assumes project ID from env or default)
                    # For local emulator or if project ID is implicit
                    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
                    if project_id:
                        db = firestore.Client(project=project_id, database="ai-agentic-hackathon-4-db")
                    else:
                        db = firestore.Client(database="ai-agentic-hackathon-4-db")

                    # Extract the actual agent message.
                    # ADK response structure: { "steps": [ { "content": { "parts": [ { "text": "JSON_STRING" } ] } } ] }
                    # Or simple output if simplified.
                    # We need to parse the JSON string embedded in the response text if using structured output mode.
                    
                    # Assuming data is the JSON body of the response.
                    # We need to find the text part.
                    agent_text = ""
                    # Simple heuristic traversal
                    if "steps" in data:
                        for step in data["steps"]:
                            if "content" in step and "parts" in step["content"]:
                                for part in step["content"]["parts"]:
                                    if "text" in part:
                                        agent_text += part["text"]

                    if not agent_text:
                        # Fallback: maybe directly in response if different format
                        agent_text = json.dumps(data)

                    # Try to parse agent_text as JSON (since we requested JSON mode)
                    clean_text = agent_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    
                    try:
                        structured_data = json.loads(clean_text)
                    except json.JSONDecodeError:
                        # If not JSON, save as raw text wrapped in dict
                        structured_data = {"raw_output": agent_text}

                    # Add metadata
                    log_entry = {
                        "timestamp": datetime.datetime.now(datetime.timezone.utc),
                        "session_id": session_id,
                        "data": structured_data
                    }

                    # Save to Firestore
                    doc_ref = db.collection("agent_execution_logs").document()
                    doc_ref.set(log_entry)
                    log(f"Saved execution log to Firestore (ID: {doc_ref.id})")
                
                else:
                    log("Skipping Firestore save: No credentials found.")

            except Exception as e:
                log(f"Error saving to Firestore: {e}")
            # -------------------------

        else:
            log(f"Job failed: {resp.status_code} {resp.text}")

    except Exception as e:
        log(f"Exception during job execution: {e}")

def main():
    log(f"Scheduler started. Target: {AGENT_API_URL}, Interval: {INTERVAL_MINUTES} min")
    
    # Run once immediately on startup? Or wait?
    # Usually better to wait or run after small delay.
    # Let's run immediately for verification, then schedule.
    # run_job() 

    schedule.every(INTERVAL_MINUTES).minutes.do(run_job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # Wait for API to be ready
    log("Waiting for Agent API to be ready...")
    time.sleep(30) 
    main()
