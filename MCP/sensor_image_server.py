import base64
import datetime
import os
import sys
import pathlib
from typing import Optional, Tuple

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

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
        "auto": "auto",
        "low": "101",
        "medium": "102",
        "high": "103"
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

if __name__ == "__main__":
    server.run()
