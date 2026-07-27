#!/usr/bin/env python3
"""
Roblox Asset Uploader - ASSET_CORE Terminal TUI Launcher
Redirects legacy GUI invocations to the new Textual TUI interface.
"""

import sys
from tui import main as launch_tui

if __name__ == "__main__":
    print("[INFO] Launching ASSET_CORE Terminal TUI...")
    launch_tui()