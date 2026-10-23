#!/usr/bin/env python3
"""Render Cron entry point. Requires PYTHONPATH=backend and requirements-render."""
from render_worker.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main())
