"""First-party web-app tool registry (technical.md "WebAppToolSchemas", owner E11-2).

Exactly `list_templates`, `create_instance`, `read_instance` at `POST /app-tools/{name}`. Every input model
forbids extra fields, so tenant_id, owner_id, session_id, credential and confirmation arguments are rejected
(mapped to validation_failed/unknown_argument). No lifecycle, capability, limit, domain, connection,
confirmation, gate or budget operation is a tool.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from pydantic import BaseModel, ConfigDict

from aicl.control.auth import AuthContext
from aicl.creation import service
from aicl.creation.models import CreateInstanceRequest
from aicl.db import to_iso


class ListTemplatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadInstanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: str


@dataclass(frozen=True)
class WebAppTool:
    name: str
    input_model: type[BaseModel]
    handler: Callable[..., object]  # (auth, payload, ctx)


def to_jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime):
        return to_iso(value).replace(".000000Z", "Z")
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def _list_templates(_auth: AuthContext, _payload: BaseModel, _ctx=None) -> object:
    return service.list_templates()


def _create_instance(auth: AuthContext, payload: BaseModel, ctx=None) -> object:
    return to_jsonable(service.create_instance(auth, payload, actor_kind="owner", surface="ui",
                                               clock=getattr(ctx, "clock", None)))


def _read_instance(auth: AuthContext, payload: BaseModel, ctx=None) -> object:
    stale = getattr(getattr(ctx, "settings", None), "hold_stale_seconds", service.DEFAULT_HOLD_STALE_SECONDS)
    return to_jsonable(service.read_instance_snapshot(auth, payload.instance_id, clock=getattr(ctx, "clock", None),
                                                      hold_stale_seconds=stale))


# Static registry: name -> tool.
TOOL_REGISTRY: dict[str, WebAppTool] = {
    "list_templates": WebAppTool("list_templates", ListTemplatesInput, _list_templates),
    "create_instance": WebAppTool("create_instance", CreateInstanceRequest, _create_instance),
    "read_instance": WebAppTool("read_instance", ReadInstanceInput, _read_instance),
}
