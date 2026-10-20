"""ChatState, ChatStep and chat storage/reply shapes (aicl-experience/technical.md, owner E11-4).

Shapes and constants only; no behavior. Tables `chat_session` and `chat_message` are tenant scoped and are
created by the E11-4 implementation migration (not created here). Proposed columns, derived from ChatState:
`chat_session (id, tenant_id, owner_id, turn, slots_json, awaiting, created_at, updated_at)` and
`chat_message (id, chat_session_id, tenant_id, turn, role, text, created_at)`; `role` is `user` or `assistant`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# The only tools reachable from chat (WebAppToolSchemas, owner E11-2); the orchestrator enforces this list.
ALLOWED_CHAT_TOOLS: tuple[str, ...] = ("list_templates", "create_instance", "read_instance")
# Conventions "Key pattern": chat key is `chat_<32 lowercase hex of chat_session_id>_<turn>`, turn 1..999999.
MAX_TURN = 999_999
CHAT_KEY_PREFIX = "chat_"
CHAT_RETENTION_DAYS = 30

# Proposed vocabulary for `awaiting`, from the specified slot order: name, instructions, capabilities, then the
# summary confirmation ("yes"/"create"). `None` means nothing is pending (before the first prompt or after create).
Awaiting = Literal["name", "instructions", "capabilities", "confirmation"]
ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatSlots:
    """Slot values collected so far; never a tenant, owner, credential or confirmation field."""

    name: str | None = None
    instructions: str | None = None
    enabled_capabilities: frozenset[str] | None = None


@dataclass(frozen=True)
class ChatState:
    chat_session_id: str  # UUID4 string; its 32-hex form (`uuid.hex`) feeds the idempotency key
    turn: int  # decimal integer from 1
    slots: ChatSlots = field(default_factory=ChatSlots)
    awaiting: Awaiting | None = None


@dataclass(frozen=True)
class Ask:
    """Ask the owner for one field (`name`, `instructions` or `enabled_capabilities`)."""

    field: str
    text: str


@dataclass(frozen=True)
class ToolCall:
    """Produced only by the state machine from validated slots, never from user or instance text."""

    tool: str  # one of ALLOWED_CHAT_TOOLS
    arguments: dict


@dataclass(frozen=True)
class Say:
    text: str


ChatStep = Ask | ToolCall | Say


@dataclass(frozen=True)
class ChatMessage:
    chat_session_id: str
    turn: int
    role: ChatRole
    text: str  # untrusted data: rendered escaped, never interpreted
    created_at: datetime


@dataclass(frozen=True)
class ChatReply:
    """`POST /chat/messages` result: the reply and, after creation, the new instance id for the page link."""

    chat_session_id: str
    turn: int
    text: str
    instance_id: str | None = None
