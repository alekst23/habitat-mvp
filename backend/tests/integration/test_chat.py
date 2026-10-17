"""E11-4 integration proofs (F3-S3 chat half, F3-S5 chat creation, F3-S6): the chat orchestrator over the real
SQLite Env and the canonical create_instance. Chat creates exactly what a direct canonical call creates, through
the allow-listed tools only, recovers from validation errors, consumes no budget and never touches confirmation.
Chat versus wizard equivalence across surfaces is E11-5's; here chat is compared with a direct create_instance."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aicl.chat.models import ChatState, ToolCall
from aicl.chat.service import SqliteChatOrchestrator, chat_key
from aicl.chat.ports import ScriptedChatModel
from aicl.control.audit import SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.creation.models import CreateInstanceRequest
from aicl.creation.service import create_instance, read_instance_snapshot

KEY_RE = re.compile(r"^chat_[0-9a-f]{32}_[0-9]+$")
AUTHORITY_ARGUMENTS = {"tenant_id": "other", "owner_id": "other", "credential": "c", "confirmation_id": "c",
                       "confirmed": True}
SLOT_ANSWERS = ["hello", "Chat Helper", "Answer politely", "inference", "yes"]  # greeting, name, instructions, caps, go


def new_owner() -> AuthContext:
    owner = str(uuid.uuid4())
    return AuthContext(owner, owner, str(uuid.uuid4()), datetime(2100, 1, 1, tzinfo=timezone.utc))


def count(env, sql: str, args: tuple = ()) -> int:
    with env.db.reader() as conn:
        return conn.execute(sql, args).fetchone()[0]


def instances(env, auth) -> int:
    return count(env, "SELECT count(*) FROM agent_instance WHERE tenant_id = ?", (auth.tenant_id,))


def drive(chat, auth, texts, session=None):
    """Send each text as one owner turn; return (session id, replies)."""
    replies = []
    for text in texts:
        reply = chat.handle_message(auth, session, text)
        session = reply.chat_session_id
        replies.append(reply)
    return session, replies


class RogueModel:
    """A model that tries to step outside the allow-list or smuggle authority into a tool call."""

    def __init__(self, step):
        self.step = step

    def next_step(self, state: ChatState, user_text: str):
        return self.step


@pytest.mark.ac("E11-4.AC1", code="backend/aicl/chat/service.py:SqliteChatOrchestrator")
def test_chat_creation_equals_direct_canonical_call_consumes_no_budget_and_is_retry_idempotent(build_env):
    env = build_env()
    auth = new_owner()
    chat = SqliteChatOrchestrator(env.db, env.clock, ScriptedChatModel())

    session, replies = drive(chat, auth, SLOT_ANSWERS)
    created = replies[-1]
    assert created.instance_id and all(r.instance_id is None for r in replies[:-1])  # created only on the confirmation
    assert instances(env, auth) == 1
    assert [m.role for m in chat.transcript(auth, session)] == ["user", "assistant"] * len(SLOT_ANSWERS)

    # the key is the derived chat key, recorded for this tenant (a retry of that turn re-sends the same key)
    (key,) = [r[0] for r in _rows(env, "SELECT idempotency_key FROM create_request WHERE tenant_id = ?",
                                  (auth.tenant_id,))]
    assert KEY_RE.fullmatch(key) and key.startswith("chat_" + uuid.UUID(session).hex + "_")
    assert key == chat_key(session, int(key.rsplit("_", 1)[1]))

    request = CreateInstanceRequest(idempotency_key=key, template_id="default", name="Chat Helper",
                                    instructions="Answer politely", enabled_capabilities=frozenset({"inference"}))
    snapshot = read_instance_snapshot(auth, created.instance_id, clock=env.clock)
    replay = create_instance(auth, request, actor_kind="chat", surface="chat", clock=env.clock)
    assert replay.created is False and replay.instance == snapshot  # the chat result IS the canonical result
    assert instances(env, auth) == 1  # retrying the same turn key creates nothing new

    other = new_owner()  # an independent direct canonical call for the same request has the same content
    direct = create_instance(other, request, actor_kind="chat", surface="chat", clock=env.clock).instance
    for field in ("template_id", "name", "instructions", "lifecycle", "status", "version", "limits",
                  "capabilities", "network_domains", "attachments"):
        assert getattr(direct, field) == getattr(snapshot, field), field
    assert snapshot.lifecycle == "draft" and snapshot.name == "Chat Helper"
    assert [c for c, on in snapshot.capabilities.items() if on] == ["inference"]

    # chat is not an instance work request: no budget, usage, confirmation or pending action rows
    for table in ("budget_hold", "budget_usage", "action_confirmation", "pending_action"):
        assert count(env, f"SELECT count(*) FROM {table}") == 0, table
    events = SqliteAuditLog().list_for_instance(auth, created.instance_id)
    assert [(e.event_type, e.actor_kind, e.details) for e in events] == [
        ("instance.created", "chat", {"template_id": "default", "surface": "chat"})]
    with pytest.raises(AiclError) as other_tenant:  # another tenant cannot read this chat session
        chat.transcript(other, session)
    assert other_tenant.value.error == "not_found"


def _rows(env, sql: str, args: tuple = ()):
    with env.db.reader() as conn:
        return [tuple(r) for r in conn.execute(sql, args)]


@pytest.mark.ac("E11-4.AC1", code="backend/aicl/chat/service.py:SqliteChatOrchestrator")
def test_validation_error_becomes_an_ask_for_the_field_and_the_corrected_answer_creates(build_env):
    env = build_env()
    auth = new_owner()
    chat = SqliteChatOrchestrator(env.db, env.clock, ScriptedChatModel())

    session, replies = drive(chat, auth, ["hello", "Chat Helper", "x" * 4001, "inference", "yes"])
    assert replies[-1].instance_id is None and instances(env, auth) == 0  # denied: nothing created, no tool result
    assert "instructions" in replies[-1].text.lower()  # the offending field is named truthfully

    created = None
    for text in ("Answer politely", "inference", "yes", "yes", "yes"):  # corrected field, then answers until created
        reply = chat.handle_message(auth, session, text)
        if reply.instance_id:
            created = reply.instance_id
            break
    assert created and instances(env, auth) == 1  # recovered by correcting the field: exactly one instance
    assert read_instance_snapshot(auth, created, clock=env.clock).instructions == "Answer politely"


@pytest.mark.ac("E11-4.AC1", code="backend/aicl/chat/service.py:SqliteChatOrchestrator")
def test_orchestrator_rejects_tools_outside_the_allow_list_and_authority_arguments(build_env):
    env = build_env()
    auth = new_owner()
    good = {"template_id": "default", "name": "Rogue", "instructions": "x", "enabled_capabilities": ["inference"],
            "idempotency_key": "chat_" + "a" * 32 + "_1"}
    attempts = [ToolCall("set_lifecycle", {"instance_id": "x", "action": "activate"}),
                ToolCall("create_confirmation", {"pending_action_id": "x"}),
                ToolCall("revoke_connection", {"connection_id": "x"})]
    attempts += [ToolCall("create_instance", {**good, field: value}) for field, value in AUTHORITY_ARGUMENTS.items()]
    for step in attempts:
        chat = SqliteChatOrchestrator(env.db, env.clock, RogueModel(step))
        try:
            reply = chat.handle_message(auth, None, "anything")
        except AiclError:
            continue  # a typed rejection is acceptable; a created instance or a confirmation never is
        assert reply.instance_id is None, step
    assert instances(env, auth) == 0
    for table in ("action_confirmation", "pending_action", "budget_hold", "connection"):
        assert count(env, f"SELECT count(*) FROM {table}") == 0, table

    # a read of another tenant's instance through chat is not_found, never a snapshot
    victim = new_owner()
    made = create_instance(victim, CreateInstanceRequest(
        idempotency_key="wiz_" + "v" * 32, template_id="default", name="Private", instructions="secret plan"),
        clock=env.clock).instance
    chat = SqliteChatOrchestrator(env.db, env.clock, RogueModel(ToolCall("read_instance", {"instance_id": made.id})))
    try:
        reply = chat.handle_message(auth, None, "show it")
    except AiclError as exc:
        assert exc.error == "not_found"
    else:
        assert "Private" not in reply.text and "secret plan" not in reply.text


@pytest.mark.ac("E11-4.AC1", code="backend/aicl/chat/routes.py:chat_router")
def test_chat_routes_redirect_anonymous_visitors_and_require_csrf(web):
    with TestClient(web.app) as anonymous:  # no session cookie
        page = anonymous.get("/chat", follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/"
        assert anonymous.post("/chat/messages", json={"text": "hi"}).status_code in (401, 403)
    signed_in = web.owner_a.get("/chat", follow_redirects=False)
    assert signed_in.status_code == 200
    forged = web.owner_a.post("/chat/messages", json={"text": "hi"})  # session cookie but no CSRF token
    assert forged.status_code == 403 and forged.json()["error"] == "denied"
