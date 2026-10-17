"""MagicLinkSender port, CaptureMagicLinkSender and SmtpMagicLinkSender (aicl-experience/technical.md
"SessionAuthProvider and magic-link sign-in", owner E11-3).

Contract stubs only. `CaptureMagicLinkSender` is the test-only fake (records `{email, link}` in memory);
`SmtpMagicLinkSender` is the application's one real outbound edge and is deliberately unimplemented here:
no network call, no credential. Neither is registered in PORT_REGISTRY/REQUIRED_PORTS; E11-3 does that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

NOT_IMPLEMENTED = "E11-3 behavior is not implemented (contract stub)"


class MagicLinkSender(Protocol):
    def send(self, email: str, link: str) -> None:
        """Deliver `link` to `email`. The plaintext address is held only for this call."""
        ...


@dataclass
class CaptureMagicLinkSender:
    """Test-only fake: installed only when AICL_TEST_MODE=1 AND AICL_ENVIRONMENT=test.

    Exposed by `GET /__test__/last-magic-link?email=` (route owned by E11-3, absent otherwise).
    """

    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, email: str, link: str) -> None:
        self.sent.append({"email": email, "link": link})

    def last_for(self, email: str) -> str | None:
        """Newest captured link for the normalized address, else None."""
        for item in reversed(self.sent):
            if item["email"] == email:
                return item["link"]
        return None


@dataclass(frozen=True)
class SmtpConfig:
    """AICL_SMTP_* settings (all empty by default; the password is read from the environment only)."""

    host: str
    port: int
    username: str = ""
    password: str = field(default="", repr=False)
    sender: str = ""


class SmtpMagicLinkSender:
    """Production sender over the operator-configured SMTP server (not Gmail, not a provider adapter).

    Delivery failure is silent to the requester and audited by the caller (the 202 body never changes).
    """

    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def send(self, email: str, link: str) -> None:
        import smtplib
        from email.message import EmailMessage
        message = EmailMessage()
        message["From"] = self.config.sender or self.config.username or "no-reply@localhost"
        message["To"] = email
        message["Subject"] = "Your sign-in link"
        message.set_content(f"Use this link to sign in (single use, expires soon):\n\n{link}\n")
        with smtplib.SMTP(self.config.host, self.config.port, timeout=10) as smtp:
            if self.config.username:
                smtp.starttls()
                smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)
