import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import types

# Add the project root to the python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ---------------------------------------------------------
# MOCKING MISSING DEPENDENCIES
# ---------------------------------------------------------

# Mock mcp.types
mcp_types = types.ModuleType("mcp.types")
mcp_types.ImageContent = MagicMock()
mcp_types.TextContent = MagicMock()
sys.modules["mcp.types"] = mcp_types

# Mock mcp.server.fastmcp
mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
MockFastMCP = MagicMock()
# Decorator mock
def tool_decorator(*args, **kwargs):
    def real_decorator(func):
        return func
    # If used as @server.tool (no parens) - unlikely for FastMCP but possible
    if len(args) == 1 and callable(args[0]):
         return args[0]
    return real_decorator
MockFastMCP.return_value.tool.side_effect = tool_decorator
mcp_fastmcp.FastMCP = MockFastMCP
sys.modules["mcp.server.fastmcp"] = mcp_fastmcp

# Mock mcp (parent)
sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()

# Mock httpx
httpx = types.ModuleType("httpx")
httpx.AsyncClient = MagicMock()
sys.modules["httpx"] = httpx

# ---------------------------------------------------------
# IMPORT TARGET MODULE
# ---------------------------------------------------------
from MCP.sensor_image_server import get_meter_data

# ---------------------------------------------------------
# TEST LOGIC
# ---------------------------------------------------------
async def verify_tool():
    print("Verifying MCP tool 'get_meter_data' logic with mocks...")
    
    # Setup mock data from sensor
    mock_sensor_response = {"temperature": 25.5, "humidity": 50}
    
    # Setup httpx mock behavior
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock()
    
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=mock_sensor_response)
    
    mock_client.get.return_value = mock_resp
    
    # Apply the mock to httpx.AsyncClient
    with patch("httpx.AsyncClient", return_value=mock_client):
        # EXECUTE
        result = await get_meter_data(base_url="http://test-node:8000")
        
        # VERIFY
        print(f"Result returned: {result}")
        
        # Check if httpx called correct URL
        mock_client.get.assert_called_with("http://test-node:8000/sensor/meter")
        print("[OK] Called correct URL: http://test-node:8000/sensor/meter")
        
        # Check result content
        # result is a list of TextContent mocks (from our setup above)
        # In our real code: return [TextContent(type="text", text=f"Sensor Data: {payload}")]
        # Since TextContent is a mock, we inspect how it was called
        
        # We need to see if TextContent was instantiated with the right text
        # Since the module is imported, TextContent inside it is mcp.types.TextContent
        
        text_content_mock = sys.modules["mcp.types"].TextContent
        
        # Check call args
        call_args = text_content_mock.call_args
        if call_args:
            kwargs = call_args.kwargs
            text = kwargs.get("text")
            print(f"TextContent content: {text}")
            
            expected_str = f"Sensor Data: {mock_sensor_response}"
            if text == expected_str:
                print("[OK] Tool returned correct data format.")
            else:
                print(f"[FAIL] Expected '{expected_str}', got '{text}'")
        else:
            print("[FAIL] TextContent was not called.")

if __name__ == "__main__":
    asyncio.run(verify_tool())
