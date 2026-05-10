#!/usr/bin/env python3
"""
Entry point for uvx execution of video-to-subtitle-summary-skill MCP server.

This allows running: uvx github.com/ptbsare/video-to-subtitle-summary-skill
"""

import sys
from pathlib import Path

# Add the parent directory to Python path so we can import the skill
skill_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(skill_dir))

def main():
    """Main entry point."""
    import asyncio
    from mcp_server import main as mcp_main
    
    try:
        asyncio.run(mcp_main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()