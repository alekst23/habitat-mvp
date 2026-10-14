"""create_app: the only composition root (technical.md AppComposition, owner E11-1)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from aicl.control.auth import AuthProvider
from aicl.control.csrf import CsrfVerifier
from aicl.db import Database
from aicl.ports import Ports
from aicl.settings import Settings


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    db: Database
    clock: object
    auth_provider: AuthProvider
    csrf_verifier: CsrfVerifier
    ports: Ports


def create_app(settings: Settings, ports: Ports | None = None) -> FastAPI:
    """Run migrations and the price import, build AppContext via build_ports(settings) (`ports` is a
    test-only override), start STARTUP_HOOKS in order and register ROUTE_FACTORIES routers."""
    raise NotImplementedError("create_app is not implemented (E11-1)")
