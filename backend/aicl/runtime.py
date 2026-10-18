"""Packaged E11 runtime: real owner authentication, simulated providers, no test routes.

Hosting supplies secrets, SMTP and TLS ingress; packaging/configuration checks do
not provision them. A mounted /data directory must persist outside the container.
"""
from __future__ import annotations

import os

from aicl.app import create_app as compose
from aicl.settings import Settings


def create_app():
    settings = Settings.from_env(os.environ)
    if settings.environment != "production" or settings.test_mode:
        raise RuntimeError("packaged runtime requires production auth with test mode disabled")
    if settings.database_url != "sqlite:////data/habitat.sqlite":
        raise RuntimeError("packaged runtime requires the /data persistent-volume database path")
    app = compose(settings)
    if any(getattr(route, "path", "").startswith("/__test__") for route in app.routes):
        raise RuntimeError("packaged runtime must not expose test routes")
    return app
