"""Port registry, typed `Ports` model and `build_ports` (technical.md AppComposition, DR-30; E11-1)."""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

from aicl.clock import Clock, SystemClock
from aicl.settings import Settings
from aicl.web.proof import CompositionIncomplete

# E11-1 requires only the clock; each owning ticket appends its own port names (E11-2 below).
REQUIRED_PORTS: tuple[str, ...] = ("clock", "secret_store", "credential_broker", "provider_oauth",
                                   "work_executor", "resolver", "magic_link_sender", "chat_model")

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
    magic_link_sender: object  # E11-3
    chat_model: object  # E11-4


def build_ports(settings: Settings) -> Ports:
    """Build exactly REQUIRED_PORTS. `clock` defaults to SystemClock; any other required port without a registered
    factory fails startup as `composition incomplete: <port>` (E11-5, F-1)."""
    built = {}
    for name in REQUIRED_PORTS:
        factory = PORT_REGISTRY.get(name)
        if factory is not None:
            built[name] = factory(settings)
        elif name == "clock":
            built[name] = SystemClock()
        else:
            raise CompositionIncomplete(f"composition incomplete: {name}")
    return Ports(**built)


def _register_wiring() -> None:
    from aicl.wiring import PORT_FACTORIES
    PORT_REGISTRY.update(PORT_FACTORIES)


_register_wiring()
