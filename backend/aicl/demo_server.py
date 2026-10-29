"""Persistent loopback demo with mock payments and optional bounded real inference."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

import uvicorn

from aicl.app import create_app
from aicl.commerce.local_payment_process import local_payment_process
from aicl.settings import Settings, SettingsError
from aicl.workflow.inference_config import add_inference_arguments, with_inference_settings, inference_startup_message

REPO = Path(__file__).resolve().parents[2]


def demo_settings(database: Path, port: int, *, payment_api_url: str = "", payment_token: str = "",
                  local_private_entry: bool = False, access_link_token: str = "") -> Settings:
    """Fixed test keys preserve demonstration identities across local restarts only."""
    return Settings.from_env({
        "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
        "AICL_LOCAL_PRIVATE_ENTRY": "1" if local_private_entry else "0",
        "AICL_ACCESS_LINK_TOKEN": access_link_token,
        "AICL_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "AICL_DATABASE_URL": f"sqlite:///{database.resolve()}",
        "AICL_PRICE_TABLE_PATH": str(REPO / "backend/aicl/price_table.example.json"),
        "AICL_SESSION_SECRET": "test-session-secret-" + "s" * 20,
        "AICL_IDENTITY_HMAC_KEY": "test-identity-hmac-key-" + "i" * 20,
        "AICL_SECRET_ENCRYPTION_KEY": base64.b64encode(bytes(range(32))).decode(),
        "AICL_MOCK_PAYMENT_API_URL": payment_api_url, "AICL_MOCK_PAYMENT_TOKEN": payment_token,
    })


def _private_entry_file(fd: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid() or info.st_nlink != 1):
        raise SettingsError("AICL_ACCESS_LINK_TOKEN", "local entry files must be owner-owned regular files with mode 0600")


def private_entry_files(database: Path, port: int) -> tuple[str, Path]:
    """Persist a local-only token and URL without printing either secret value."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise SettingsError("AICL_PUBLIC_BASE_URL", "local entry port must be between 1024 and 65535")
    database = database.resolve()
    token_file = database.with_name(database.name + ".private-access-token")
    url_file = database.with_name(database.name + ".private-access-url")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    temporary = None
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
        except FileExistsError:
            fd = os.open(token_file, os.O_RDONLY | nofollow | nonblock)
            with os.fdopen(fd, "r", encoding="ascii") as handle:
                _private_entry_file(handle.fileno())
                saved = handle.read(130)
            token = saved[:-1] if saved.endswith("\n") else saved
            if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) is None or token.startswith(("CHANGE_ME", "YOUR_")):
                raise SettingsError("AICL_ACCESS_LINK_TOKEN", "saved local entry token is malformed; replace its file deliberately")
        else:
            token = secrets.token_urlsafe(32)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(token + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        try:
            fd = os.open(url_file, os.O_RDONLY | nofollow | nonblock)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd, "r", encoding="ascii") as handle:
                _private_entry_file(handle.fileno())
        fd, temporary = tempfile.mkstemp(prefix="." + url_file.name + ".", dir=database.parent)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(f"http://127.0.0.1:{port}/auth/access?token={token}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, url_file)
        temporary = None
        return token, url_file
    except (OSError, UnicodeError):
        raise SettingsError("AICL_ACCESS_LINK_TOKEN", "cannot safely read or write owner-only local entry files") from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Habitat with local mock payments and optional GPT-6 Sol inference.")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--database", type=Path, default=REPO / ".ctx/mock-commerce/demo.db")
    parser.add_argument("--payment-port", type=int, default=4174)
    parser.add_argument("--entry", choices=("private-link", "email"), default="private-link",
                        help="private local link (default), or captured email sign-in for testing")
    add_inference_arguments(parser)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not 1024 <= args.payment_port <= 65535 or args.payment_port == args.port:
        parser.error("--payment-port must be between 1024 and 65535 and differ from --port")
    try:
        private_entry = args.entry == "private-link"
        access_token, access_url_file = private_entry_files(args.database, args.port) if private_entry else ("", None)
        settings = with_inference_settings(demo_settings(args.database, args.port,
            local_private_entry=private_entry, access_link_token=access_token), args)
    except SettingsError as exc:
        parser.error(str(exc))
    payment_database = args.database.with_name(args.database.stem + "-payments.db")
    with local_payment_process(payment_database, args.payment_port) as payments:
        settings = Settings.model_validate({**settings.model_dump(),
            "payment_api_url": payments.url, "payment_token": payments.token})
        app = create_app(settings)
        print(f"Habitat demo: http://127.0.0.1:{args.port}", flush=True)
        print(f"Persistent demo database: {args.database.resolve()}", flush=True)
        print(f"Mock payment API ready: {payments.url} (separate local process)", flush=True)
        print(f"Persistent mock payment database: {payments.database}", flush=True)
        print("Mock payments and seller. No real money or PayPal Sandbox calls.", flush=True)
        print(inference_startup_message(settings), flush=True)
        if private_entry:
            print(f"Private local access link file: {access_url_file}", flush=True)
            print("Private-link entry is enabled. No SMTP or test sign-in endpoints.", flush=True)
        else:
            print("Sign-in emails are captured locally; see /__test__/last-magic-link?email=YOUR_EMAIL", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", access_log=not private_entry)


if __name__ == "__main__":
    main()
