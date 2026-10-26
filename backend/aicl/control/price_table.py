"""PriceTable (technical.md "PriceTable", owner E11-1). Integer micro-USD, ceiling arithmetic."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection

from aicl.control.errors import AiclError

METERS: tuple[str, ...] = ("inference.input_tokens", "inference.output_tokens", "compute.minutes")
OPTIONAL_METERS: tuple[str, ...] = ("inference.web_search_calls",)
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


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


def _invalid(message: str) -> AiclError:
    return AiclError("validation_failed", f"price table: {message}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_price_table(raw: bytes) -> PriceTableVersion:
    """Validate three required meters and optional priced tools, with no duplicates or floats.

    Invalid input raises AiclError('validation_failed')."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise _invalid("not valid JSON") from None
    if not isinstance(data, dict):
        raise _invalid("must be an object")
    version, stamp, rates_raw = data.get("version"), data.get("effective_from"), data.get("rates")
    if not isinstance(version, str) or not _VERSION.match(version):
        raise _invalid("invalid version")
    if not isinstance(stamp, str) or not _STAMP.match(stamp):
        raise _invalid("effective_from must be a UTC timestamp")
    try:
        effective_from = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise _invalid("effective_from is not a date") from None
    if not isinstance(rates_raw, list):
        raise _invalid("rates must be a list")
    rates: dict[str, Rate] = {}
    for item in rates_raw:
        if not isinstance(item, dict):
            raise _invalid("rate must be an object")
        meter, unit, price = item.get("meter"), item.get("unit_size"), item.get("micro_usd")
        if meter not in METERS + OPTIONAL_METERS or meter in rates:
            raise _invalid("unknown or duplicate meter")
        if not _is_int(unit) or unit <= 0 or not _is_int(price) or price < 0:
            raise _invalid("unit_size must be a positive integer and micro_usd a nonnegative integer")
        rates[meter] = Rate(meter, unit, price)
    if not set(METERS).issubset(rates):
        raise _invalid("every required meter must appear exactly once")
    ordered = tuple(rates[m] for m in sorted(rates))
    canonical = json.dumps({"version": version, "effective_from": stamp,
                            "rates": [{"meter": r.meter, "unit_size": r.unit_size, "micro_usd": r.micro_usd}
                                      for r in ordered]}, sort_keys=True, separators=(",", ":"))
    return PriceTableVersion(version, effective_from, ordered, hashlib.sha256(canonical.encode()).hexdigest())


def _load(conn: Connection, version: str) -> PriceTableVersion | None:
    from aicl.db import from_iso
    row = conn.execute("SELECT version, effective_from, sha256 FROM price_table_version WHERE version = ?",
                       (version,)).fetchone()
    if row is None:
        return None
    rates = tuple(Rate(r["meter"], r["unit_size"], r["micro_usd"]) for r in conn.execute(
        "SELECT meter, unit_size, micro_usd FROM price_rate WHERE version = ? ORDER BY meter", (version,)))
    return PriceTableVersion(row["version"], from_iso(row["effective_from"]), rates, row["sha256"])


def load_version(conn: Connection, version: str) -> PriceTableVersion:
    loaded = _load(conn, version)
    if loaded is None:
        raise AiclError("unavailable", "price table version is missing")
    return loaded


def import_price_table(conn: Connection, path: Path) -> PriceTableVersion:
    """Insert-only import; same version with a different hash is a startup failure."""
    from aicl.db import to_iso
    parsed = parse_price_table(Path(path).read_bytes())
    existing = _load(conn, parsed.version)
    if existing is not None:
        if existing.sha256 != parsed.sha256:
            raise AiclError("conflict", f"price table version {parsed.version} already imported with different content")
        return existing
    conn.execute("INSERT INTO price_table_version (version, effective_from, sha256, imported_at) VALUES (?,?,?,?)",
                 (parsed.version, to_iso(parsed.effective_from), parsed.sha256, to_iso(datetime.now(timezone.utc))))
    for rate in parsed.rates:
        conn.execute("INSERT INTO price_rate (version, meter, unit_size, micro_usd) VALUES (?,?,?,?)",
                     (parsed.version, rate.meter, rate.unit_size, rate.micro_usd))
    return parsed


def effective_version(conn: Connection, now: datetime) -> PriceTableVersion | None:
    """Greatest effective_from not later than `now`, or None (use-time `price_unavailable`)."""
    from aicl.db import to_iso
    row = conn.execute("SELECT version FROM price_table_version WHERE effective_from <= ? AND explicit_only = 0 "
                       "ORDER BY effective_from DESC LIMIT 1", (to_iso(now),)).fetchone()
    return None if row is None else _load(conn, row["version"])


def cost_micro_usd(version: PriceTableVersion, meter: str, units: int) -> int:
    """Price observed units; an absent optional meter is safe only for zero use."""
    for rate in version.rates:
        if rate.meter == meter:
            return -(-(units * rate.micro_usd) // rate.unit_size)
    if meter in OPTIONAL_METERS and units == 0:
        return 0
    raise AiclError("unavailable", f"no rate for meter {meter}")
