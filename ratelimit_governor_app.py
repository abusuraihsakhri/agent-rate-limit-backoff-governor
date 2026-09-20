#!/usr/bin/env python3
"""Compatibility entry point for existing invocations."""
import sys
from ratelimit_governor.cli import main

if __name__ == "__main__":
    sys.exit(main())
