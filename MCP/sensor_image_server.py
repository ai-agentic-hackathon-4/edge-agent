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
    width: int = 800,
    height: int = 600,
    base_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
):
    """Fetch a JPEG from the sensor API and return it as MCP image content."""
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive")

    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    # Fetch data but don't decode to bytes, keep as base64 string for the model
    # We re-implement _fetch_image logic slightly here or modify it, 
    # but for safety, let's just get the raw base64 from the sensor.
    
    url = f"{base}/image"
    params = {"width": width, "height": height}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    if "data_base64" not in payload:
        raise ValueError("Sensor response missing data_base64")
    
    b64_data = payload["data_base64"]
    fmt = str(payload.get("format", "jpeg")).lower() or "jpeg"
    w = int(payload.get("width", width))
    h = int(payload.get("height", height))
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

if __name__ == "__main__":
    server.run()
