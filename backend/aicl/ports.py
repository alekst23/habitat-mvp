"""Port registry, typed `Ports` model and `build_ports` (technical.md AppComposition, DR-30; E11-1)."""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

from aicl.clock import Clock, SystemClock
from aicl.settings import Settings

# E11-1 requires only the clock; each owning ticket appends its own port names (E11-2 below).
REQUIRED_PORTS: tuple[str, ...] = ("clock", "secret_store", "credential_broker", "provider_oauth",
                                   "work_executor", "resolver")

# port name -> factory(settings) building the leaf port for the active mode; tickets register theirs.
PORT_REGISTRY: dict[str, Callable[[Settings], object]] = {}


class Ports(BaseModel):
    """Frozen typed model with one field per port name (later tickets add fields)."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    clock: Clock
    secret_store: object  # E11-2
    credential_broker: object  # E11-2
    provider_oauth: object  # E11-2
    work_executor: object  # E11-2
    resolver: object  # E11-2


def build_ports(settings: Settings) -> Ports:
    """Validate exactly REQUIRED_PORTS (an unregistered later-ticket port never fails startup)."""
    built = {}
    for name in REQUIRED_PORTS:
        factory = PORT_REGISTRY.get(name)
        built[name] = factory(settings) if factory is not None else SystemClock()
    return Ports(**built)


def _register_e11_2() -> None:
    from aicl.wiring import PORT_FACTORIES
    PORT_REGISTRY.update(PORT_FACTORIES)


_register_e11_2()
