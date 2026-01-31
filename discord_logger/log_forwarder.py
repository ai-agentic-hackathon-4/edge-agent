import os
import time
import requests
import docker
import threading
import logging
from datetime import datetime

# Configuration
# First try the specific log webhook, then fall back to the generic one (though usually we want to separate them)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
LOG_BUFFER_SIZE = 2000  # Characters
LOG_FLUSH_INTERVAL = 2  # Seconds
SENSOR_LOG_FILE = "/app/logs/sensor_logger.log"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not DISCORD_WEBHOOK_URL:
    logger.error("DISCORD_WEBHOOK_URL environment variable is not set.")
    exit(1)

log_buffer = []
buffer_lock = threading.Lock()

def send_to_discord(logs):
    if not logs:
        return
    
    content = "".join(logs)
    # Split into chunks if too long (Discord limit is 2000 chars, but code blocks take space)
    # We'll use a safe limit of 1900
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
    
    for chunk in chunks:
        payload = {
            "content": f"```\n{chunk}\n```"
        }
        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logger.info("Sent logs to Discord")
        except Exception as e:
            logger.error(f"Failed to send logs to Discord: {e}")
            # If rate limited, maybe sleep? For now just log error.
            if hasattr(response, 'status_code') and response.status_code == 429:
                 retry_after = response.json().get('retry_after', 1)
                 logger.warning(f"Rate limited. Waiting {retry_after}s")
                 time.sleep(retry_after)

def send_startup_message():
    try:
        payload = {"content": "**Discord Logger Connected**\nMonitoring container logs and `sensor_logger.log`..."}
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
        logger.info("Sent startup message to Discord")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")

def flush_logs():
    global log_buffer
    while True:
        time.sleep(LOG_FLUSH_INTERVAL)
        with buffer_lock:
            if log_buffer:
                logs_to_send = list(log_buffer)
                log_buffer = []
            else:
                logs_to_send = []
        
        if logs_to_send:
            send_to_discord(logs_to_send)

def follow_container_logs(container):
    try:
        logger.info(f"Following logs for container: {container.name}")
        for line in container.logs(stream=True, follow=True, tail=0):
            try:
                decoded_line = line.decode('utf-8')
            except UnicodeDecodeError:
                decoded_line = str(line)
                
            formatted_line = f"[{container.name}] {decoded_line}"
            with buffer_lock:
                log_buffer.append(formatted_line)
    except Exception as e:
        logger.error(f"Error following container {container.name}: {e}")

def tail_file(filepath):
    logger.info(f"Tailing file: {filepath}")
    # Simple tail -f implementation
    try:
        if not os.path.exists(filepath):
            logger.warning(f"File {filepath} does not exist yet. Waiting...")
            while not os.path.exists(filepath):
                time.sleep(5)
            logger.info(f"File {filepath} found.")

        f = open(filepath, 'r')
        # Go to the end of file
        f.seek(0, 2)
        
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            
            formatted_line = f"[sensor_logger] {line}"
            with buffer_lock:
                log_buffer.append(formatted_line)
    except Exception as e:
        logger.error(f"Error tailing file {filepath}: {e}")

def main():
    send_startup_message()

    # Start flusher thread
    flusher = threading.Thread(target=flush_logs, daemon=True)
    flusher.start()

    # Start file tailer thread
    file_tailer = threading.Thread(target=tail_file, args=(SENSOR_LOG_FILE,), daemon=True)
    file_tailer.start()

    # Docker client
    try:
        client = docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker daemon: {e}")
        return

    # Monitor containers
    # We want to monitor all containers in this compose project, but exclude ourselves
    # For now, let's just monitor all running containers or specific ones
    # A robust way is to listen for events, but for simplicity, let's just attach to existing ones
    # and maybe poll for new ones or just assume fixed set for now.
    # Given the user request "Docker-composeのログ...すべてのログ", let's try to attach to all.
    
    attached_containers = set()
    
    while True:
        try:
            containers = client.containers.list()
            for c in containers:
                if c.id not in attached_containers and "discord-logger" not in c.name:
                    # Avoid logging our own logs to infinite loop if we used stdout
                    # But we are using a separate sender. Still safer to skip self if possible
                    # or at least be careful.
                    # We identified self by name "discord-logger" (assuming we name it so in compose)
                    
                    t = threading.Thread(target=follow_container_logs, args=(c,), daemon=True)
                    t.start()
                    attached_containers.add(c.id)
        except Exception as e:
            logger.error(f"Error listing containers: {e}")
        
        time.sleep(10)

if __name__ == "__main__":
    main()
