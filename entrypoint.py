#!/usr/bin/env python3
"""
porkill AppImage entrypoint.
Launches the porkill GUI application.
"""
import sys
import os

# Ensure the AppImage's internal lib path is on sys.path
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

from porkill import main

if __name__ == "__main__":
    sys.exit(main())
