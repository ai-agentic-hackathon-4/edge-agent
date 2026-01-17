import base64
import os
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

    # Return as TextContent so the model sees the base64 string directly
    # and can process it according to the system instructions.
    return [
        TextContent(
            type="text",
            text=f"Image captured. Metadata: width={w}, height={h}, mime={mime}.\nBase64 Data: {b64_data}"
        )
    ]


if __name__ == "__main__":
    server.run()
