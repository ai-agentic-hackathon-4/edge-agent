import subprocess
import os
import time

def run_adk_with_session(session_id):
    print(f"Running agent with session_id={session_id}...")
    cmd = ["adk", "run", "agent", "--session_id", session_id]
    input_str = "Test message\n/bye\n"
    
    # Needs to run in the correctly activated environment or use full path to adk
    # We assume 'adk' is available in path if running via the venv python
    
    # Use full path to adk if possible for robustness
    # Assuming standard venv layout
    adk_path = os.path.join(os.path.dirname(__file__), "../env/bin/adk")
    if os.path.exists(adk_path):
        cmd[0] = adk_path
        
    env = os.environ.copy()
    
    try:
        process = subprocess.run(
            cmd,
            input=input_str,
            text=True,
            capture_output=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            env=env
        )
        print(f"Return Code: {process.returncode}")
        if process.returncode != 0:
            print(f"Error: {process.stderr}")
            if "AlreadyExistsError" in process.stderr:
                print("Confirmed: Session already exists error.")
            elif "DatabaseSessionService" in process.stderr:
                 print("Database error suspected.")
        else:
            print("Success.")
            
    except Exception as e:
        print(f"Exception: {e}")

def main():
    sid = "verify_persistence_sess"
    print("--- Run 1 ---")
    run_adk_with_session(sid)
    
    time.sleep(2)
    
    print("\n--- Run 2 (Should resume) ---")
    run_adk_with_session(sid)

if __name__ == "__main__":
    main()
