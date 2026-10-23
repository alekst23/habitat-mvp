"""Owner-defined scope for a reviewed browser purchase-proposal workflow.

Configuration performs structural URL checks only. The browser transport must
still resolve and reject non-public addresses at every network connection.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from aicl.control.errors import AiclError

BROWSER_SCENARIO = "browser_purchase"
MAX_AMOUNT_MINOR = 1_000_000
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid", ".example")


def normalize_browser_task(value):
    if not isinstance(value, dict):
        raise AiclError("validation_failed", "Set a website, purchase objective and maximum amount for browser work.")
    raw = value.get("service_url")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
        raise AiclError("validation_failed", "Enter the public HTTPS website the agent should review.")
    raw = raw.strip()
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query or "?" in raw or parsed.fragment or "#" in raw or "\\" in raw
                or any(ord(char) < 33 for char in raw) or not host.isascii() or len(host) > 253
                or "." not in host or host.endswith(_LOCAL_SUFFIXES)
                or not all(_LABEL.fullmatch(label) for label in host.split("."))
                or not re.fullmatch(r"[a-z][a-z0-9-]*", host.rsplit(".", 1)[-1])):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise AiclError("validation_failed", "Use a public HTTPS hostname on port 443, without login credentials, query parameters or a fragment.")
    objective = value.get("objective")
    if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 2000:
        raise AiclError("validation_failed", "Describe the proposed purchase in 1–2000 characters.")
    amount = value.get("max_amount_minor")
    if type(amount) is not int or not 1 <= amount <= MAX_AMOUNT_MINOR:
        raise AiclError("validation_failed", "The maximum purchase amount must be between $0.01 and $10,000.00.")
    if value.get("currency", "USD") != "USD":
        raise AiclError("validation_failed", "Browser purchase proposals currently use USD.")
    return {"service_url": urlunsplit(("https", host, parsed.path or "/", parsed.query, "")),
            "objective": objective.strip(), "max_amount_minor": amount, "currency": "USD"}


def browser_purchase_preset():
    """An editable starting brief, not a service integration or spending grant."""
    return {"scenario": BROWSER_SCENARIO,
            "goal": "Prepare an advertising purchase proposal for my mobile game. Ask for sign-in when needed and stop before checkout.",
            "inputs": "Add your game's name, store listing, audience and campaign constraints here. The website is a starting point; this workflow does not publish ads.",
            "cadence": "daily", "timezone": "America/New_York",
            "browser_task": {"service_url": "https://ads.snapchat.com/",
                             "objective": "Review a small mobile-game advertising test and prepare a purchase request with observed account details, rationale, scope and budget.",
                             "max_amount_minor": 2500, "currency": "USD"},
            "deliverables": [{"key": "purchase_proposal", "name": "Advertising purchase proposal",
                              "description": "A bounded proposal linked to the website evidence and the job that prepared it.",
                              "criteria": ["Identify the website and account information actually observed",
                                           "Explain the proposed campaign and why it supports the goal",
                                           "State the proposed amount within the owner's cap and disclose unverified details",
                                           "Confirm no checkout, payment or ad publication has occurred"],
                              "purchase_required": False, "validation_scenario": "pass"}]}
