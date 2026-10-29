#!/usr/bin/env python3
"""Entry point for the packaged executable and for `python chip8bit.py`."""

import sys

from nescore.cli import main

if __name__ == "__main__":
    sys.exit(main())
