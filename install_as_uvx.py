#!/usr/bin/env python3
"""
Install this skill as a uvx package for easy access via uvx github.com/ptbsare/video-to-subtitle-summary-skill

Usage:
  python3 install_as_uvx.py
"""

import os
import subprocess
import sys
from pathlib import Path

def main():
    """Build and install the package for uvx usage."""
    skill_dir = Path(__file__).resolve().parent
    
    print("Building video-to-subtitle-summary-skill for uvx...")
    
    # Build the package
    try:
        subprocess.run([
            sys.executable, "-m", "build", "--wheel"
        ], cwd=skill_dir, check=True)
    except subprocess.CalledProcessError:
        print("Failed to build package. Installing build dependencies...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "build", "setuptools"
        ], check=True)
        subprocess.run([
            sys.executable, "-m", "build", "--wheel"
        ], cwd=skill_dir, check=True)
    
    # Find the built wheel
    dist_dir = skill_dir / "dist"
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        print("Error: No wheel file found in dist/")
        sys.exit(1)
    
    wheel_path = wheels[0]
    print(f"Built wheel: {wheel_path}")
    
    # Install the wheel
    print("Installing package...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", str(wheel_path)
    ], check=True)
    
    print("\n✅ Installation complete!")
    print("\nYou can now run the MCP server using:")
    print("  video-to-subtitle-summary-skill")
    print("\nOr use uvx (if available):")
    print("  uvx video-to-subtitle-summary-skill")

if __name__ == "__main__":
    main()