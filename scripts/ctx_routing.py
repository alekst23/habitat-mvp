"""Deterministic CTX response normalization. No network, shell, or approval authority."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys


TOKENS = frozenset({"ready", "blocked", "intake_done", "design", "tests", "implementation",
                    "browser", "integrate", "epic", "checkpoint", "more", "complete"})
MAX_RESPONSE_BYTES = 256 * 1024


class RoutingError(ValueError):
    """Unknown, malformed or ambiguous output must never select a success route."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RoutingError("duplicate JSON field")
        result[key] = value
    return result


def normalize_response(response, allowed):
    """Return a structured result; prose is information, never an instruction."""
    allowed = set(allowed)
    if not allowed or not allowed <= TOKENS:
        raise RoutingError("invalid routing allowlist")
    if not isinstance(response, str) or len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise RoutingError("invalid or oversized response")
    text = response.strip()
    if text.startswith("{"):
        try:
            result = json.loads(text, object_pairs_hook=unique_object)
        except ValueError as exc:
            raise RoutingError("invalid structured routing result") from exc
        if (not isinstance(result, dict) or "routing_token" not in result
                or set(result) - {"routing_token", "informational_output"}
                or not isinstance(result.get("informational_output", ""), str)):
            raise RoutingError("invalid structured routing fields")
        token = result["routing_token"]
        information = result.get("informational_output", "")
    else:
        lines = text.splitlines()
        if not lines:
            raise RoutingError("empty routing response")
        token = lines[-1].strip()
        information = "\n".join(lines[:-1]).rstrip()
        fence = None
        for line in lines[:-1]:
            line = line.strip()
            marker = re.match(r"^(`{3,}|~{3,})", line)
            if marker:
                if fence is None:
                    fence = marker[1][0]
                elif marker[1][0] == fence:
                    fence = None
            elif fence is None:
                if line in TOKENS and line != token:
                    raise RoutingError("conflicting standalone routing tokens")
                if re.search(r'["\']?routing_token["\']?\s*[:=]', line):
                    raise RoutingError("mixed structured and plain routing signals")
        if fence is not None:
            raise RoutingError("routing token inside an unclosed code fence")
    if not isinstance(token, str) or token not in allowed:
        raise RoutingError("unknown routing token for this component")
    return {"routing_token": token, "informational_output": information}


def response_path(component):
    if not re.fullmatch(r"[a-z][a-z_]*", component):
        raise RoutingError("invalid component identity")
    # Deliberately outside ignored .ctx/: GitLab's file tool rejects ignored paths.
    return Path(f"ctx-routing-{component}.input")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "normalize"))
    parser.add_argument("--component", required=True)
    parser.add_argument("--allowed", required=True)
    parser.add_argument("--token-only", action="store_true")
    args = parser.parse_args()
    try:
        path = response_path(args.component)
        if args.action == "prepare":
            # Never overwrite a pre-existing, stale, or symlinked scratch file.
            if os.path.lexists(path):
                raise RoutingError("routing scratch already exists; reconcile before resuming")
            sys.stdout.write("absent")
            return 0
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            identity = os.fstat(stream.fileno())
            if not stat.S_ISREG(identity.st_mode) or identity.st_size > MAX_RESPONSE_BYTES:
                raise RoutingError("invalid routing scratch file")
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
        result = normalize_response(raw.decode("utf-8"), args.allowed.split(","))
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise RoutingError("routing scratch changed during normalization")
        path.unlink()  # Only the exact, consumed scratch file; no recursive cleanup.
        # Native GitLab routes this field verbatim; no trailing newline or diagnostic text.
        sys.stdout.write(result["routing_token"] if args.token_only else json.dumps(result))
        return 0
    except (RoutingError, OSError, UnicodeError) as exc:
        print(f"CTX routing rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
