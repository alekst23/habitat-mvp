"""Authenticated transport to the private browser runtime; no upstream error bodies."""
from urllib.parse import quote

import httpx

from aicl.control.errors import AiclError


class BrowserClient:
    def __init__(self, base_url, token, *, transport=None):
        self.base_url, self.token, self.transport = base_url.rstrip("/"), token, transport

    def _call(self, method, path, payload=None, *, missing_ok=False):
        try:
            with httpx.Client(base_url=self.base_url, timeout=70, follow_redirects=False,
                              trust_env=False, transport=self.transport,
                              headers={"Authorization": "Bearer " + self.token}) as client:
                response = client.request(method, path, json=payload)
                if response.status_code == 404 and missing_ok:
                    return {}
                if response.status_code == 404:
                    raise AiclError("unavailable", "The browser session has ended. Open a new sign-in session.")
                if response.status_code >= 300 or len(response.content) > 5_000_000:
                    raise AiclError("unavailable", "The private browser service could not complete this operation.")
                result = response.json() if response.content else {}
                if not isinstance(result, dict):
                    raise ValueError("invalid response")
                return result
        except (httpx.HTTPError, ValueError):
            # Runtime URLs, HTML, cookies and transport errors can contain login material.
            raise AiclError("unavailable", "The private browser service is unavailable. Your request remains pending.") from None

    def create(self, **payload):
        return self._call("POST", "/sessions", payload)

    def frame(self, session_id):
        return self._call("GET", "/sessions/" + quote(session_id, safe="") + "/frame")

    def input(self, session_id, payload):
        return self._call("POST", "/sessions/" + quote(session_id, safe="") + "/input", payload)

    def snapshot(self, session_id):
        return self._call("POST", "/sessions/" + quote(session_id, safe="") + "/snapshot", {})

    def page(self, session_id):
        return self._call("GET", "/sessions/" + quote(session_id, safe="") + "/page")

    def close(self, session_id):
        return self._call("DELETE", "/sessions/" + quote(session_id, safe=""), missing_ok=True)

    def cancel_key(self, idempotency_key):
        # Unlike an unknown session ID, an unknown key must be tombstoned by the
        # runtime. A 404 here is not proof that a late create cannot still finish.
        return self._call("DELETE", "/session-keys/" + quote(idempotency_key, safe=""))
