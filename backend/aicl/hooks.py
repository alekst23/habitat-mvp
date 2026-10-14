"""Ordered startup-hook extension point (E11-1): empty here; E11-2 adds the reconciler."""

from __future__ import annotations

from typing import Callable

# Ordered tuple of `(AppContext) -> None` hooks started by create_app after the routers.
STARTUP_HOOKS: tuple[Callable[..., object], ...] = ()
