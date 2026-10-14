"""Vercel FastAPI entrypoint for the ArbitMint read-only market API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arbitmint.app import app

__all__ = ["app"]
