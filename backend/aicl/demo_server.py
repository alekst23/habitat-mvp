"""Persistent loopback demo with mock payments and optional bounded real inference."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

import uvicorn

from aicl.app import create_app
from aicl.commerce.local_payment_process import local_payment_process
from aicl.settings import Settings, SettingsError
from aicl.workflow.inference_config import add_inference_arguments, with_inference_settings, inference_startup_message

REPO = Path(__file__).resolve().parents[2]


def demo_settings(database: Path, port: int, *, payment_api_url: str = "", payment_token: str = "") -> Settings:
    """Fixed test keys preserve demonstration identities across local restarts only."""
    return Settings.from_env({
        "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
        "AICL_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "AICL_DATABASE_URL": f"sqlite:///{database.resolve()}",
        "AICL_PRICE_TABLE_PATH": str(REPO / "backend/aicl/price_table.example.json"),
        "AICL_SESSION_SECRET": "test-session-secret-" + "s" * 20,
        "AICL_IDENTITY_HMAC_KEY": "test-identity-hmac-key-" + "i" * 20,
        "AICL_SECRET_ENCRYPTION_KEY": base64.b64encode(bytes(range(32))).decode(),
        "AICL_MOCK_PAYMENT_API_URL": payment_api_url, "AICL_MOCK_PAYMENT_TOKEN": payment_token,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Habitat with local mock payments and optional GPT-6 Sol inference.")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--database", type=Path, default=REPO / ".ctx/mock-commerce/demo.db")
    parser.add_argument("--payment-port", type=int, default=4174)
    add_inference_arguments(parser)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not 1024 <= args.payment_port <= 65535 or args.payment_port == args.port:
        parser.error("--payment-port must be between 1024 and 65535 and differ from --port")
    try:
        settings = with_inference_settings(demo_settings(args.database, args.port), args)
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
        print("Sign-in emails are captured locally; see /__test__/last-magic-link?email=YOUR_EMAIL", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
