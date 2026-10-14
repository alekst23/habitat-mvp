"""PriceTable (technical.md "PriceTable", owner E11-1). Integer micro-USD, ceiling arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection

METERS: tuple[str, ...] = ("inference.input_tokens", "inference.output_tokens", "compute.minutes")


@dataclass(frozen=True)
class Rate:
    meter: str
    unit_size: int
    micro_usd: int


@dataclass(frozen=True)
class PriceTableVersion:
    version: str
    effective_from: datetime
    rates: tuple[Rate, ...]
    sha256: str


def parse_price_table(raw: bytes) -> PriceTableVersion:
    """Validate schema (version pattern, three meters exactly once, positive unit_size, no floats).

    Invalid input raises AiclError('validation_failed'). Stub.
    """
    raise NotImplementedError("parse_price_table is not implemented (E11-1)")


def import_price_table(conn: Connection, path: Path) -> PriceTableVersion:
    """Insert-only import; same version with a different hash is a startup failure. Stub."""
    raise NotImplementedError("import_price_table is not implemented (E11-1)")


def effective_version(conn: Connection, now: datetime) -> PriceTableVersion | None:
    """Greatest effective_from not later than `now`, or None (use-time `price_unavailable`). Stub."""
    raise NotImplementedError("effective_version is not implemented (E11-1)")


def cost_micro_usd(version: PriceTableVersion, meter: str, units: int) -> int:
    """ceil(units * micro_usd / unit_size); a missing meter raises AiclError('unavailable'). Stub."""
    raise NotImplementedError("cost_micro_usd is not implemented (E11-1)")
