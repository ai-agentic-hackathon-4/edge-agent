import time
import subprocess
import os
import sys

# Script to run the agent periodically (every 1 hour)
# It invokes 'adk run agent' and pipes a command to it.

def run_agent_check():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting periodic agent check...")
    
    # Message to trigger the agent
    # We want to force it to a single turn check
    user_input = "現在の植物の状態を確認してください。"
    
    # Construct the command
    # We assume 'adk' is in the path or we use python -m google.adk
    # We are inside the edge-agent directory, run.sh sets up env.
    # We should reuse the environment or activation.
    
    # We'll use the virtualenv python to run adk module if possible, or just the adk command if accessible.
    # From run.sh: adk run agent
    
    cmd = ["adk", "run", "agent", "--session_id", "periodic_monitor_session"]
    
    # We need to feed input.
    # 'adk run agent' starts an interactive session.
    # We need to send the input, maybe wait for output, and then exit.
    # Since 'adk run agent' might not exit automatically after one turn, sending EOF or "exit" might be needed.
    
    try:
        # Popen allows us to write to stdin
        # We also want to capture stdout/stderr
        # We need to ensure we activate the right environment variables (load from .env)
        
        env = os.environ.copy()
        # Add necessary vars from .env if not present (assuming this script is run from a place that might not have them)
        # But usually we run this with `edge-agent/env/bin/python` which doesn't auto-load .env
        pass 
        
        # Simple interaction: Send message + newline + "exit" + newline
        input_str = f"{user_input}\n/bye\n" # /bye or exit often quits ADK CLI methods
        
        # If /bye doesn't work, we might just timeout.
        
        process = subprocess.run(
            cmd,
            input=input_str,
            text=True,
            capture_output=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."), # Run from edge-agent dir
            env=env
        )
        
        print("Agent Output:")
        print(process.stdout)
        
        if process.returncode != 0:
            print("Agent Error Output:")
            print(process.stderr)
            
    except Exception as e:
        print(f"Error running agent: {e}")

def main():
    while True:
        run_agent_check()
        print("Sleeping for 1 hour...")
        time.sleep(3600)

if __name__ == "__main__":
    main()
