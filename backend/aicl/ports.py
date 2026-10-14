"""Port registry, typed `Ports` model and `build_ports` (technical.md AppComposition, DR-30; E11-1)."""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

from aicl.clock import Clock
from aicl.settings import Settings

# E11-1 requires only the clock; each owning ticket appends its own port names.
REQUIRED_PORTS: tuple[str, ...] = ("clock",)

# port name -> factory(settings) building the leaf port for the active mode; tickets register theirs.
PORT_REGISTRY: dict[str, Callable[[Settings], object]] = {}


class Ports(BaseModel):
    """Frozen typed model with one field per port name (later tickets add fields)."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    clock: Clock


def build_ports(settings: Settings) -> Ports:
    """Validate exactly REQUIRED_PORTS (an unregistered later-ticket port never fails startup)."""
    raise NotImplementedError("build_ports is not implemented (E11-1)")
