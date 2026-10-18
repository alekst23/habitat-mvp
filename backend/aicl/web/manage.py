"""Management pages and form routes (aicl-experience/technical.md, owner E11-5). Contract stub.

`manage_router` is NOT yet in `aicl.routes.ROUTE_FACTORIES`; the implementation phase appends that one line (the
E11-1 extension point) and updates the composition test that pins the route-factory count (currently 4).

Rules the implementation must keep:

- Every page redirects an unauthenticated visitor to `/`; every POST uses the shared E11-1 `require_csrf`
  dependency (urlencoded forms carry `csrf_token`, which `FormCsrfShim` copies into `X-CSRF-Token`; a page that
  uses `fetch` sends the `X-CSRF-Token` header itself). No route reads a tenant or owner from the client.
- Mutation forms post the page's `expected_version` to the E11-2 `InstanceOperations` (`SqliteInstanceOperations`),
  then show the committed instance, or the structured denial (`conflict` with `current_version`, `invalid_state`,
  `invalid_transition`, `validation_failed` field errors, `denied` with `reason`, including `gate_unresolved`).
- `GET /workspace` already exists in `web.routes.web_router` (E11-3) with a direct SQL list. The implementation
  changes that handler to render `WorkspaceView` instead of registering a second `/workspace` (FastAPI serves the
  first registered match, so a duplicate in this router would never run).
- Existing E11-2 routes stay as they are: `POST /instances/{id}/work-requests` and `POST /connections/oauth/begin`
  take JSON, `POST /pending-actions/{id}/confirm` takes no body, and `GET /connections/oauth/callback` redirects to
  `/connections?oauth=connected|denied`, so `GET /connections` below must show that result. Pages call them with
  minimal vanilla JS `fetch` (same origin, `X-CSRF-Token`) or through form routes that call the same services.
- Pages state that revocation does not undo actions already taken, that real provider adapters are not enabled and
  that gated reasons stay until the owner fixes the control and the system re-checks it. Simulated work is labelled
  simulated. User-supplied text is rendered escaped only; no page contains a credential or `secret_ref`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

NOT_IMPLEMENTED = "E11-5 behavior is not implemented (contract stub)"


@dataclass(frozen=True)
class ManagementRoute:
    method: str
    path: str
    calls: str  # the existing operation the route delegates to


# Proposed route table (paths are proposals owned by E11-5; the `calls` targets are existing E11-2 contracts).
MANAGEMENT_ROUTES: tuple[ManagementRoute, ...] = (
    ManagementRoute("GET", "/instances/{instance_id}", "ProjectionService.instance_detail"),
    ManagementRoute("GET", "/connections", "ProjectionService.connections"),
    ManagementRoute("POST", "/instances/{instance_id}/lifecycle", "InstanceOperations.set_lifecycle"),
    ManagementRoute("POST", "/instances/{instance_id}/capabilities", "InstanceOperations.set_capability"),
    ManagementRoute("POST", "/instances/{instance_id}/limits", "InstanceOperations.set_limits"),
    ManagementRoute("POST", "/instances/{instance_id}/domains", "InstanceOperations.add_network_domain"),
    ManagementRoute("POST", "/instances/{instance_id}/domains/remove", "InstanceOperations.remove_network_domain"),
    ManagementRoute("POST", "/instances/{instance_id}/attachments", "InstanceOperations.attach_connection"),
    ManagementRoute("POST", "/instances/{instance_id}/attachments/detach", "InstanceOperations.detach_connection"),
    ManagementRoute("POST", "/instances/{instance_id}/resolve-gate", "InstanceOperations.resolve_gate"),
    ManagementRoute("POST", "/connections/{connection_id}/revoke", "ConnectionService.revoke_connection"),
)


def manage_router(ctx) -> APIRouter:
    """`(AppContext) -> APIRouter` factory in the ROUTE_FACTORIES shape."""
    raise NotImplementedError(NOT_IMPLEMENTED)
