"""File-to-note native checkpoint transport; no model transcription or dispatch.

Run only from reviewed coordinator source inside the existing GitLab flow. Uses
its injected OAuth credential in memory, never a human/controller token or CLI
credential store. All remote writes are new notes on the pinned Showcase issue.
Local intent receipts prevent blind POST retries; they are not distributed locks.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import ctx_development as dev
import ctx_owner as owner

API = "https://gitlab.com/api/v4"
BASE = "https://gitlab.com/" + owner.closure.PROJECT
WRITER_ID = 43132375  # Verified CTX Development service account, not the human user.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_BODY_BYTES = 512 * 1024


class CheckpointError(ValueError):
    """Safe, fixed diagnostic text (never remote body or credential data)."""


def require(condition, message):
    if not condition:
        raise CheckpointError(message)


class TransportError(CheckpointError):
    def __init__(self, code):
        super().__init__(f"checkpoint transport {code}; reconcile before another write")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_path(source):
    require(type(source) is int and source > 0, "invalid source issue")
    return f"/projects/{owner.PROJECT_ID}/issues/{source}/notes"


class GitLabNotes:
    def __init__(self, token):
        require(isinstance(token, str) and token and not any(c.isspace() for c in token),
                "missing flow OAuth credential")
        self._token = token
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env
        require(env.get("CI_PROJECT_ID") == str(owner.PROJECT_ID), "requires the Showcase flow runtime")
        for key, expected in (("GITLAB_BASE_URL", "https://gitlab.com"),
                              ("CI_SERVER_URL", "https://gitlab.com"), ("CI_API_V4_URL", API)):
            require(key not in env or env[key].rstrip("/") == expected, "unexpected GitLab runtime origin")
        tokens = [env[k] for k in ("GITLAB_TOKEN", "GITLAB_OAUTH_TOKEN") if env.get(k)]
        require(tokens and len(set(tokens)) == 1, "missing or conflicting injected flow OAuth credentials")
        return cls(tokens[0])

    def _request(self, method, path, data=None):
        # Internal callers alone construct paths; no generic URL/method/token CLI.
        require((method == "GET" and path == "/user") or
                re.fullmatch(rf"/projects/{owner.PROJECT_ID}/issues/[1-9][0-9]*/notes"
                             r"(?:/[1-9][0-9]*|\?per_page=100&page=[1-9][0-9]*&order_by=created_at&sort=asc)?", path)
                and method in {"GET", "POST"}, "unsupported checkpoint endpoint")
        require(method != "POST" or (path.endswith("/notes") and isinstance(data, dict)
                and set(data) == {"body"} and isinstance(data["body"], str)), "unsupported checkpoint write")
        require(data is None or self._token not in data["body"], "credential detected in checkpoint")
        request = Request(API + path, method=method,
                          data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
                          headers={"Authorization": "Bearer " + self._token,
                                   "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                require(len(raw) <= MAX_RESPONSE_BYTES, "response too large")
                return json.loads(raw, object_pairs_hook=dev.unique_object), response.headers
        except HTTPError as exc:
            raise TransportError(f"HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise TransportError("unknown outcome") from None
        except (ValueError, UnicodeError):
            # Never echo response bodies, headers, payloads or credential values.
            raise TransportError("invalid or oversized response") from None

    def authenticate(self):
        user, _ = self._request("GET", "/user")
        require(isinstance(user, dict) and user.get("id") == WRITER_ID,
                "requires the registered CTX Development service account, not a personal credential")
        return user["id"]

    @staticmethod
    def normalize(source, value):
        require(isinstance(value, dict) and type(value.get("id")) is int and value["id"] > 0 and
                isinstance(value.get("body"), str) and isinstance(value.get("author"), dict) and
                type(value["author"].get("id")) is int and value["author"]["id"] > 0,
                "incomplete server note response")
        return {"id": value["id"], "author_id": value["author"]["id"], "body": value["body"],
                "url": BASE + f"/-/issues/{source}#note_{value['id']}"}

    def notes(self, source):
        notes = []
        for page in range(1, 101):
            values, headers = self._request("GET", source_path(source) +
                                           f"?per_page=100&page={page}&order_by=created_at&sort=asc")
            require(isinstance(values, list), "note page is not a list")
            notes.extend(self.normalize(source, value) for value in values)
            next_page = headers.get("X-Next-Page")
            if next_page == "" or (next_page is None and len(values) < 100):
                return notes
            require(next_page == str(page + 1), "incomplete or unexpected note pagination")
        raise CheckpointError("note pagination limit; no partial checkpoint selection")

    def get(self, source, note_id):
        require(type(note_id) is int and note_id > 0, "invalid checkpoint note ID")
        value, _ = self._request("GET", source_path(source) + f"/{note_id}")
        return self.normalize(source, value)

    def create(self, source, body):
        value, _ = self._request("POST", source_path(source), {"body": body})
        return self.normalize(source, value)


def select(api, source, epic, legacy_note_ids=None):
    notes = api.notes(source)
    result = owner.select(notes, source_issue_iid=source, epic=epic,
                          trusted_author_ids=[WRITER_ID], legacy_note_ids=legacy_note_ids)
    return notes, result


def note_id(url):
    return int(url.rsplit("#note_", 1)[1])


def assemble(value, *, journal=None, closure_record=None, updates=None):
    """Splice generated records into a loaded checkpoint, never recopy its history."""
    owner.validate(value)
    updates = {} if updates is None else updates
    require(isinstance(updates, dict) and set(updates) <= {
        "session", "decisions", "resources_append", "closure_returns_append"}, "unsupported checkpoint update")
    result = deepcopy(value)
    for key, replacement in (("journal", journal), ("closure", closure_record)):
        if replacement is not None:
            result[key] = deepcopy(replacement)
    for key in ("session", "decisions"):
        if key in updates:
            result[key] = deepcopy(updates[key])
    for key in ("resources", "closure_returns"):
        addition = updates.get(key + "_append", [])
        require(isinstance(addition, list), "checkpoint additions must be lists")
        result[key].extend(deepcopy(addition))
    owner.validate(result)
    owner.validate_continuation(value, result)
    return result


def download(api, source, epic, output, legacy_note_ids=None):
    require(api.authenticate() == WRITER_ID, "unexpected checkpoint writer")
    notes, result = select(api, source, epic, legacy_note_ids)
    require(result["action"] == "resume", "no complete checkpoint; reconcile legacy evidence, do not reset")
    output = Path(output)
    require(not output.exists(), "download destination already exists; preserve local work")
    output.mkdir(mode=0o700, parents=True)
    for name, value in (("notes.json", notes), ("handoff.json", result["handoff"]),
                        ("closure.json", result["handoff"]["closure"]),
                        ("journal.json", result["handoff"]["journal"])):
        dev.save_json(output / name, value)
    return {"action": "downloaded", "source_note_id": note_id(result["source_url"]),
            "source_url": result["source_url"], "output_dir": str(output),
            "excluded_notes": result["excluded_notes"], "next": result["next"]}


def publish(api, value, summary, *, previous_note_id, receipt_path, initial=False, legacy_note_ids=None):
    owner.validate(value)
    require(isinstance(summary, str) and summary.strip() and len(summary.split()) <= 120 and
            len(summary.encode("utf-8")) <= 4096 and not owner.marker_lines(summary) and
            "```" not in summary and "~~~" not in summary and "@" not in summary and
            not re.search(r"(?m)^\s*/[A-Za-z]", summary),
            "use a short plain status summary without state JSON, mentions or quick actions")
    body = summary.strip() + "\n\n" + owner.render(value)
    require(len(body.encode("utf-8")) <= MAX_BODY_BYTES, "checkpoint exceeds transport limit; never truncate")
    require(api.authenticate() == WRITER_ID, "unexpected checkpoint writer")
    objective = value["objective"]
    source, epic = objective["source_issue_iid"], objective["epic"]
    require((initial and previous_note_id is None) or
            (not initial and type(previous_note_id) is int and previous_note_id > 0),
            "choose the verified previous note or explicit initial publication")
    intent = {"version": 1, "project_id": owner.PROJECT_ID, "source_issue_iid": source,
              "epic": epic, "run_id": objective["run_id"], "session_id": value["session"]["session_id"],
              "previous_note_id": previous_note_id, "body_sha256": digest(body)}
    receipt_path = Path(receipt_path)
    prior_receipt = dev.read_json(receipt_path) if receipt_path.exists() else None
    require(prior_receipt is None or prior_receipt.get("intent") == intent,
            "receipt belongs to another publication; retain it")
    notes, selected = select(api, source, epic, legacy_note_ids)
    matches = [n for n in notes if n["author_id"] == WRITER_ID and n["body"] == body]
    require(len(matches) <= 1, "duplicate checkpoint publications; reconcile ownership")

    if matches:
        published = matches[0]
        require(selected["action"] == "resume" and note_id(selected["source_url"]) == published["id"],
                "checkpoint is no longer current; read the successor before acting")
    else:
        # Any durable local intent means the previous POST may have happened. No
        # automatic retry, including when the API cannot yet find the saved note.
        require(prior_receipt is None, "publication unverified; reconcile the existing attempt without reposting")
        if initial:
            require(selected["action"] == "reconcile_legacy", "initial publication cannot replace a checkpoint")
        else:
            require(selected["action"] == "resume" and note_id(selected["source_url"]) == previous_note_id,
                    "stale or missing parent checkpoint; reconcile before publication")
            owner.validate_continuation(selected["handoff"], value)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation closes the local double-POST window. This does not
        # establish exclusive remote coordination or a cross-session lease.
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump({"intent": intent, "state": "publication_unknown"}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        published = api.create(source, body)  # Exactly one POST; no network retry.
        dev.save_json(receipt_path, {"intent": intent, "state": "readback_pending", "note_id": published["id"]})

    saved = api.get(source, published["id"])
    require(saved["id"] == published["id"] and saved["url"] == BASE + f"/-/issues/{source}#note_{saved['id']}"
            and saved["author_id"] == WRITER_ID and saved["body"] == body,
            "checkpoint exact readback failed; no dispatch or repeated write")
    require(owner.parse(saved["body"]) == value, "checkpoint payload equality failed")
    # A second listing catches an intervening newer checkpoint and validates the
    # saved note against the complete retained history. It is not an atomic lock.
    _, current = select(api, source, epic, legacy_note_ids)
    require(current["action"] == "resume" and current["source_url"] == saved["url"] and
            current["handoff"] == value, "checkpoint superseded or inconsistent; reconcile before dispatch")
    receipt = {"intent": intent, "state": "verified", "verified": True,
               "note_id": saved["id"], "note_url": saved["url"], "body_sha256": digest(saved["body"]),
               "excluded_notes": current["excluded_notes"]}
    dev.save_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("assemble")
    build.add_argument("input", type=Path)
    build.add_argument("--journal-file", type=Path)
    build.add_argument("--closure-file", type=Path)
    build.add_argument("--updates-file", type=Path)
    build.add_argument("--output", type=Path, required=True)
    read = commands.add_parser("read")
    read.add_argument("--source-issue", type=int, required=True)
    read.add_argument("--epic", required=True)
    read.add_argument("--output-dir", type=Path, required=True)
    send = commands.add_parser("publish")
    send.add_argument("input", type=Path)
    send.add_argument("--summary-file", type=Path, required=True)
    parent = send.add_mutually_exclusive_group(required=True)
    parent.add_argument("--previous-note-id", type=int)
    parent.add_argument("--initial", action="store_true")
    send.add_argument("--receipt-file", type=Path, required=True)
    for command in (read, send):
        command.add_argument("--legacy-note-id", type=int, action="append", dest="legacy_note_ids")
    args = parser.parse_args()
    try:
        if args.command == "assemble":
            value = assemble(dev.read_json(args.input),
                             journal=dev.read_json(args.journal_file) if args.journal_file else None,
                             closure_record=dev.read_json(args.closure_file) if args.closure_file else None,
                             updates=dev.read_json(args.updates_file) if args.updates_file else None)
            require(not args.output.exists(), "assembled destination exists; preserve local work")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            dev.save_json(args.output, value)
            result = {"action": "assembled", "output": str(args.output),
                      "payload_sha256": digest(owner.render(value))}
        elif args.command == "read":
            api = GitLabNotes.from_environment()
            result = download(api, args.source_issue, args.epic, args.output_dir, args.legacy_note_ids)
        else:
            api = GitLabNotes.from_environment()
            result = publish(api, dev.read_json(args.input), args.summary_file.read_text(encoding="utf-8"),
                             previous_note_id=args.previous_note_id, receipt_path=args.receipt_file,
                             initial=args.initial, legacy_note_ids=args.legacy_note_ids)
        print(json.dumps(result))  # Small receipt only, never the full payload/token.
        return 0
    except (ValueError, OSError, TypeError, KeyError, IndexError, AttributeError) as exc:
        # OSError filenames and parser details may contain private local content.
        message = str(exc) if isinstance(exc, CheckpointError) else "checkpoint consistency/file validation failed; retain files and use the owner codec to reconcile"
        print(json.dumps({"action": "blocked", "verified": False, "reason": message}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
