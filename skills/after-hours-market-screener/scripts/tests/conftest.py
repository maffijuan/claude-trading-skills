"""Shared path setup for After-Hours Market Screener tests."""

import os
import sys

# scripts/ dir so modules import cleanly under both isolated and bulk runs.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
