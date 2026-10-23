"""Small, non-redirecting client for AICL's restricted machine API.

Never log headers, response bodies, saved inputs or exception strings from an
HTTP library. Neither this package nor its Render service needs database access,
an owner session, a model key, or PayPal credentials.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

import httpx


class MachineAPIError(RuntimeError):
    """A deliberately redacted transport/protocol error."""


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid machine resource identifier")
    return value


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    token: str = field(repr=False)

    def __post_init__(self):
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
            clean = (parsed.scheme in ("http", "https") and parsed.hostname
                     and not parsed.username and not parsed.password
                     and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                     and not any(c.isspace() or ord(c) < 32 for c in self.base_url)
                     and "\\" not in self.base_url and (port is None or 1 <= port <= 65535))
        except ValueError:
            clean = False
        if not clean:
            raise ValueError("AICL machine API requires a clean http(s) origin")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            # Render's private service hostnames are single-label names. Public
            # hosts must use HTTPS; private HTTP must be selected explicitly.
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,100}", parsed.hostname):
                raise ValueError("AICL machine API requires HTTPS outside local or Render private hosts")
        if (not isinstance(self.token, str) or not 32 <= len(self.token) <= 1024
                or not self.token.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in self.token)):
            raise ValueError("AICL machine token must have 32–1024 ASCII characters without whitespace")

    @classmethod
    def from_env(cls, role: str, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        if role not in ("worker", "scheduler"):
            raise ValueError("unknown machine role")
        base_url = env.get("AICL_API_URL", "")
        if not base_url:
            hostport = env.get("AICL_INTERNAL_HOSTPORT", "")
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,100}:[1-9][0-9]{0,4}", hostport):
                raise ValueError("Set AICL_API_URL or the Render private AICL_INTERNAL_HOSTPORT")
            base_url = "http://" + hostport
        return cls(base_url.rstrip("/"), env.get("AICL_" + role.upper() + "_TOKEN", ""))


class AICLClient:
    def __init__(self, config: ClientConfig, *, transport=None):
        self._http = httpx.Client(base_url=config.base_url, timeout=90,
                                  headers={"Authorization": "Bearer " + config.token},
                                  follow_redirects=False, trust_env=False, transport=transport)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _post(self, path, payload):
        try:
            response = self._http.post("/internal/render/" + path, json=payload)
        except httpx.HTTPError:
            raise MachineAPIError("AICL machine request outcome is unknown") from None
        if response.status_code != 200:
            raise MachineAPIError(f"AICL machine request returned HTTP {response.status_code}")
        if len(response.content) > 2_000_000:
            raise MachineAPIError("AICL machine response exceeded its bound")
        try:
            result = response.json()
        except ValueError:
            raise MachineAPIError("AICL machine response was not JSON") from None
        if not isinstance(result, dict):
            raise MachineAPIError("AICL machine response was not an object")
        return result

    def dispatch(self):
        return self._post("dispatch", {})

    def submitted(self, dispatch_id, task_run_id):
        return self._post(f"dispatch/{identifier(dispatch_id)}/submitted", {"task_run_id": identifier(task_run_id)})

    def uncertain(self, dispatch_id):
        return self._post(f"dispatch/{identifier(dispatch_id)}/uncertain", {})

    def claim(self, dispatch_id, task_run_id):
        return self._post(f"jobs/{identifier(dispatch_id)}/claim", {"task_run_id": identifier(task_run_id)})

    def generate(self, dispatch_id, task_run_id, attempt_id):
        return self._post(f"jobs/{identifier(dispatch_id)}/generate", {
            "task_run_id": identifier(task_run_id), "attempt_id": identifier(attempt_id)})

    def browser_prepare(self, dispatch_id, task_run_id, attempt_id):
        """Prepare reviewed browsing or persist an owner wait, without credentials."""
        return self._post(f"jobs/{identifier(dispatch_id)}/browser/prepare", {
            "task_run_id": identifier(task_run_id), "attempt_id": identifier(attempt_id)})

    def complete_attempt(self, dispatch_id, task_run_id, attempt_id, validation):
        return self._post(f"jobs/{identifier(dispatch_id)}/complete-attempt", {
            "task_run_id": identifier(task_run_id), "attempt_id": identifier(attempt_id), "validation": validation})

    def request_owner(self, dispatch_id, task_run_id, workflow_run_id, *, kind, title, reason, details=None, dedupe_key):
        return self._post(f"jobs/{identifier(dispatch_id)}/owner-request", {
            "task_run_id": identifier(task_run_id), "workflow_run_id": identifier(workflow_run_id),
            "kind": kind, "title": title, "reason": reason, "details": details or {}, "dedupe_key": dedupe_key})

    def browser_page(self, dispatch_id, task_run_id, workflow_run_id, request_id, url):
        """Read one authorized page. No browser credentials enter this worker."""
        return self._post(f"jobs/{identifier(dispatch_id)}/browser/page", {
            "task_run_id": identifier(task_run_id), "workflow_run_id": identifier(workflow_run_id),
            "request_id": identifier(request_id), "url": url})

    def finish(self, dispatch_id, task_run_id):
        return self._post(f"jobs/{identifier(dispatch_id)}/finish", {"task_run_id": identifier(task_run_id)})
