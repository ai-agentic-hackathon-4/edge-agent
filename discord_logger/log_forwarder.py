import os
import time
import requests
import docker
import threading
import logging
from datetime import datetime

# Configuration
# First try the specific log webhook, then fall back to the generic one
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_LOG_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
LOG_BUFFER_SIZE = 2000  # Characters
LOG_FLUSH_INTERVAL = 2  # Seconds
SENSOR_LOG_FILE = "/app/logs/sensor_logger.log"
HEARTBEAT_INTERVAL = 600  # 10 minutes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not DISCORD_WEBHOOK_URL:
    logger.error("DISCORD_WEBHOOK_URL environment variable is not set.")
    exit(1)

log_buffer = []
buffer_lock = threading.Lock()
# Track containers whose log-following threads have died and need re-attachment
dead_containers = set()
dead_containers_lock = threading.Lock()


def send_to_discord(logs):
    """Send buffered log lines to Discord. Handles chunking and rate limits."""
    if not logs:
        return

    content = "".join(logs)
    # Split into chunks if too long (Discord limit is 2000 chars, code blocks take space)
    # We'll use a safe limit of 1900
    chunks = [content[i:i + 1900] for i in range(0, len(content), 1900)]

    for chunk in chunks:
        payload = {
            "content": f"```\n{chunk}\n```"
        }
        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send logs to Discord: {e}")
            # Check for rate limiting via the response on the exception
            resp = getattr(e, 'response', None)
            if resp is not None and resp.status_code == 429:
                try:
                    retry_after = resp.json().get('retry_after', 5)
                except Exception:
                    retry_after = 5
                logger.warning(f"Rate limited. Waiting {retry_after}s")
                time.sleep(retry_after)


def send_startup_message():
    try:
        payload = {"content": "**Discord Logger Connected**\nMonitoring container logs and `sensor_logger.log`..."}
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        logger.info("Sent startup message to Discord")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")


def flush_logs():
    """Periodically flush buffered log lines to Discord. Never exits."""
    global log_buffer
    while True:
        try:
            time.sleep(LOG_FLUSH_INTERVAL)
            with buffer_lock:
                if log_buffer:
                    logs_to_send = list(log_buffer)
                    log_buffer = []
                else:
                    logs_to_send = []

            if logs_to_send:
                send_to_discord(logs_to_send)
        except Exception as e:
            logger.error(f"Error in flush_logs: {e}")
            # Sleep briefly to avoid tight error loop
            time.sleep(5)


def follow_container_logs(container):
    """Follow logs for a single container. Marks container for re-attachment on exit."""
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
    finally:
        # Signal main loop to re-attach this container
        with dead_containers_lock:
            dead_containers.add(container.id)
        logger.warning(f"Container log thread exited for {container.name} ({container.id}). Will re-attach.")


def tail_file(filepath):
    """
    Tail a log file, handling RotatingFileHandler log rotation.
    Detects rotation by comparing inode numbers.
    Never exits — retries on all errors.
    """
    logger.info(f"Tailing file: {filepath}")

    while True:
        try:
            # Wait for file to exist
            if not os.path.exists(filepath):
                logger.warning(f"File {filepath} does not exist yet. Waiting...")
                while not os.path.exists(filepath):
                    time.sleep(5)
                logger.info(f"File {filepath} found.")

            f = open(filepath, 'r')
            try:
                current_inode = os.fstat(f.fileno()).st_ino
            except OSError:
                f.close()
                time.sleep(1)
                continue

            # Seek to end of file (only read new lines)
            f.seek(0, 2)
            logger.info(f"Opened {filepath} (inode={current_inode}), seeking to end.")

            no_data_count = 0
            while True:
                line = f.readline()
                if not line:
                    no_data_count += 1
                    # Check for rotation every ~5 seconds of inactivity (10 * 0.5s)
                    if no_data_count >= 10:
                        no_data_count = 0
                        try:
                            new_inode = os.stat(filepath).st_ino
                            if new_inode != current_inode:
                                logger.info(
                                    f"Log file rotated (inode {current_inode} -> {new_inode}). "
                                    f"Reopening..."
                                )
                                f.close()
                                break  # Break inner loop to reopen in outer loop
                        except FileNotFoundError:
                            logger.warning(f"File {filepath} disappeared. Waiting for recreation...")
                            f.close()
                            break  # Break inner loop to wait for file in outer loop
                    time.sleep(0.5)
                    continue

                no_data_count = 0
                formatted_line = f"[sensor_logger] {line}"
                with buffer_lock:
                    log_buffer.append(formatted_line)

        except Exception as e:
            logger.error(f"Error tailing file {filepath}: {e}")
            time.sleep(5)


def heartbeat():
    """Send periodic heartbeat to Discord so we know the forwarder is alive."""
    while True:
        try:
            time.sleep(HEARTBEAT_INTERVAL)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = {
                "content": f"💓 `[{now}]` Discord Logger heartbeat — running normally."
            }
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            logger.info("Sent heartbeat to Discord")
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")


def main():
    send_startup_message()

    # Start flusher thread
    flusher = threading.Thread(target=flush_logs, daemon=True)
    flusher.start()

    # Start file tailer thread
    file_tailer = threading.Thread(target=tail_file, args=(SENSOR_LOG_FILE,), daemon=True)
    file_tailer.start()

    # Start heartbeat thread
    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    # Docker client
    try:
        client = docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker daemon: {e}")
        return

    # Monitor containers — continuously attach to running containers.
    # Re-attach to containers whose log threads have died.
    attached_containers = set()

    while True:
        try:
            # Remove dead containers so they can be re-attached
            with dead_containers_lock:
                if dead_containers:
                    removed = dead_containers & attached_containers
                    attached_containers -= dead_containers
                    dead_containers.clear()
                    if removed:
                        logger.info(f"Cleared {len(removed)} dead container(s) for re-attachment.")

            containers = client.containers.list()
            for c in containers:
                if c.id not in attached_containers and "discord-logger" not in c.name:
                    t = threading.Thread(target=follow_container_logs, args=(c,), daemon=True)
                    t.start()
                    attached_containers.add(c.id)
                    logger.info(f"Attached to container: {c.name} ({c.id[:12]})")
        except Exception as e:
            logger.error(f"Error listing containers: {e}")

        time.sleep(10)


if __name__ == "__main__":
    main()
