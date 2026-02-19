import base64
import datetime
import os
import sys
import pathlib
from typing import Optional, Tuple

import httpx
import asyncio
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from google.cloud import firestore
from google.cloud import storage

# Default sensor API base. Override per call (base_url param) or via SENSOR_API_BASE.
DEFAULT_BASE_URL = os.getenv("SENSOR_API_BASE", "http://192.168.11.226:8000").rstrip("/")

server = FastMCP("sensor-image-server")


async def _fetch_image(
    base_url: str, width: int, height: int, timeout_seconds: float
) -> Tuple[bytes, str, int, int]:
    url = f"{base_url}/image"
    params = {"width": width, "height": height}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    if "data_base64" not in payload:
        raise ValueError("Sensor response missing data_base64")

    try:
        image_bytes = base64.b64decode(payload["data_base64"])
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Failed to decode base64 image data") from exc

    fmt = str(payload.get("format", "jpeg")).lower() or "jpeg"
    w = int(payload.get("width", width))
    h = int(payload.get("height", height))
    return image_bytes, fmt, w, h


@server.tool()
async def capture_image(
    base_url: Optional[str] = None,
    timeout_seconds: float = 30.0,
):
    """Fetch a full-size JPEG from the sensor API and return it as MCP image content."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    
    url = f"{base}/image"
    # No params = native resolution (full size)
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()

    if "data_base64" not in payload:
        raise ValueError("Sensor response missing data_base64")
    
    b64_data = payload["data_base64"]
    fmt = str(payload.get("format", "jpeg")).lower() or "jpeg"
    w = payload.get("width")
    h = payload.get("height")
    mime = f"image/{fmt}"


    # Upload to GCS
    try:
        # Debug mock
        if os.environ.get("DEBUG_MOCK_GCS"):
            gcs_uri = "gs://mock-bucket/mock-image.jpg"
            sys.stderr.write(f"DEBUG: Mocked upload to {gcs_uri}\n")
        else:
            from MCP.uploader import GCSUploader
            uploader = GCSUploader()
            image_bytes = base64.b64decode(b64_data)
            gcs_uri = uploader.upload_bytes(image_bytes, content_type=mime, folder="agent-captures")
            sys.stderr.write(f"Uploaded image to {gcs_uri}\n")
        
    except Exception as e:
        sys.stderr.write(f"Error uploading to GCS: {e}\n")
        # Fallback to returning base64 if GCS fails? 
        # Fallback to returning base64 if GCS fails? 
        # Or better, return error message so user knows GCS failed.
        # For now, let's append error but still return base64 as fallback or just fail.
        # User requested REPLACING base64 with GCS URL. So we should probably fail if GCS fails.
        raise RuntimeError(f"Failed to upload image to GCS: {e}")

    # Return as TextContent with GCS URI
    # Agent can handle gs:// URIs natively if configured, or just knows it's a file path.
    return [
        TextContent(
            type="text",
            text=f"Image captured and uploaded to {gcs_uri}. Metadata: width={w}, height={h}."
        )
    ]



@server.tool()
async def get_meter_data(
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch temperature and humidity from the sensor API."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/sensor/meter"
    
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        
    # Return as TextContent
    return [
        TextContent(
            type="text",
            text=f"Sensor Data: {payload}"
        )
    ]


@server.tool()
async def get_soil_moisture(
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch soil moisture data from the sensor API."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/sensor/soil"
    
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        
    return [
        TextContent(
            type="text",
            text=f"Soil Moisture: {payload}"
        )
    ]

@server.tool()
async def get_bh1750_data(
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch lux data from the BH1750 sensor."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/sensor/bh1750"
    
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        
    return [
        TextContent(
            type="text",
            text=f"Lux Sensor Data: {payload}"
        )
    ]

@server.tool()
async def get_air_conditioner_status(
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch the current status of the Air Conditioner (e.g. power, temp, mode)."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/sensor/air-conditioner"
    
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error fetching AC status: {e}")]
        
    return [
        TextContent(
            type="text",
            text=f"Air Conditioner Status: {payload}"
        )
    ]

@server.tool()
async def get_humidifier_status(
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch the current status of the Humidifier (e.g. power, mode, humidity)."""
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/sensor/humidifier"
    
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error fetching Humidifier status: {e}")]
        
    return [
        TextContent(
            type="text",
            text=f"Humidifier Status: {payload}"
        )
    ]

@server.tool()
async def control_air_conditioner(
    temperature: int,
    mode: str,
    fan_speed: str,
    is_on: bool,
    base_url: Optional[str] = None,
    timeout_seconds: float = 10.0,
):
    """
    Control the Air Conditioner (Infrared Remote).
    Args:
        temperature (int): Target temperature (e.g., 25).
        mode (str): One of "auto", "cool", "dry", "fan", "heat".
        fan_speed (str): One of "auto", "low", "medium", "high".
        is_on (bool): Power state.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/control/air-conditioner/settings"
    
    # Map strings to expected Enum values if needed. 
    # API schema expects int for Enum but Pydantic can often handle strings if they match name.
    # However, our sensor-node Enums are IntEnum.
    # Let's map string input to IntEnum values manually to be safe or update schema.
    # The sensor-node `ACSettings` uses:
    # ACMode(IntEnum): AUTO=1...
    # Input `mode` string needs to be mapped.
    
    # Simple mapping
    ac_modes = {"auto": 1, "cool": 2, "dry": 3, "fan": 4, "heat": 5}
    fan_speeds = {"auto": 1, "low": 2, "medium": 3, "high": 4}

    mode_val = ac_modes.get(mode.lower())
    if not mode_val:
        return [TextContent(type="text", text=f"Error: Invalid AC mode '{mode}'. Available: {list(ac_modes.keys())}")]
    
    fan_val = fan_speeds.get(fan_speed.lower())
    if not fan_val:
        return [TextContent(type="text", text=f"Error: Invalid Fan Speed '{fan_speed}'. Available: {list(fan_speeds.keys())}")]

    payload = {
        "temperature": temperature,
        "mode": mode_val,
        "fan_speed": fan_val,
        "is_on": is_on
    }

    print(f"DEBUG: Sending AC POST to {url} with payload {payload}", file=sys.stderr)

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload)
            print(f"DEBUG: AC Response Status: {resp.status_code}", file=sys.stderr)
            resp.raise_for_status()
            data = resp.json() 
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error controlling AC: {e}. URL: {url}")]
            
    return [
        TextContent(
            type="text",
            text=f"Air Conditioner control command sent. Settings: {payload}. Response: {data}"
        )
    ]

@server.tool()
async def control_humidifier(
    mode: str,
    is_on: bool,
    base_url: Optional[str] = None,
    timeout_seconds: float = 10.0,
):
    """
    Control the Humidifier.
    Args:
        mode (str): One of "auto", "low", "medium", "high".
        is_on (bool): Power state.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/control/humidifier/settings"
    
    # Map string mode to Hub 2 expected values?
    # Sensor-node `HumidifierMode` expects "auto", "101"(low), "102"(medium), "103"(high)
    
    h_modes = {
        "auto": "7",
        "high": "1",
        "medium": "2",
        "low": "3",
        "quiet": "4"
    }
    
    mode_val = h_modes.get(mode.lower())
    if not mode_val:
         return [TextContent(type="text", text=f"Error: Invalid Humidifier mode '{mode}'. Available: {list(h_modes.keys())}")]

    payload = {
        "mode": mode_val,
        "is_on": is_on
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error controlling Humidifier: {e}")]

    return [
        TextContent(
            type="text",
            text=f"Humidifier control command sent. Settings: {payload} (Mapped Mode: {mode_val}). Response: {data}"
        )
    ]


@server.tool()
async def control_pump(
    volume_ml: float = 50.0,
    base_url: Optional[str] = None,
    timeout_seconds: float = 10.0,
):
    """
    Control the Water Pump to water the plant.
    Args:
        volume_ml (float): Amount of water in milliliters. Default 50ml.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/control/pump"
    
    payload = {
        "volume_ml": volume_ml
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error controlling Pump: {e}")]
    
    return [
        TextContent(
            type="text",
            text=f"Pump control command sent. Volume: {volume_ml}ml. Response: {data}"
        )
    ]


@server.tool()
async def control_plug_mini(
    is_on: bool,
    base_url: Optional[str] = None,
    timeout_seconds: float = 10.0,
):
    """
    Control the Plug Mini to toggle the grow light on/off.
    Use this to supplement light when BH1750 lux is low during the day.
    Args:
        is_on (bool): Power state.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/control/plug-mini/settings"

    payload = {"is_on": is_on}

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error controlling Plug Mini: {e}")]

    return [
        TextContent(
            type="text",
            text=f"Plug Mini control command sent. is_on={is_on}. Response: {data}"
        )
    ]



# ----------------------------------------------------------------------
# Helper functions for Discord Notification (Character Info)
# ----------------------------------------------------------------------

def _get_character_info_sync():
    """
    Fetches character info (name, image_url) from Firestore.
    Path: /prod_growing_diaries/Character
    Database: ai-agentic-hackathon-4-db
    """
    try:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        # Initialize Firestore with specific database
        db = firestore.Client(project=project_id, database="ai-agentic-hackathon-4-db")
        
        doc_ref = db.collection("prod_growing_diaries").document("Character")
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            # Try common field names
            name = data.get("name") or data.get("character_name")
            image_url = data.get("image_url") or data.get("icon_url") or data.get("public_url") or data.get("image_uri")
            return name, image_url
            
    except Exception as e:
        sys.stderr.write(f"Error fetching character info from Firestore: {e}\n")
    
    return None, None

def _sign_gcs_url_sync(gcs_uri):
    """
    Generates a signed URL for a GCS URI (valid for 1 hour).
    Discord needs a publicly accessible URL.
    """
    if not gcs_uri:
        return None
        
    # Handle https://storage.googleapis.com/bucket/blob format
    if gcs_uri.startswith("https://storage.googleapis.com/"):
        nopre = gcs_uri.replace("https://storage.googleapis.com/", "")
    elif gcs_uri.startswith("gs://"):
        nopre = gcs_uri.replace("gs://", "")
    else:
        # Assume it's already a public URL or we can't sign it
        return gcs_uri

    try:
        client = storage.Client()
        # Parse bucket/blob_name
        if "/" not in nopre:
            return None
            
        bucket_name, blob_name = nopre.split("/", 1)
        
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET"
        )
        return url
    except Exception as e:
        sys.stderr.write(f"Error signing GCS URL: {e}\n")
        return None


@server.tool()
async def send_discord_notification(
    message: str,
    webhook_url: Optional[str] = None,
    timeout_seconds: float = 10.0,
):
    """
    Send a notification message to Discord.
    Use this when the plant's condition is URGENT (e.g. dying, severe disease).
    Args:
        message (str): The message content to send.
    """
    # use DISCORD_WEBHOOK_URL from env or provided argument
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    
    if not url:
         return [TextContent(type="text", text="Error: No Discord Webhook URL configured.")]

    # Fetch character info from Firestore to customize the notification
    # We use firestore/storage sync clients, so run in thread to avoid blocking async loop
    char_name, char_image_uri = await asyncio.to_thread(_get_character_info_sync)
    
    avatar_url = None
    if char_image_uri:
        avatar_url = await asyncio.to_thread(_sign_gcs_url_sync, char_image_uri)

    payload = {
        "content": message
    }
    
    # Add custom username and avatar if available
    if char_name:
        payload["username"] = char_name
    if avatar_url:
        payload["avatar_url"] = avatar_url

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Error sending Discord notification: {e}")]

    return [
        TextContent(
            type="text",
            text=f"Discord notification sent successfully."
        )
    ]

@server.tool()
async def calculate_vpd(
    temp: float,
    hum: float,
):
    """
    気温(T)と湿度(RH)からVPD(飽差)を計算する関数
    :param temp: 気温 (摂氏)
    :param hum: 相対湿度 (%)
    """
    
    # 1. 飽和水蒸気圧 (SVP) を計算 (Tetensの式)
    # 温度Tの空気が限界まで持てる水分量 (hPa)
    svp = 6.1078 * 10 ** ((7.5 * temp) / (temp + 237.3))
    
    # 2. 実際の水蒸気圧 (VP) を計算
    # 今の空気中に実際にある水分量 (hPa)
    vp = svp * (hum / 100.0)
    
    # 3. 飽差 (VPD) = 飽和 - 実測 (hPa -> kPaに変換するために10で割る)
    vpd = (svp - vp) / 10.0
    
    # 判定ロジック（ラディッシュ・葉物野菜向け）
    # 理想ゾーン: 0.8 〜 1.2 kPa
    if vpd < 0.8:
        status = "多湿 (Wet) -> 除湿/送風が必要"
    elif vpd > 1.2:
        status = "乾燥 (Dry) -> 加湿が必要"
    else:
        status = "適正 (Good) -> 維持"

    return [
        TextContent(
            type="text",
            text=f"VPD: {vpd:.2f} kPa, 判定: {status}"
        )
    ]

@server.tool()
async def get_current_time():
    """
    Get the current time in Japan Standard Time (JST).
    Returns the ISO 8601 formatted string of the current JST time.
    """
    import pytz
    from datetime import datetime
    
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    
    return [
        TextContent(
            type="text",
            text=f"Current JST Time: {now.isoformat()}"
        )
    ]


@server.tool()
async def get_days_since_sowing():
    """
    Get the number of days since sowing (種まきからの日数).
    Reads the sowing_date from the Firestore configurations/edge_agent document
    and calculates the elapsed days from that date to today (JST).
    Returns the number of days and the sowing date.
    """
    import pytz
    from datetime import datetime as dt

    try:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        db = firestore.Client(project=project_id, database="ai-agentic-hackathon-4-db")

        doc_ref = db.collection("configurations").document("edge_agent")
        doc = doc_ref.get()

        if not doc.exists:
            return [
                TextContent(
                    type="text",
                    text="Error: configurations/edge_agent document not found in Firestore."
                )
            ]

        data = doc.to_dict()
        sowing_date_raw = data.get("sowing_date")

        if sowing_date_raw is None:
            return [
                TextContent(
                    type="text",
                    text="Error: sowing_date field is not set in configurations/edge_agent. "
                         "Please set it in Firestore (e.g. '2026-02-01')."
                )
            ]

        jst = pytz.timezone("Asia/Tokyo")

        # Handle Firestore Timestamp, datetime, or string
        if hasattr(sowing_date_raw, "date"):
            # datetime or Timestamp object
            sowing_date = sowing_date_raw.astimezone(jst).date()
        elif isinstance(sowing_date_raw, str):
            # ISO 8601 string (e.g. "2026-02-01")
            sowing_date = dt.strptime(sowing_date_raw, "%Y-%m-%d").date()
        else:
            return [
                TextContent(
                    type="text",
                    text=f"Error: sowing_date has unexpected type: {type(sowing_date_raw)}"
                )
            ]

        today = dt.now(jst).date()
        days_elapsed = (today - sowing_date).days

        return [
            TextContent(
                type="text",
                text=f"種まき日: {sowing_date.isoformat()}, 経過日数: {days_elapsed}日目"
            )
        ]

    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Error calculating days since sowing: {e}"
            )
        ]


if __name__ == "__main__":
    server.run()
