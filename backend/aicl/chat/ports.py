"""ChatModelPort and ScriptedChatModel (aicl-experience/technical.md "ChatModelPort", owner E11-4).

`ScriptedChatModel` is the only enabled implementation (`AICL_CHAT_MODEL_MODE=fake`): a deterministic
keyword-matching slot-filling state machine with no network or model call and no cost. It asks for the name, the
instructions and the capabilities (listing the catalog names), summarizes, and only on an exact "yes"/"create" at
the confirmation step emits a `create_instance` ToolCall built from the collected slots. A real model is provider
enablement and is rejected at startup by Settings.

The model is a pure function of `(state, user_text)`. Slot capture (`absorb_answer`) and the user-facing texts live
here so the model and the orchestrator share one definition; the orchestrator, not the model, enforces the
boundary rules (allow-list, validation, server-owned idempotency key).
"""

from __future__ import annotations

import re
from typing import Protocol

from aicl.chat.models import Ask, ChatSlots, ChatState, ChatStep, Say, ToolCall
from aicl.control.instances import CATALOG_CAPABILITIES

NOT_IMPLEMENTED = "E11-4 behavior is not implemented (contract stub)"  # retained for the stub-contract importers

# Ask.field vocabulary: the three slot fields plus the summary confirmation step.
FIELD_FOR_AWAITING = {"name": "name", "instructions": "instructions", "capabilities": "enabled_capabilities",
                      "confirmation": "confirmation"}
AWAITING_FOR_FIELD = {field: awaiting for awaiting, field in FIELD_FOR_AWAITING.items()}
CONFIRM_WORDS = frozenset({"yes", "create"})
CANCEL_WORDS = frozenset({"no", "cancel"})
NO_CAPABILITY_WORDS = frozenset({"none", "no", "nothing", "skip"})
SUMMARY_SHOWN_CHARS = 200

ASK_TEXT = {
    "name": "What name should your agent have? (1 to 80 characters)",
    "instructions": "What instructions should your agent follow? (up to 4000 characters)",
    "enabled_capabilities": "Which capabilities should it have? Available: " + ", ".join(CATALOG_CAPABILITIES)
                            + ". Reply with the names separated by spaces or commas, or 'none'.",
}


class ChatModelPort(Protocol):
    def next_step(self, state: ChatState, user_text: str) -> ChatStep:
        """Pure function of `(state, user_text)`: no I/O, no randomness. `user_text` is untrusted data."""
        ...


def parse_capabilities(text: str) -> frozenset[str] | None:
    """Catalog names mentioned in the text; 'none' words mean the empty set; anything else is unrecognized."""
    tokens = set(re.findall(r"[a-z]+(?:\.[a-z]+)?", text.lower()))
    found = frozenset(c for c in CATALOG_CAPABILITIES if c in tokens)
    if found:
        return found
    return frozenset() if tokens & NO_CAPABILITY_WORDS else None


def absorb_answer(state: ChatState, user_text: str) -> ChatSlots:
    """Slots after taking `user_text` as the answer to the pending question (unchanged when nothing is pending
    or the answer is empty/unrecognized). Values are stored verbatim; the canonical creation service validates."""
    slots = state.slots
    if state.awaiting == "name" and user_text.strip():
        return ChatSlots(user_text.strip(), slots.instructions, slots.enabled_capabilities)
    if state.awaiting == "instructions" and user_text.strip():
        return ChatSlots(slots.name, user_text.strip(), slots.enabled_capabilities)
    if state.awaiting == "capabilities":
        parsed = parse_capabilities(user_text)
        if parsed is not None:
            return ChatSlots(slots.name, slots.instructions, parsed)
    return slots


def ask_for(field: str, prefix: str = "") -> Ask:
    return Ask(field, (prefix + " " if prefix else "") + ASK_TEXT[field])


def shown(value: str) -> str:
    return value if len(value) <= SUMMARY_SHOWN_CHARS else value[:SUMMARY_SHOWN_CHARS] + "..."


def summary_ask(slots: ChatSlots) -> Ask:
    caps = ", ".join(sorted(slots.enabled_capabilities or ())) or "none"
    return Ask("confirmation", f'Here is what I will create: name "{shown(slots.name or "")}", instructions '
                               f'"{shown(slots.instructions or "")}", capabilities: {caps}. Reply "yes" to create it.')


def next_missing(slots: ChatSlots) -> str | None:
    if slots.name is None:
        return "name"
    if slots.instructions is None:
        return "instructions"
    if slots.enabled_capabilities is None:
        return "enabled_capabilities"
    return None


class ScriptedChatModel:
    """Deterministic fake model behind ChatModelPort (keyword matching only)."""

    def next_step(self, state: ChatState, user_text: str) -> ChatStep:
        normalized = user_text.strip().lower().rstrip(".!")
        if state.awaiting == "confirmation":
            if next_missing(state.slots) is None and normalized in CONFIRM_WORDS:
                slots = state.slots
                return ToolCall("create_instance", {
                    "template_id": "default", "name": slots.name, "instructions": slots.instructions,
                    "enabled_capabilities": sorted(slots.enabled_capabilities)})
            if normalized in CANCEL_WORDS:
                return Say("Okay, I did not create anything. Say hello whenever you want to start again.")
            if next_missing(state.slots) is None:
                return summary_ask(state.slots)
        slots = absorb_answer(state, user_text)
        missing = next_missing(slots)
        return ask_for(missing) if missing else summary_ask(slots)
