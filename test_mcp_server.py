#!/usr/bin/env python3
"""
Test script for the MCP server.
"""

import json
import asyncio
import sys
from pathlib import Path

# Add the skill directory to Python path
skill_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(skill_dir))

from mcp_server import app

async def test_mcp_server():
    """Test the MCP server functionality."""
    
    # Test listing tools
    tools = await app.list_tools()
    print(f"✅ Found {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}")
        print(f"    Parameters: {tool.inputSchema}")
    
    # Test calling the tool with a simple input
    print("\n🧪 Testing tool call...")
    
    # Mock arguments for testing (this won't actually process a video)
    test_arguments = {
        "input": "test.mp4",
        "output_dir": "/tmp/test_output"
    }
    
    try:
        result = await app.call_tool("video_to_subtitle_summary", test_arguments)
        print("✅ Tool call successful!")
        for content in result:
            print(f"  Response: {content.text[:200]}...")
    except Exception as e:
        print(f"❌ Tool call failed (expected for test file): {e}")
    
    print("\n🎉 MCP server test completed!")

if __name__ == "__main__":
    asyncio.run(test_mcp_server())