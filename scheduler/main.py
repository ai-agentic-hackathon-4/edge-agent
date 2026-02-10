
import os
import time
import requests
import schedule
import datetime
import sys
import json

# Configuration
AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://agent:8080")
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "30"))
QUIET_INTERVAL_MINUTES = int(os.environ.get("QUIET_INTERVAL_MINUTES", "120"))
START_QUIET_HOUR = int(os.environ.get("START_QUIET_HOUR", "22")) # 22:00
END_QUIET_HOUR = int(os.environ.get("END_QUIET_HOUR", "7"))     # 07:00
AGENT_TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "1500"))
PROMPT_MESSAGE = "定期モニタリングを実行してください。植物の状態、土壌水分、環境データ(温度/湿度/照度)を確認し、必要なら水やりや空調調整を行い、ログに残してください。"
HANDOVER_PROMPT = """このセッションは終了します。次の担当エージェントへの引き継ぎ資料を作成してください。
現在の植物の健康状態、成長段階、および特に注意すべき点を詳細に分析し、
`plant_status` および `comment` フィールドに記述してください。
デバイスの操作は不要です（`operation`は空にするか現状維持としてください）。"""
# Session lifetime configuration
SESSION_LIFETIME_DAYS = int(os.environ.get("SESSION_LIFETIME_DAYS", "3"))

# Session persistence file path
SESSION_FILE_PATH = os.environ.get("SESSION_FILE_PATH", "/app/data/current_session.json")
# Context persistence file path
CONTEXT_FILE_PATH = os.environ.get("CONTEXT_FILE_PATH", "/app/data/latest_context.json")

# Global state for tracking last successful run
LAST_RUN_TIME = None

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stdout, flush=True)

def is_quiet_hour(hour):
    # Handle overnight range (e.g. 22 to 7)
    if START_QUIET_HOUR > END_QUIET_HOUR:
        return hour >= START_QUIET_HOUR or hour < END_QUIET_HOUR
    else:
        return START_QUIET_HOUR <= hour < END_QUIET_HOUR

def should_skip_quiet_time():
    global LAST_RUN_TIME
    now = datetime.datetime.now()
    hour = now.hour
    
    if is_quiet_hour(hour):
        if LAST_RUN_TIME is not None:
            elapsed_minutes = (now - LAST_RUN_TIME).total_seconds() / 60
            if elapsed_minutes < QUIET_INTERVAL_MINUTES:
                remaining = int(QUIET_INTERVAL_MINUTES - elapsed_minutes)
                log(f"In quiet hours ({START_QUIET_HOUR}:00 - {END_QUIET_HOUR}:00). Skipping because only {int(elapsed_minutes)} min passed since last run. Next run in approx {remaining} min.")
                return True
        log(f"In quiet hours, but enough time has passed since last run ({QUIET_INTERVAL_MINUTES} min). Executing...")
    
    return False

def load_session_id():
    """Load session ID from persistent file."""
    try:
        if os.path.exists(SESSION_FILE_PATH):
            with open(SESSION_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                session_id = data.get("session_id")
                start_time_iso = data.get("start_time")
                
                # Default to now if start_time is missing (for legacy sessions)
                start_time = None
                if start_time_iso:
                    try:
                        start_time = datetime.datetime.fromisoformat(start_time_iso)
                    except ValueError:
                        pass
                
                if session_id:
                    log(f"Loaded session ID from file: {session_id} (Start Time: {start_time})")
                    return session_id, start_time
    except Exception as e:
        log(f"Error loading session ID from file: {e}")
    return None, None

def save_session_id(session_id, start_time=None):
    """Save session ID to persistent file."""
    try:
        os.makedirs(os.path.dirname(SESSION_FILE_PATH), exist_ok=True)
        if start_time is None:
             start_time = datetime.datetime.now()
        
        with open(SESSION_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                "session_id": session_id, 
                "start_time": start_time.isoformat()
            }, f)
        log(f"Saved session ID to file: {session_id} (Start Time: {start_time.isoformat()})")
    except Exception as e:
        log(f"Error saving session ID to file: {e}")

def clear_session_id():
    """Clear session ID from persistent file."""
    try:
        if os.path.exists(SESSION_FILE_PATH):
            os.remove(SESSION_FILE_PATH)
            log("Cleared session ID file.")
    except Exception as e:
        log(f"Error clearing session ID file: {e}")

def load_context():
    """Load latest context from persistent file."""
    try:
        if os.path.exists(CONTEXT_FILE_PATH):
            with open(CONTEXT_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        log(f"Error loading context from file: {e}")
    return None

def save_context(data):
    """Save latest context to persistent file."""
    try:
        os.makedirs(os.path.dirname(CONTEXT_FILE_PATH), exist_ok=True)
        # Extract relevant fields to keep context concise
        context = {
            "timestamp": datetime.datetime.now().isoformat(),
            "plant_status": data.get("plant_status"),
            "growth_stage": data.get("growth_stage"),
            "last_operation": data.get("operation"),
            "last_comment": data.get("comment")
        }
        with open(CONTEXT_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(context, f, ensure_ascii=False, indent=2)
        log(f"Saved context to file.")
    except Exception as e:
        log(f"Error saving context to file: {e}")

# State (loaded from file on startup)
CURRENT_SESSION_ID = None
CURRENT_SESSION_START = None

def run_job():
    global CURRENT_SESSION_ID, CURRENT_SESSION_START

    if should_skip_quiet_time():
        return

    log("Starting periodic monitoring job...")
    
    max_retries = 1
    for attempt in range(max_retries + 1):
        # 1. Create/Get Session if not exists
        if not CURRENT_SESSION_ID:
            # Try to load from file first
            CURRENT_SESSION_ID, CURRENT_SESSION_START = load_session_id()
        
        # Check session lifetime (Time-based reset)
        if CURRENT_SESSION_ID and CURRENT_SESSION_START:
            now = datetime.datetime.now()
            # If loaded session has no start time (legacy), treat as new or keep it?
            # Let's say if we have a start time, we check elapsed time.
            elapsed = now - CURRENT_SESSION_START
            if elapsed.days >= SESSION_LIFETIME_DAYS:
                 log(f"Session lifetime exceeded ({elapsed.days} days >= {SESSION_LIFETIME_DAYS} days). Starting handover...")
                 
                 # --- Handover Sequence ---
                 try:
                     handover_url = f"{AGENT_API_URL}/run"
                     handover_payload = {
                        "app_name": "agent",
                        "user_id": "default",
                        "session_id": CURRENT_SESSION_ID,
                        "new_message": {
                            "parts": [{"text": HANDOVER_PROMPT}]
                        }
                     }
                     log(f"Sending handover prompt...")
                     h_resp = requests.post(handover_url, json=handover_payload, timeout=AGENT_TIMEOUT)
                     if h_resp.status_code == 200:
                         h_data = h_resp.json()
                         
                         # Parse JSON logic (using similar logic to main loop, simplified here for brevity)
                         # We can reuse a helper or just do quick extract
                         # For now, let's reuse a simplified version or just assume standard flow
                         # To avoid code duplication, we could refactor parsing, but for now let's do a quick best-effort parse
                         h_text = json.dumps(h_data) 
                         # Try to extract text content
                         if isinstance(h_data, list) and len(h_data) > 0:
                             parts = h_data[0].get("content", {}).get("parts", [])
                             if parts:
                                 h_text = parts[0].get("text", h_text)
                         
                         # Parse JSON string
                         clean_h_text = h_text.strip()
                         if clean_h_text.startswith("```json"): clean_h_text = clean_h_text[7:]
                         if clean_h_text.endswith("```"): clean_h_text = clean_h_text[:-3]
                         clean_h_text = clean_h_text.strip()
                         
                         try:
                             h_structured = json.loads(clean_h_text)
                             if isinstance(h_structured, dict):
                                 save_context(h_structured)
                                 log("Handover context saved successfully.")
                         except:
                             log("Failed to parse handover JSON, saving raw text as comment.")
                             save_context({"plant_status": "Handover (Raw)", "comment": h_text})

                 except Exception as he:
                     log(f"Handover failed: {he}")
                 # -------------------------

                 CURRENT_SESSION_ID = None
                 CURRENT_SESSION_START = None
                 clear_session_id()
        
        if not CURRENT_SESSION_ID:
            try:
                # Create session
                session_url = f"{AGENT_API_URL}/apps/agent/users/default/sessions"
                resp = requests.post(session_url, json={})
                if resp.status_code != 200:
                    log(f"Error creating session: {resp.status_code} {resp.text}")
                    return
                    
                session_id = resp.json().get("id")
                
                log(f"Created session: {session_id} (Response: {resp.json()})")
                if not session_id:
                     # Fallback if response structure is different
                     session_id = resp.json().get("name", "").split("/")[-1] # if resource name
    
                if not session_id:
                    log("Could not extract session_id.")
                    return
                
                CURRENT_SESSION_ID = session_id
                CURRENT_SESSION_START = datetime.datetime.now()
                # Save to file for persistence
                save_session_id(CURRENT_SESSION_ID, CURRENT_SESSION_START)
            except Exception as e:
                log(f"Exception during session creation: {e}")
                return
        else:
            log(f"Reusing session: {CURRENT_SESSION_ID}")
    
        # Prepare Prompt with Context (if meaningful)
        message_to_send = PROMPT_MESSAGE
        
        last_context = load_context()
        if last_context:
            context_str = "\n\n**【前回の観測記録 (Context)】**\n"
            context_str += "以下の情報は、前回実行時の記録です。今回の判断の参考にしてください（ただし、現在のセンサー値を優先すること）。\n"
            if last_context.get('timestamp'):
                context_str += f"- 前回実行日時: {last_context.get('timestamp')}\n"
            if last_context.get('plant_status'):
                context_str += f"- 植物の状態: {last_context.get('plant_status')}\n"
            if last_context.get('growth_stage'):
                context_str += f"- 成長段階(GrowthStage): {last_context.get('growth_stage')}\n"
            if last_context.get('last_operation'):
                ops = json.dumps(last_context.get('last_operation'), ensure_ascii=False)
                context_str += f"- 前回操作: {ops}\n"
            
            message_to_send += context_str

        # 2. Run Agent
        try:
            run_url = f"{AGENT_API_URL}/run"
            payload = {
                "app_name": "agent",
                "user_id": "default",
                "session_id": CURRENT_SESSION_ID,
                "new_message": {
                    "parts": [
                        {"text": message_to_send}
                    ]
                }
            }
            
            log(f"Sending prompt to {run_url}...")
            resp = requests.post(run_url, json=payload, timeout=AGENT_TIMEOUT)
            
            if resp.status_code == 200:
                log("Job completed successfully.")
                # Response is a list of Events
                data = resp.json()
                log(f"Agent Response Events: {len(data)}")
    
                # --- Parse Agent Response ---
                structured_data = {}
                try:
                    # Extract the actual agent message.
                    # ADK response structure: { "steps": [ { "content": { "parts": [ { "text": "JSON_STRING" } ] } } ] }
                    # Or simple output if simplified.
                    # We need to parse the JSON string embedded in the response text if using structured output mode.
                    
                    agent_text = ""
                    if isinstance(data, list):
                        for event in data:
                            if "content" in event and event["content"]:
                                if "parts" in event["content"]:
                                    for part in event["content"]["parts"]:
                                        if "text" in part:
                                            agent_text += part["text"]
    
                    if not agent_text:
                        # Fallback
                        agent_text = json.dumps(data)
    
                    # Try to parse agent_text as JSON (since we requested JSON mode)
                    clean_text = agent_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    
                    try:
                        structured_data = None
                        
                        # Robust JSON extraction:
                        # The agent might output "Thinking" text before the JSON.
                        end_idx = clean_text.rfind("}")
                        if end_idx != -1:
                            start_idx = clean_text.find("{")
                            while start_idx != -1 and start_idx < end_idx:
                                candidate = clean_text[start_idx : end_idx + 1]
                                try:
                                    structured_data = json.loads(candidate)
                                    log(f"Successfully parsed JSON starting at index {start_idx}")
                                    break
                                except json.JSONDecodeError:
                                    start_idx = clean_text.find("{", start_idx + 1)
                        
                        if structured_data is None:
                            # Fallback to simple load
                            structured_data = json.loads(clean_text)
    
                    except json.JSONDecodeError:
                        # If not JSON, save as raw text wrapped in dict
                        structured_data = {"raw_output": agent_text}
    
                    # Log the structured response to stdout (ALWAYS)
                    log(f"Agent Response: {json.dumps(structured_data, ensure_ascii=False, indent=2)}")

                    # Save context for next run
                    if isinstance(structured_data, dict) and "plant_status" in structured_data:
                        save_context(structured_data)
    
                except Exception as e:
                    log(f"Error parsing agent response: {e}")
                    structured_data = {"raw_output": str(data)}
    
                # --- Firestore Logging ---
                try:
                    from google.cloud import firestore
                    
                    # Check authentication
                    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ or "GOOGLE_CLOUD_PROJECT" in os.environ:
                        # Initialize DB (assumes project ID from env or default)
                        # For local emulator or if project ID is implicit
                        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
                        if project_id:
                            db = firestore.Client(project=project_id, database="ai-agentic-hackathon-4-db")
                        else:
                            db = firestore.Client(database="ai-agentic-hackathon-4-db")
    
                        # Add metadata
                        log_entry = {
                            "timestamp": datetime.datetime.now(datetime.timezone.utc),
                            "session_id": CURRENT_SESSION_ID,
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
                
                # Success - break the retry loop
                LAST_RUN_TIME = datetime.datetime.now()
                # No need to update session file on every turn since we only track start time
                break
    
            elif resp.status_code == 404 or resp.status_code == 500:
                log(f"Session error ({resp.status_code}). Resetting session ID.")
                CURRENT_SESSION_ID = None
                CURRENT_SESSION_START = None
                clear_session_id()
                
                if attempt < max_retries:
                    log("Retrying immediately with new session...")
                    continue # Try again
                else:
                    log("Max retries reached. Aborting.")
                    break # Exit loop after max retries
            else:
                log(f"Job failed: {resp.status_code} {resp.text}")
                break # Don't retry for non-session errors
    
        except Exception as e:
            log(f"Exception during job execution: {e}")
            break

def main():
    global CURRENT_SESSION_ID, LAST_RUN_TIME
    log(f"Scheduler started. Target: {AGENT_API_URL}, Interval: {INTERVAL_MINUTES} min")
    
    # Load session ID from file on startup
    CURRENT_SESSION_ID, CURRENT_SESSION_START = load_session_id()
    if CURRENT_SESSION_ID:
        log(f"Restored session from previous run: {CURRENT_SESSION_ID} (Start: {CURRENT_SESSION_START})")
    
    # Run once immediately on startup? Or wait?
    # Usually better to wait or run after small delay.
    # Let's run immediately for verification, then schedule.
    run_job() 

    schedule.every(INTERVAL_MINUTES).minutes.do(run_job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # Wait for API to be ready
    log("Waiting for Agent API to be ready...")
    time.sleep(30) 
    main()
