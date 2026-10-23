"""Own a separate loopback payment fixture process for the local demonstration."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
from threading import Thread
import time
import urllib.error
import urllib.request

from aicl.settings import validate_mock_payment_settings


@dataclass(frozen=True)
class LocalPaymentProcess:
    url: str
    database: Path
    token: str = field(repr=False)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _local_token(path: Path) -> str:
    """Create once; refuse symlinks, shared permissions and malformed existing files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | nofollow)
        with os.fdopen(fd, "r") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise RuntimeError("The local mock payment token must be an owner-only regular file")
            token = handle.read(1025).strip()
        validate_mock_payment_settings("test", "http://127.0.0.1:4174", token)
        return token
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(fd, "w") as handle:
            handle.write(token + "\n")
        return token


def _stop_owned_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@contextmanager
def local_payment_process(database: Path, port: int = 4174, *, startup_timeout: float = 10.0):
    """Start only our child, wait for readiness, and stop only that child on exit."""
    if not 1024 <= port <= 65535:
        raise ValueError("Mock payment port must be between 1024 and 65535")
    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    # Never silently attach to an existing process, even if it has a healthy API.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Mock payment port {port} is already in use; choose --payment-port") from None
    token = _local_token(database.parent / ".mock-payment-token")
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "AICL_MOCK_PAYMENT_TOKEN": token}
    backend = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (backend, env.get("PYTHONPATH", ""))))
    process = subprocess.Popen(
        [sys.executable, "-m", "aicl.commerce.payment_api", "--db", str(database), "--port", str(port)],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True,
    )
    stderr = deque(maxlen=12)

    def read_errors():
        assert process.stderr is not None
        for line in process.stderr:
            stderr.append(line[:512].replace(token, "[redacted]"))

    reader = Thread(target=read_errors, daemon=True)
    reader.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    deadline = time.monotonic() + startup_timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                reader.join(timeout=1)
                detail = "".join(stderr).strip()
                raise RuntimeError("Local mock payment API exited before readiness" + (f": {detail}" if detail else ""))
            ready = False
            try:
                with opener.open(url + "/health", timeout=0.3) as response:
                    ready = json.loads(response.read(1024)) == {"status": "ok", "mode": "http_mock"}
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                pass
            if ready and process.poll() is None:
                yield LocalPaymentProcess(url, database, token)
                return
            time.sleep(0.05)
        raise RuntimeError("Local mock payment API did not become ready before the startup timeout")
    finally:
        _stop_owned_process(process)
        reader.join(timeout=1)
        if process.stderr is not None:
            process.stderr.close()
