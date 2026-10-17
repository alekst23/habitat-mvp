"""ChatModelPort and ScriptedChatModel (aicl-experience/technical.md "ChatModelPort", owner E11-4).

Contract stub only. `ScriptedChatModel` is the only enabled implementation (`AICL_CHAT_MODEL_MODE=fake`): a
deterministic keyword-matching slot-filling state machine with no network or model call and no cost. Its
behavior (ask name, instructions, capabilities listing the six catalog names; summarize; on "yes"/"create"
emit a `create_instance` ToolCall) belongs to the implementation phase. A real model is provider enablement
and is rejected at startup by Settings. Not registered in PORT_REGISTRY/REQUIRED_PORTS here; E11-4 does that.
"""

from __future__ import annotations

from typing import Protocol

from aicl.chat.models import ChatState, ChatStep

NOT_IMPLEMENTED = "E11-4 behavior is not implemented (contract stub)"


class ChatModelPort(Protocol):
    def next_step(self, state: ChatState, user_text: str) -> ChatStep:
        """Pure function of `(state, user_text)`: no I/O, no randomness. `user_text` is untrusted data."""
        ...


class ScriptedChatModel:
    """Deterministic fake model behind ChatModelPort (keyword matching only)."""

    def next_step(self, state: ChatState, user_text: str) -> ChatStep:
        raise NotImplementedError(NOT_IMPLEMENTED)
