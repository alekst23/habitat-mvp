"""Launch the public-only research worker under externally enforced isolation.

Docker is an operator-controlled broker dependency, never exposed to agents.
Each worker is inspected before start, has no mounts or inherited credentials,
and receives released public data over stdin. A readiness flag cannot substitute
for this launch. The application/model worker is not thereby claimed isolated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

from aicl.control.errors import AiclError
from aicl.network import research_worker_program


class DockerResearchWorker:
    def __init__(self, image_id: str):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("Research workers require an immutable local image ID")
        self.image_id = image_id
        self.program = Path(research_worker_program.__file__).read_text()

    @staticmethod
    def _command(arguments, *, data=None, timeout=15):
        command = ["docker", *arguments]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        # The worker is contained but remains an untrusted producer. Bound both
        # output streams while reading, rather than after communicate() allocates
        # arbitrary output in the credential-bearing broker process.
        limit, deadline = 2_000_000, time.monotonic() + timeout
        incoming = (data or "").encode("utf-8")
        sent, size = 0, 0
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                if incoming:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                else:
                    process.stdin.close()
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    for key, _ in selector.select(min(remaining, 0.25)):
                        try:
                            if key.data == "stdin":
                                try:
                                    sent += os.write(key.fd, incoming[sent:sent + 65536])
                                except BrokenPipeError:
                                    sent = len(incoming)
                                if sent == len(incoming):
                                    selector.unregister(key.fileobj)
                                    key.fileobj.close()
                            else:
                                chunk = os.read(key.fd, 65536)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                    key.fileobj.close()
                                    continue
                                size += len(chunk)
                                if size > limit:
                                    raise OSError("Research supervisor output exceeded its limit")
                                buffers[key.data].extend(chunk)
                        except BlockingIOError:
                            continue
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            stdout, stderr = (buffers[name].decode("utf-8", errors="replace") for name in ("stdout", "stderr"))
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            if process.poll() is None:
                process.kill()
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()
            process.wait(timeout=3)

    @staticmethod
    def _verify_container(value):
        host, config = value.get("HostConfig", {}), value.get("Config", {})
        valid = (host.get("NetworkMode") == "none" and host.get("ReadonlyRootfs") is True
                 and host.get("Privileged") is False and host.get("CapDrop") == ["ALL"]
                 and host.get("CapAdd") in (None, []) and not host.get("Binds")
                 and not value.get("Mounts") and not host.get("Devices")
                 and not host.get("DeviceRequests") and not host.get("VolumesFrom")
                 and host.get("PidMode", "") != "host" and host.get("IpcMode", "") != "host"
                 and host.get("UTSMode", "") != "host" and host.get("UsernsMode", "") != "host"
                 and host.get("LogConfig", {}).get("Type") == "none"
                 and config.get("User") == "65534:65534"
                 and "no-new-privileges" in host.get("SecurityOpt", [])
                 and config.get("Entrypoint") == ["python"]
                 and host.get("PidsLimit") == 16 and 0 < host.get("Memory", 0) <= 100_663_296)
        environment = config.get("Env", [])
        if not valid or any(any(word in entry.split("=", 1)[0].upper() for word in
                                ("TOKEN", "SECRET", "API_KEY", "CREDENTIAL")) for entry in environment):
            raise AiclError("unavailable", "The research worker isolation could not be verified.",
                            reason="worker_containment_unverified")

    def execute(self, payload, *, timeout_seconds=30):
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(encoded.encode()) > research_worker_program.MAX_INPUT_BYTES:
            raise AiclError("denied", "The public research input is too large.", reason="response_limit")
        container_id = None
        deadline = time.monotonic() + timeout_seconds
        def bounded(arguments, *, data=None):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Research worker deadline expired")
            return self._command(arguments, data=data, timeout=min(remaining, 30))
        try:
            created = bounded(["create", "--pull=never", "--network=none", "--read-only", "--log-driver=none",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534",
                "--pids-limit=16", "--memory=96m", "--cpus=0.5", "--interactive",
                "--entrypoint=python", self.image_id, "-I", "-c", self.program])
            container_id = created.stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{64}", container_id):
                raise ValueError("Unexpected container identity")
            observed = json.loads(bounded(["inspect", container_id]).stdout)[0]
            if observed.get("Image") != self.image_id:
                raise ValueError("The worker image changed")
            self._verify_container(observed)
            result = bounded(["start", "--attach", "--interactive", container_id], data=encoded)
            if len(result.stdout) > 250_000:
                raise ValueError("Worker response too large")
            return json.loads(result.stdout)
        except AiclError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
            raise AiclError("unavailable", "The isolated research worker is unavailable.",
                            reason="worker_containment_unverified") from None
        finally:
            if container_id and re.fullmatch(r"[0-9a-f]{64}", container_id):
                try:
                    self._command(["rm", "--force", container_id], timeout=3)
                except (OSError, subprocess.SubprocessError):
                    pass

    def check(self):
        result = self.execute({"action": "verify"})
        expected = {"non_root", "no_provider_environment", "read_only_root", "ipv4_egress_denied",
                    "ipv6_egress_denied", "public_dns_transport_denied", "no_linux_capabilities", "no_new_privileges"}
        return (isinstance(result, dict) and set(result) == {"checks"}
                and set(result["checks"]) == expected and all(v is True for v in result["checks"].values()))


class FixtureResearchWorker:
    """Offline test seam; the broker rejects it without a MockTransport."""

    def execute(self, payload, *, timeout_seconds=30):
        try:
            return research_worker_program.process(payload)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AiclError("unavailable", "The public response could not be parsed.",
                            reason="response_invalid") from None
