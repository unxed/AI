#!/usr/bin/env python3
"""aistudio - offload work to Gemini via the Google AI Studio chat UI (headless real Chrome).
The engine (offload_core.py, cdp.py) also ships, as an identical copy, with grok-offload."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offload_core  # noqa: E402

if __name__ == "__main__":
    offload_core.main()
