"""Persistent loopback preview with real PayPal Sandbox API calls and test money."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Mapping

import uvicorn

from aicl.app import create_app
from aicl.demo_server import REPO, demo_settings
from aicl.settings import Settings, SettingsError
from aicl.workflow.inference_config import add_inference_arguments, with_inference_settings, inference_startup_message

SANDBOX_KEYS = {
    "AICL_PAYPAL_CLIENT_ID": "paypal_client_id",
    "AICL_PAYPAL_CLIENT_SECRET": "paypal_client_secret",
    "AICL_PAYPAL_MERCHANT_ID": "paypal_merchant_id",
    "AICL_PAYPAL_PURCHASE_CLIENT_ID": "paypal_purchase_client_id",
    "AICL_PAYPAL_PURCHASE_CLIENT_SECRET": "paypal_purchase_client_secret",
    "AICL_PAYPAL_PURCHASE_MERCHANT_ID": "paypal_purchase_merchant_id",
}
FILE_KEYS = frozenset(SANDBOX_KEYS) | {"AICL_PAYMENT_MODE"}


def read_credentials_file(path: Path) -> dict[str, str]:
    """Read literal KEY=value lines; never source, interpolate, eval or execute them."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise SettingsError("--credentials-file", "must be at most 64 KiB")
        contents = raw.decode("utf-8")
    except (OSError, UnicodeError):
        raise SettingsError("--credentials-file", "could not read a UTF-8 credentials file") from None
    values: dict[str, str] = {}
    for number, line in enumerate(contents.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=\s*(.*)", line)
        if match is None or match.group(1) not in FILE_KEYS:
            raise SettingsError("--credentials-file", f"line {number} must set a supported Sandbox variable")
        name, value = match.groups()
        if name in values:
            raise SettingsError(name, "appears more than once in the credentials file")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise SettingsError(name, "must have matching quotes")
            value = value[1:-1]
        if any(char in value for char in ("$", "`", "\\", "\x00")):
            raise SettingsError(name, "must be a literal value without shell expressions or escapes")
        values[name] = value
    return values


def build_sandbox_settings(database: Path, port: int, credentials: Mapping[str, str]) -> Settings:
    """Reuse local preview defaults with explicit, fully validated payment settings."""
    if not 1024 <= port <= 65535:
        raise SettingsError("--port", "must be between 1024 and 65535")
    if credentials.get("AICL_PAYMENT_MODE", "paypal_sandbox") != "paypal_sandbox":
        raise SettingsError("AICL_PAYMENT_MODE", "the Sandbox launcher requires paypal_sandbox")
    values = demo_settings(database, port).model_dump()
    values.update({field: credentials.get(name, "") for name, field in SANDBOX_KEYS.items()})
    values.update(payment_mode="paypal_sandbox",
                  payment_api_url=credentials.get("AICL_MOCK_PAYMENT_API_URL", ""),
                  payment_token=credentials.get("AICL_MOCK_PAYMENT_TOKEN", ""))
    return Settings.model_validate(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Habitat locally with PayPal Sandbox checkout; test money only.")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--database", type=Path, default=REPO / ".ctx/paypal-sandbox/aicl.db")
    parser.add_argument("--credentials-file", type=Path,
                        help="literal Sandbox KEY=value file; overrides matching environment variables")
    parser.add_argument("--check-config", action="store_true",
                        help="validate configuration without opening a port or contacting PayPal")
    add_inference_arguments(parser)
    args = parser.parse_args()
    credentials = {name: os.environ[name] for name in FILE_KEYS | {
        "AICL_MOCK_PAYMENT_API_URL", "AICL_MOCK_PAYMENT_TOKEN"} if name in os.environ}
    try:
        if args.credentials_file:
            credentials.update(read_credentials_file(args.credentials_file))
        settings = with_inference_settings(build_sandbox_settings(args.database, args.port, credentials), args)
    except SettingsError as exc:
        parser.error(str(exc))
    if args.check_config:
        print("PayPal Sandbox configuration is valid. No API request or transaction was made.", flush=True)
        return
    app = create_app(settings)
    print(f"Habitat PayPal Sandbox: http://127.0.0.1:{args.port}", flush=True)
    print(f"Persistent Sandbox database: {args.database.resolve()}", flush=True)
    print("PayPal Sandbox credentials loaded. Test money only; no live-payment option.", flush=True)
    print(inference_startup_message(settings), flush=True)
    print("Compute execution and advertising delivery remain simulated.", flush=True)
    print("Local test keys and captured sign-in mail; do not expose this server publicly.", flush=True)
    print("Sign-in link: /__test__/last-magic-link?email=YOUR_EMAIL", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
