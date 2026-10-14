"""Route-factory extension point (E11-1): empty here; each ticket with routes adds one line."""

from __future__ import annotations

from typing import Callable

# Ordered tuple of `(AppContext) -> fastapi.APIRouter`.
ROUTE_FACTORIES: tuple[Callable[..., object], ...] = ()
