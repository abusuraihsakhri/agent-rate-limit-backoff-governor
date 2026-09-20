#!/usr/bin/env python3
"""Compatibility wrapper for the package CLI."""
import sys
from ratelimit_governor.cli import main

if __name__ == "__main__":
    sys.exit(main())
