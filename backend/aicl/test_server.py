"""`python -m aicl.test_server`: create_app(test settings) plus test-only routes (E11-1)."""

from __future__ import annotations

import base64
import shutil
import tempfile
from pathlib import Path

import uvicorn

from aicl.app import create_app
from aicl.settings import Settings

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    """Serve on 127.0.0.1:4173 with a temporary database under .ctx/tmp/ (both test flags required)."""
    tmp_root = REPO / ".ctx" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="aicl-test-", dir=tmp_root))
    try:
        settings = Settings.from_env({
            "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
            "AICL_DATABASE_URL": f"sqlite:///{workdir / 'aicl.db'}",
            "AICL_PRICE_TABLE_PATH": str(REPO / "backend" / "aicl" / "price_table.example.json"),
            "AICL_SESSION_SECRET": "test-session-secret-" + "s" * 20,
            "AICL_IDENTITY_HMAC_KEY": "test-identity-hmac-key-" + "i" * 20,
            "AICL_SECRET_ENCRYPTION_KEY": base64.b64encode(bytes(range(32))).decode(),
        })
        uvicorn.run(create_app(settings), host="127.0.0.1", port=4173, log_level="warning")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
