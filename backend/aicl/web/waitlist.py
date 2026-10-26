"""Anonymous signup to an operator-owned private Google Sheet via Apps Script.

Only the server knows the shared secret. No signup creates an owner/session or
stores the address locally. Google handles deduplication under a script lock.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from aicl.web.pages import render


def normalize_email(value: str) -> str | None:
    email = value.strip().lower()
    if not email.isascii() or len(email) > 254 or email.count("@") != 1:
        return None
    local, domain = email.split("@")
    if (not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".") or ".." in local
            or re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) is None):
        return None
    labels = domain.split(".")
    if len(labels) < 2 or any(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels):
        return None
    return email


def google_client() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False)


def save_to_google(settings, email: str) -> bool:
    """Accept only a positive application receipt; never forward POST secrets on redirects."""
    try:
        with google_client() as client:
            response = client.post(settings.waitlist_webhook_url, json={
                "token": settings.waitlist_webhook_token.get_secret_value(), "email": email})
            if response.status_code in (302, 303):
                location = response.headers.get("location", "")
                target = urlsplit(location)
                # Apps Script ContentService uses a one-time Google-hosted GET receipt.
                if (target.scheme != "https" or target.netloc != "script.googleusercontent.com"
                        or target.path != "/macros/echo" or target.fragment
                        or "\\" in location or any(c.isspace() or ord(c) < 32 for c in location)):
                    return False
                response = client.get(location)
            if response.status_code != 200:
                return False
            receipt = response.json()
            return isinstance(receipt, dict) and receipt.get("ok") is True
    except (httpx.HTTPError, ValueError):
        # Provider bodies/exception strings may contain emails or secrets.
        return False


def reserve_attempt(ctx, email: str, client_ip: str) -> bool:
    """Per-email, per-IP and total hourly caps, shared across app workers/restarts."""
    key = ctx.settings.identity_hmac_key.encode()

    def digest(kind, value):
        return hmac.new(key, f"waitlist:{kind}:{value}".encode(), hashlib.sha256).hexdigest()

    window = int(ctx.clock.now().timestamp()) // 3600 * 3600
    limits = ((digest("email", email), 5), (digest("ip", client_ip), 20), ("total", 100))
    with ctx.db.transaction() as conn:
        conn.execute("DELETE FROM waitlist_rate_limit WHERE window_start < ?", (window - 3600,))
        for bucket, limit in limits:
            row = conn.execute("SELECT count FROM waitlist_rate_limit WHERE bucket = ? AND window_start = ?",
                               (bucket, window)).fetchone()
            if row and row["count"] >= limit:
                return False
        for bucket, _ in limits:
            conn.execute("INSERT INTO waitlist_rate_limit (bucket, window_start, count) VALUES (?, ?, 1) "
                         "ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + 1", (bucket, window))
    return True


def waitlist_router(ctx) -> APIRouter:
    router = APIRouter()

    def page(status=200, *, error="", email="", success=False):
        return HTMLResponse(render("waitlist", title="Waitlist", waitlist_enabled=ctx.settings.waitlist_enabled,
                                   waitlist_success=success, waitlist_error=error, waitlist_email=email),
                            status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"})

    @router.get("/waitlist", response_class=HTMLResponse)
    def signup_page():
        return page(200 if ctx.settings.waitlist_enabled else 503)

    @router.post("/waitlist", response_class=HTMLResponse)
    async def signup(request: Request):
        if not ctx.settings.waitlist_enabled:
            return page(503)
        if (request.headers.get("origin") != ctx.settings.public_base_url.rstrip("/")
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return page(403, error="Please open the waitlist on this site and try again.")
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
            return page(415, error="Please use the waitlist form to sign up.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2048:
                return page(413, error="That submission is too long. Please enter just your email.")
        try:
            form = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=4)
        except (ValueError, UnicodeError):
            return page(422, error="Please enter a valid email address.")
        if form.get("website", [""])[0]:
            return page(success=True)  # Discard bot-filled honeypots without contacting Google.
        emails = form.get("email", [])
        email = normalize_email(emails[0]) if len(emails) == 1 else None
        if email is None:
            return page(422, error="Please enter a valid email address.", email=emails[0][:254] if emails else "")
        allowed = await run_in_threadpool(reserve_attempt, ctx, email, request.client.host if request.client else "unknown")
        if not allowed:
            response = page(429, error="Too many attempts. Please try again in an hour.", email=email)
            response.headers["Retry-After"] = "3600"
            return response
        saved = await run_in_threadpool(save_to_google, ctx.settings, email)
        if not saved:
            return page(503, error="We couldn’t confirm your signup. Please try again in a moment.", email=email)
        return page(success=True)

    return router
