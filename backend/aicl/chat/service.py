"""Chat orchestrator contract and chat storage (aicl-experience/technical.md, owner E11-4).

Signatures and docstrings only. The orchestrator, not the model, enforces every boundary rule:

- only the tools in ALLOWED_CHAT_TOOLS are reachable, each validated against its E11-2 input model in
  `aicl.creation.tools.TOOL_REGISTRY` (extra fields such as tenant, owner, credential or confirmation arguments
  are rejected by those models), invoked with the session's own AuthContext;
- the actor kind and surface of a creation are set by the server: a creation runs through the canonical
  `aicl.creation.service.create_instance(auth, request, actor_kind="chat", surface="chat", clock=...)`, because the
  HTTP tool handler records `owner`/`ui`; the result is the E11-2 CreateInstanceResult/InstanceSnapshot;
- the key is `chat_key(chat_session_id, turn)`; user and instance text are escaped plain text only;
- it holds no reference to confirmation, connection, lifecycle, limit, capability, domain or work operations and
  never calls BudgetPort; a `validation_failed` result becomes an Ask for the offending field, `unavailable` a
  retryable message, `denied` a safe verbatim message.
"""

from __future__ import annotations

from typing import Protocol

from aicl.chat.models import ChatMessage, ChatReply, ChatState
from aicl.chat.ports import NOT_IMPLEMENTED, ChatModelPort
from aicl.clock import Clock
from aicl.control.auth import AuthContext


def chat_key(chat_session_id: str, turn: int) -> str:
    """`chat_<32 lowercase hex of chat_session_id>_<turn>`: 39 characters for turn 1, at most 44 for turn 999999,
    always matching `^[A-Za-z0-9_-]{16,64}$` (no colon). Raises ValueError outside 1..MAX_TURN."""
    raise NotImplementedError(NOT_IMPLEMENTED)


class ChatStore(Protocol):
    """Tenant-scoped `chat_session` / `chat_message` storage. Another tenant's session is `not_found`."""

    def get_or_create_state(self, conn: object, auth: AuthContext, chat_session_id: str | None) -> ChatState:
        """None creates a new session (UUID4, turn 1); an unknown or foreign id raises not_found."""
        ...

    def save_turn(self, conn: object, auth: AuthContext, state: ChatState, user_text: str, reply_text: str) -> None:
        """Persist the next state and both messages in one transaction."""
        ...

    def transcript(self, conn: object, auth: AuthContext, chat_session_id: str) -> list[ChatMessage]: ...


class ChatOrchestrator(Protocol):
    def transcript(self, auth: AuthContext, chat_session_id: str | None) -> list[ChatMessage]:
        """Messages for `GET /chat` (empty for a new session)."""
        ...

    def handle_message(self, auth: AuthContext, chat_session_id: str | None, user_text: str) -> ChatReply:
        """One owner turn: model step, allow-listed tool call if any, persisted state, reply and instance id."""
        ...


class SqliteChatOrchestrator:
    """Stub implementation over the E11-1 Database. The constructor signature is the contract."""

    def __init__(self, db: object, clock: Clock, model: ChatModelPort) -> None:
        self.db = db
        self.clock = clock
        self.model = model

    def transcript(self, auth: AuthContext, chat_session_id: str | None) -> list[ChatMessage]:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def handle_message(self, auth: AuthContext, chat_session_id: str | None, user_text: str) -> ChatReply:
        raise NotImplementedError(NOT_IMPLEMENTED)
