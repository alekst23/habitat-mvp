"""Chat orchestrator and chat storage (aicl-experience/technical.md, owner E11-4).

The orchestrator, not the model, enforces every boundary rule:

- only the tools in ALLOWED_CHAT_TOOLS are reachable, each validated against its E11-2 input model in
  `aicl.creation.tools.TOOL_REGISTRY` (extra fields such as tenant, owner, credential or confirmation arguments
  are rejected by those models), invoked with the session's own AuthContext;
- the actor kind and surface of a creation are set by the server: a creation runs through the canonical
  `aicl.creation.service.create_instance(auth, request, actor_kind="chat", surface="chat", clock=...)`, because the
  HTTP tool handler records `owner`/`ui`; the result is the E11-2 CreateInstanceResult/InstanceSnapshot;
- the key is `chat_key(chat_session_id, turn)`, always set by the server (a model-supplied key is overwritten);
  user and instance text are plain text only (the pages escape them);
- it holds no reference to confirmation, connection, lifecycle, limit, capability, domain or work operations and
  never calls BudgetPort; a `validation_failed` result becomes an Ask for the offending field, `unavailable` a
  retryable message, `denied` a safe verbatim message.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Protocol

from pydantic import ValidationError

from aicl.chat.models import (
    ALLOWED_CHAT_TOOLS, CHAT_KEY_PREFIX, CHAT_RETENTION_DAYS, MAX_TURN, Ask, ChatMessage, ChatReply, ChatSlots,
    ChatState, Say, ToolCall,
)
from aicl.chat.ports import (
    AWAITING_FOR_FIELD, ChatModelPort, absorb_answer, ask_for, shown,
)
from aicl.clock import Clock
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.creation import service as creation
from aicl.creation.routes import field_errors_from
from aicl.creation.tools import TOOL_REGISTRY
from aicl.db import from_iso, to_iso

MAX_USER_TEXT = 8000
SLOT_FIELDS = ("name", "instructions", "enabled_capabilities")
FIELD_LABEL = {"name": "name", "instructions": "instructions", "enabled_capabilities": "capabilities"}
RETRY_TEXT = "I could not save that just now. Please say \"yes\" again in a moment."
REFUSED_TEXT = "I can't do that from chat. I can only create a draft agent, list templates or read an agent."
NOT_FOUND_TEXT = "I could not find that agent."


def chat_key(chat_session_id: str, turn: int) -> str:
    """`chat_<32 lowercase hex of chat_session_id>_<turn>`: 39 characters for turn 1, at most 44 for turn 999999,
    always matching `^[A-Za-z0-9_-]{16,64}$` (no colon). Raises ValueError outside 1..MAX_TURN."""
    if isinstance(turn, bool) or not isinstance(turn, int) or not 1 <= turn <= MAX_TURN:
        raise ValueError(f"chat turn must be an integer from 1 to {MAX_TURN}")
    return f"{CHAT_KEY_PREFIX}{uuid.UUID(chat_session_id).hex}_{turn}"


def _session_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise AiclError("not_found", "chat session not found") from None


class ChatStore(Protocol):
    """Tenant-scoped `chat_session` / `chat_message` storage. Another tenant's session is `not_found`."""

    def get_or_create_state(self, conn: object, auth: AuthContext, chat_session_id: str | None) -> ChatState:
        """None creates a new session (UUID4, turn 1); an unknown or foreign id raises not_found."""
        ...

    def save_turn(self, conn: object, auth: AuthContext, state: ChatState, user_text: str, reply_text: str, *,
                  previous_turn: int | None = None) -> None:
        """Persist the next state and both messages in one transaction. The messages are recorded at
        `previous_turn` (default `state.turn - 1`); raises `conflict` when the stored turn is no longer that
        (a concurrent message)."""
        ...

    def transcript(self, conn: object, auth: AuthContext, chat_session_id: str) -> list[ChatMessage]: ...


class SqliteChatStore:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def _purge_expired(self, conn, auth: AuthContext) -> None:
        cutoff = to_iso(self.clock.now() - timedelta(days=CHAT_RETENTION_DAYS))
        conn.execute("DELETE FROM chat_message WHERE tenant_id = ? AND chat_session_id IN "
                     "(SELECT id FROM chat_session WHERE tenant_id = ? AND updated_at < ?)",
                     (auth.tenant_id, auth.tenant_id, cutoff))
        conn.execute("DELETE FROM chat_session WHERE tenant_id = ? AND updated_at < ?", (auth.tenant_id, cutoff))

    def get_or_create_state(self, conn, auth: AuthContext, chat_session_id: str | None) -> ChatState:
        self._purge_expired(conn, auth)
        if chat_session_id is None:
            new_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO chat_session (id, tenant_id, owner_id, turn, slots_json, awaiting, created_at, "
                         "updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (new_id, auth.tenant_id, auth.owner_id, 1, "{}", None, now, now))
            return ChatState(new_id, 1)
        row = self._row(conn, auth, chat_session_id)
        return ChatState(row["id"], row["turn"], _slots_from_json(row["slots_json"]), row["awaiting"])

    def _row(self, conn, auth: AuthContext, chat_session_id: str):
        row = conn.execute("SELECT * FROM chat_session WHERE id = ? AND tenant_id = ?",
                           (_session_id(chat_session_id), auth.tenant_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "chat session not found")
        return row

    def save_turn(self, conn, auth: AuthContext, state: ChatState, user_text: str, reply_text: str, *,
                  previous_turn: int | None = None) -> None:
        previous_turn = state.turn - 1 if previous_turn is None else previous_turn
        now = to_iso(self.clock.now())
        updated = conn.execute(
            "UPDATE chat_session SET turn = ?, slots_json = ?, awaiting = ?, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND turn = ?",
            (state.turn, _slots_to_json(state.slots), state.awaiting, now, state.chat_session_id,
             auth.tenant_id, previous_turn)).rowcount
        if updated != 1:
            raise AiclError("conflict", "chat session changed; reload and retry")
        for role, text in (("user", user_text), ("assistant", reply_text)):
            conn.execute("INSERT INTO chat_message (chat_session_id, tenant_id, turn, role, text, created_at) "
                         "VALUES (?,?,?,?,?,?)", (state.chat_session_id, auth.tenant_id, previous_turn, role, text, now))

    def transcript(self, conn, auth: AuthContext, chat_session_id: str) -> list[ChatMessage]:
        row = self._row(conn, auth, chat_session_id)
        rows = conn.execute("SELECT * FROM chat_message WHERE chat_session_id = ? AND tenant_id = ? ORDER BY id",
                            (row["id"], auth.tenant_id)).fetchall()
        return [ChatMessage(r["chat_session_id"], r["turn"], r["role"], r["text"], from_iso(r["created_at"]))
                for r in rows]


def _slots_to_json(slots: ChatSlots) -> str:
    caps = None if slots.enabled_capabilities is None else sorted(slots.enabled_capabilities)
    return json.dumps({"name": slots.name, "instructions": slots.instructions, "enabled_capabilities": caps},
                      sort_keys=True)


def _slots_from_json(text: str) -> ChatSlots:
    data = json.loads(text or "{}")
    caps = data.get("enabled_capabilities")
    return ChatSlots(data.get("name"), data.get("instructions"), None if caps is None else frozenset(caps))


class ChatOrchestrator(Protocol):
    def transcript(self, auth: AuthContext, chat_session_id: str | None) -> list[ChatMessage]:
        """Messages for `GET /chat` (empty for a new session)."""
        ...

    def handle_message(self, auth: AuthContext, chat_session_id: str | None, user_text: str) -> ChatReply:
        """One owner turn: model step, allow-listed tool call if any, persisted state, reply and instance id."""
        ...


class SqliteChatOrchestrator:
    """Orchestrator over the E11-1 Database. The constructor signature is the contract."""

    def __init__(self, db: object, clock: Clock, model: ChatModelPort) -> None:
        self.db = db
        self.clock = clock
        self.model = model
        self.store = SqliteChatStore(clock)

    def transcript(self, auth: AuthContext, chat_session_id: str | None) -> list[ChatMessage]:
        if chat_session_id is None:
            return []
        with self.db.reader() as conn:
            return self.store.transcript(conn, auth, chat_session_id)

    def handle_message(self, auth: AuthContext, chat_session_id: str | None, user_text: str) -> ChatReply:
        if not isinstance(user_text, str) or not user_text.strip():
            raise creation.validation_failed(("text", "required"))
        if len(user_text) > MAX_USER_TEXT:
            raise creation.validation_failed(("text", "length"))
        with self.db.transaction() as conn:
            state = self.store.get_or_create_state(conn, auth, chat_session_id)
        if state.turn > MAX_TURN:
            raise AiclError("invalid_state", "this conversation is full; start a new one")

        step = self.model.next_step(state, user_text)
        instance_id = None
        if isinstance(step, Ask):
            reply = step.text
            next_state = ChatState(state.chat_session_id, state.turn + 1, absorb_answer(state, user_text),
                                   AWAITING_FOR_FIELD.get(step.field))
        elif isinstance(step, ToolCall):
            reply, instance_id, next_state = self._tool_turn(auth, state, step)
        else:
            reply = step.text
            next_state = ChatState(state.chat_session_id, state.turn + 1)  # a Say ends the exchange: fresh slots
        with self.db.transaction() as conn:
            self.store.save_turn(conn, auth, next_state, user_text, reply, previous_turn=state.turn)
        return ChatReply(state.chat_session_id, state.turn, reply, instance_id)

    # -- tool boundary ------------------------------------------------------------------------------------
    def _tool_turn(self, auth: AuthContext, state: ChatState, step: ToolCall) -> tuple[str, str | None, ChatState]:
        """Run one allow-listed tool call; return (reply, created instance id, next state)."""
        unchanged = ChatState(state.chat_session_id, state.turn + 1, state.slots, state.awaiting)
        if step.tool not in ALLOWED_CHAT_TOOLS or step.tool not in TOOL_REGISTRY:
            return REFUSED_TEXT, None, unchanged
        tool = TOOL_REGISTRY[step.tool]
        arguments = dict(step.arguments)
        if step.tool == "create_instance":
            arguments["idempotency_key"] = chat_key(state.chat_session_id, state.turn)  # server-owned
        try:
            payload = tool.input_model.model_validate(arguments)
            if step.tool == "create_instance":
                result = creation.create_instance(auth, payload, actor_kind="chat", surface="chat", clock=self.clock)
                name = shown(result.instance.name)
                return (f'Created "{name}" as a draft. It is not active until you activate it.',
                        result.instance.id, ChatState(state.chat_session_id, state.turn + 1))
            if step.tool == "list_templates":
                names = ", ".join(t["name"] for t in creation.list_templates()["templates"])
                return f"Available templates: {names}.", None, unchanged
            snapshot = creation.read_instance_snapshot(auth, payload.instance_id, clock=self.clock)
            return f'"{shown(snapshot.name)}" is a {snapshot.status} agent.', None, unchanged
        except ValidationError as exc:
            return self._rejected(state, field_errors_from(exc), unchanged)
        except AiclError as exc:
            return self._rejected(state, exc, unchanged)

    def _rejected(self, state: ChatState, exc: AiclError, unchanged: ChatState) -> tuple[str, None, ChatState]:
        if exc.error == "validation_failed":
            for item in exc.extra.get("field_errors", []):
                field = item.get("field")
                if field in SLOT_FIELDS:
                    slots = state.slots
                    cleared = ChatSlots(None if field == "name" else slots.name,
                                        None if field == "instructions" else slots.instructions,
                                        None if field == "enabled_capabilities" else slots.enabled_capabilities)
                    ask = ask_for(field, f"The {FIELD_LABEL[field]} could not be accepted ({item.get('code')}).")
                    return ask.text, None, ChatState(state.chat_session_id, state.turn + 1, cleared,
                                                     AWAITING_FOR_FIELD[field])
            return REFUSED_TEXT, None, unchanged
        if exc.error == "unavailable":  # retryable: nothing was committed; the slots stay and "yes" retries
            return RETRY_TEXT, None, unchanged
        if exc.error == "denied":
            return f"That was not allowed: {exc.message or 'denied'}.", None, unchanged
        if exc.error == "not_found":
            return NOT_FOUND_TEXT, None, unchanged
        raise exc
