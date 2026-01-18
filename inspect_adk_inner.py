
import inspect
import sys
import os
import asyncio
from typing import Any
from unittest.mock import MagicMock
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from google.genai import types as genai_types

async def inspect_tools():
    toolset = None
    try:
        print("Attributes of MCPToolset:")
        for attr in dir(MCPToolset):
            if not attr.startswith('__'):
                print(f"- {attr}")

        server_script = "/app/MCP/sensor_image_server.py" 
        os.environ["DEBUG_MOCK_GCS"] = "true"
        
        toolset = MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="python",
                    args=[server_script],
                    env=os.environ.copy()
                )
            )
        )
        
        print("\nCalling get_tools()...")
        tools = await toolset.get_tools()
        
        mock_context = MagicMock()
        
        for tool in tools:
            if tool.name == "capture_image":
                print("\nFound capture_image tool.")
                
                # Monkeypatching logic simulation
                original_run_async = tool.run_async
                
                async def gcs_aware_run_async(*, args, tool_context):
                    result = await original_run_async(args=args, tool_context=tool_context)
                    # result is dict: {'content': [{'type': 'text', 'text': '...'}], 'isError': False}
                    print(f"Original Result: {result}")
                    
                    if isinstance(result, dict) and 'content' in result:
                        for content in result['content']:
                            if content.get('type') == 'text' and 'gs://' in content.get('text', ''):
                                text = content['text']
                                # Extract URI (simple parsing)
                                import re
                                match = re.search(r'gs://[^\s\.]+', text)
                                if match:
                                    uri = match.group(0)
                                    print(f"Detected GCS URI: {uri}")
                                    # Create Part
                                    # Assuming image/jpeg for now
                                    part = genai_types.Part.from_uri(file_uri=uri, mime_type="image/jpeg")
                                    print(f"Created Part: {part}")
                                    return part
                    return result
                
                # Execute wrapper
                print("Executing wrapped run_async...")
                final_result = await gcs_aware_run_async(args={}, tool_context=mock_context)
                print(f"Final Result type: {type(final_result)}")
                print(f"Final Result: {final_result}")

    finally:
        if toolset and hasattr(toolset, 'close'):
             await toolset.close() if inspect.iscoroutinefunction(toolset.close) else toolset.close()

if __name__ == "__main__":
    asyncio.run(inspect_tools())
