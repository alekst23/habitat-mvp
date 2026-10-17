"""Ordered startup-hook extension point (E11-1): E11-2 adds the sweeper then the reconciler."""

from __future__ import annotations

from typing import Callable

from aicl.wiring import start_hold_reconciler, start_revocation_sweeper

# Ordered tuple of `(AppContext) -> None` hooks started by create_app after the routers. A failing hook fails
# startup; the revocation sweeper must run before the hold reconciler.
STARTUP_HOOKS: tuple[Callable[..., object], ...] = (start_revocation_sweeper, start_hold_reconciler)
