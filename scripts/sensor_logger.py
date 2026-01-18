import os
import sys
import base64
import time
import httpx
import logging
from google.cloud import firestore
from datetime import datetime
import pytz
from dotenv import load_dotenv

# Add parent directory to path to import MCP modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env from agent/.env
agent_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
env_path = os.path.join(agent_dir, ".env")
load_dotenv(env_path)

# Fix GOOGLE_APPLICATION_CREDENTIALS path if it points to container path
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if cred_path and not os.path.exists(cred_path):
    # Try to find it in the agent directory
    filename = os.path.basename(cred_path)
    local_path = os.path.join(agent_dir, filename)
    if os.path.exists(local_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_path
        logging.info(f"Updated credential path to local file: {local_path}")
    else:
        logging.warning(f"Credential file not found at {cred_path} or {local_path}")
try:
    from MCP.uploader import GCSUploader
except ImportError:
    # Fallback or error if not found. 
    # Since we are in scripts/, parent is edge-agent/, which contains MCP/.
    pass

# Configuration
SENSOR_API_BASE = os.getenv("SENSOR_API_BASE", "http://192.168.11.226:8000").rstrip("/")
FIRESTORE_COLLECTION = "sensor_logs"
INTERVAL_SECONDS = 60
IMAGE_INTERVAL_MINUTES = 30

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_sensor_data(client: httpx.Client, endpoint: str) -> dict:
    try:
        url = f"{SENSOR_API_BASE}{endpoint}"
        response = client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch {endpoint}: {e}")
        return {}

def fetch_and_upload_image(client: httpx.Client, uploader: GCSUploader) -> str:
    try:
        # High resolution fetch
        url = f"{SENSOR_API_BASE}/image"
        params = {"width": 1920, "height": 1080}
        logger.info(f"Capturing high-res image from {url}...")
        
        # Increase timeout for image capture/download
        response = client.get(url, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        
        if "data_base64" in data:
            image_bytes = base64.b64decode(data["data_base64"])
            # Upload
            uri = uploader.upload_bytes(image_bytes, content_type="image/jpeg", folder="logger-captures")
            logger.info(f"Uploaded image to {uri}")
            return uri
    except Exception as e:
        logger.error(f"Failed to capture/upload image: {e}")
    return None

def main():
    logger.info("Starting Sensor Logger...")
    
    # Initialize Firestore
    try:
        db = firestore.Client(database="ai-agentic-hackathon-4-db")
        logger.info(f"Connected to Firestore project: {db.project}, database: ai-agentic-hackathon-4-db")
    except Exception as e:
        logger.critical(f"Failed to connect to Firestore: {e}")
        return

    # Initialize GCS Uploader
    try:
        uploader = GCSUploader()
        logger.info(f"Initialized GCS Uploader for bucket: {uploader.bucket_name}")
    except Exception as e:
        logger.error(f"Failed to initialize GCS Uploader: {e}. Image capture will be disabled.")
        uploader = None

    last_image_time = 0
    
    while True:
        try:
            current_time = time.time()
            with httpx.Client() as client:
                # Fetch data
                meter_data = fetch_sensor_data(client, "/sensor/meter")
                soil_data = fetch_sensor_data(client, "/sensor/soil")
                
                # Prepare document
                now = datetime.now(pytz.timezone('Asia/Tokyo'))
                
                doc_data = {
                    "timestamp": now,
                    "unix_timestamp": now.timestamp(),
                    "date": now.strftime("%Y-%m-%d"),
                    "temperature": meter_data.get("temperature"),
                    "humidity": meter_data.get("humidity"),
                    "soil_moisture": soil_data.get("moisture_percent"),
                    "soil_raw": soil_data.get("raw_value"),
                    "raw_data": {
                        "meter": meter_data,
                        "soil": soil_data
                    }
                }

                # Check if we need to capture image (every 30 mins)
                # First run (last_image_time==0) or elapsed time > interval
                if uploader and (current_time - last_image_time >= IMAGE_INTERVAL_MINUTES * 60):
                    image_uri = fetch_and_upload_image(client, uploader)
                    if image_uri:
                        doc_data["image_uri"] = image_uri
                        last_image_time = current_time
                
                # Write to Firestore
                db.collection(FIRESTORE_COLLECTION).add(doc_data)
                
                log_msg = f"Logged data: Temp={doc_data.get('temperature')}, Hum={doc_data.get('humidity')}, Soil={doc_data.get('soil_moisture')}%"
                if "image_uri" in doc_data:
                    log_msg += f", Image={doc_data['image_uri']}"
                logger.info(log_msg)

        except Exception as e:
            logger.error(f"Error in main loop: {e}")

        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
