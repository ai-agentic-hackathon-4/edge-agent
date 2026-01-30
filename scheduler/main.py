
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
        session_url = f"{AGENT_API_URL}/agent/sessions"
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
        turn_url = f"{AGENT_API_URL}/agent/sessions/{session_id}/turns"
        payload = {
            "queries": [
                {"text": PROMPT_MESSAGE}
            ]
        }
        
        log(f"Sending prompt to {turn_url}...")
        resp = requests.post(turn_url, json=payload, timeout=120)
        
        if resp.status_code == 200:
            log("Job completed successfully.")
            # Optional: Print agent response summary
            data = resp.json()
            # Try to find text response
            log(f"Agent Response: {data}")
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
