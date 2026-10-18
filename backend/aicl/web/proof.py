"""Composition and cross-surface equivalence proof contracts (aicl-experience/technical.md "Production wiring",
owner E11-5). Contract stubs: shapes and signatures only, no behavior.

The proof is test-composition evidence: `create_app(settings)` with `ports=None` under the test flags
(`AICL_TEST_MODE=1`, `AICL_ENVIRONMENT=test`). `inspect_composition` reads an already built app and reports what is
registered; the integration test asserts the report against the FINAL tuples below. Only the leaf ports are fakes.

Known gap the implementation phase closes (observed at 6f276d91): `aicl.ports.build_ports` fills a required port that
has no registered factory with a `SystemClock` instead of failing, so "fails startup when a required port is
missing" is not yet true. The E11-1 text already says a missing required port fails startup as
`composition incomplete: <port>`; the E11-5 implementation raises `CompositionIncomplete` from `build_ports` for a
`REQUIRED_PORTS` name without a registered factory (`clock` keeps its `SystemClock` default), and the test removes
one registry entry, expects the failure at startup, and restores the entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from aicl.creation.models import InstanceSnapshot

NOT_IMPLEMENTED = "E11-5 behavior is not implemented (contract stub)"

# Final composition the proof asserts (design: "Incremental composition port delivery (DR-30)").
FINAL_REQUIRED_PORTS: tuple[str, ...] = (
    "clock", "secret_store", "credential_broker", "provider_oauth", "work_executor", "resolver",
    "magic_link_sender", "chat_model",
)
FINAL_STARTUP_HOOKS: tuple[str, ...] = (
    "start_revocation_sweeper", "start_hold_reconciler", "start_magic_link_purge",
)
# Fields compared across creation surfaces (wizard, chat, direct canonical call). `id`, timestamps and the audit
# event id are per-instance; `version`, `status` and the rest must be equal for equal input.
EQUIVALENCE_FIELDS: tuple[str, ...] = (
    "template_id", "name", "instructions", "lifecycle", "status", "gated_reason", "version", "limits",
    "capabilities", "network_domains", "attachments",
)


class CompositionIncomplete(Exception):
    """Raised at startup when a required port has no registered implementation (`composition incomplete: <port>`)."""


@dataclass(frozen=True)
class CompositionReport:
    port_names: tuple[str, ...]  # fields of the built `Ports`
    route_factory_names: tuple[str, ...]  # `ROUTE_FACTORIES` entries
    hook_names: tuple[str, ...]  # `STARTUP_HOOKS` entries
    route_paths: frozenset[str]  # every path the built FastAPI app serves
    test_only_paths: frozenset[str]  # the `/__test__/*` subset (must be empty outside the test flags)


def inspect_composition(app: object) -> CompositionReport:
    """Read-only: reports ports, route factories, startup hooks and served paths of a built app."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def equivalent_surfaces(first: InstanceSnapshot, second: InstanceSnapshot) -> bool:
    """True when the two snapshots agree on every `EQUIVALENCE_FIELDS` field (wizard vs chat vs direct creation)."""
    raise NotImplementedError(NOT_IMPLEMENTED)
