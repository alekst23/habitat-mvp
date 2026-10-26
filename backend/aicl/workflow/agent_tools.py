"""Server-owned agent capabilities, independent of a task, topic or source.

An owner's saved tool selection grants a capability, not instructions from a
retrieved document. New tools need an implementation, permission and cost bound
here before the assistant can offer them.
"""
from aicl.control.errors import AiclError

TOOL_CATALOG = (
    {"id": "web_search", "title": "Public web research",
     "description": "Let the agent choose search queries and sources for your goal. Up to one web search per deliverable; results include source links."},
)
_TOOL_IDS = frozenset(tool["id"] for tool in TOOL_CATALOG)


def normalize_tools(value):
    if (not isinstance(value, list) or len(value) > len(_TOOL_IDS)
            or any(type(item) is not str or item not in _TOOL_IDS for item in value)
            or len(set(value)) != len(value)):
        message = "Choose only supported agent tools, without duplicates."
        raise AiclError("validation_failed", message, field_errors={"tools": message})
    return sorted(value)


def web_search_enabled(snapshot):
    return snapshot.get("scenario") == "general" and "web_search" in normalize_tools(snapshot.get("tools", []))
