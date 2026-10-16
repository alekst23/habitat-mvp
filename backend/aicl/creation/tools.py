"""First-party web-app tool registry (technical.md "WebAppToolSchemas", owner E11-2).

Exactly `list_templates`, `create_instance`, `read_instance` at `POST /app-tools/{name}`. Every input model
forbids extra fields, so tenant_id, owner_id, session_id, credential and confirmation arguments are rejected
(mapped to validation_failed/unknown_argument by the implementation). No lifecycle, capability, limit,
domain, connection, confirmation, gate or budget operation is a tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict

from aicl.control.auth import AuthContext
from aicl.creation.models import CreateInstanceRequest
from aicl.creation.service import NOT_IMPLEMENTED


class ListTemplatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadInstanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: str


@dataclass(frozen=True)
class WebAppTool:
    name: str
    input_model: type[BaseModel]
    handler: Callable[[AuthContext, BaseModel], object]


def _unimplemented(_auth: AuthContext, _payload: BaseModel) -> object:
    raise NotImplementedError(NOT_IMPLEMENTED)


# Static registry: name -> tool. Handlers are wired by the implementation.
TOOL_REGISTRY: dict[str, WebAppTool] = {
    "list_templates": WebAppTool("list_templates", ListTemplatesInput, _unimplemented),
    "create_instance": WebAppTool("create_instance", CreateInstanceRequest, _unimplemented),
    "read_instance": WebAppTool("read_instance", ReadInstanceInput, _unimplemented),
}
