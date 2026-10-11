"""GitLab.com transport and protected-state store for the CTX controller.

No credential is passed to a Duo goal, repository file, artifact, or subprocess.
HTTP redirects are refused. Errors omit response bodies and credentials.
"""
import argparse
import base64
import json
import os
import re
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ctx_execution import (Controller, PROJECT_ID, PROJECT_PATH, application_base, canonical, digest,
                           integer, new_run, next_step, require, resume_run, sha, unique_object)

API = "https://gitlab.com/api/v4"
STATE_BRANCH = "ctx/controller-state"
MAX_BYTES = 2_000_000


class APIError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"GitLab request failed ({code}); retain state and reconcile before retrying writes")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(config):
    require(set(config) == {"version", "enabled", "consumer_id", "catalog_version_id", "report_author_ids",
                           "agent_privileges", "pre_approved_agent_privileges"}, "unexpected controller config")
    require(config["version"] == 1 and config["enabled"] is True, "controller not activated")
    require(all(integer(config[k], 1, 2**63) for k in ("consumer_id", "catalog_version_id")),
            "resolve the enabled consumer and exact published catalog version IDs")
    require(config["report_author_ids"] and all(integer(i, 1, 2**63) for i in config["report_author_ids"]),
            "pin the verified reporting service-account IDs")
    allowed = config["agent_privileges"]
    approved = config["pre_approved_agent_privileges"]
    require(isinstance(allowed, list) and allowed and len(set(allowed)) == len(allowed)
            and all(integer(i, 1, 5) for i in allowed), "explicit non-MCP privileges required")
    require(isinstance(approved, list) and len(set(approved)) == len(approved)
            and set(approved) <= set(allowed), "pre-approved privileges exceed allowed privileges")


class GitLab:
    def __init__(self, token):
        require(isinstance(token, str) and token.strip() and not any(c.isspace() for c in token), "missing controller token")
        self._token = token
        self._opener = build_opener(NoRedirect())

    def request(self, method, path, data=None, graphql=False):
        require(path.startswith("/") and not path.startswith("//"), "invalid API path")
        url = "https://gitlab.com/api/graphql" if graphql else API + path
        req = Request(url, data=None if data is None else canonical(data).encode(), method=method,
                      headers={"PRIVATE-TOKEN": self._token, "Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
                require(len(raw) <= MAX_BYTES, "API response too large; no partial evidence")
                value = json.loads(raw, object_pairs_hook=unique_object)
                return value, response.headers
        except HTTPError as exc:
            raise APIError(exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise APIError("transport/unknown outcome") from None

    def rest(self, method, path, data=None):
        return self.request(method, f"/projects/{PROJECT_ID}" + path, data)[0]

    def head(self, branch):
        return self.rest("GET", "/repository/branches/" + quote(branch, safe=""))["commit"]["id"]

    def check_state_branch(self):
        project = self.rest("GET", "")
        branch = self.rest("GET", "/repository/branches/" + quote(STATE_BRANCH, safe=""))
        require(project["path_with_namespace"] == PROJECT_PATH and project["default_branch"] != STATE_BRANCH
                and branch["protected"] is True, "pre-create a separately protected non-default controller-state branch")

    def start(self, goal, request, config):
        body = {"project_id": str(PROJECT_ID), "issue_id": request["source_issue_iid"],
                "source_branch": request["branch"], "goal": goal, "environment": "ambient",
                "ai_catalog_item_consumer_id": config["consumer_id"],
                "ai_catalog_item_version_id": config["catalog_version_id"], "start_workflow": True,
                "agent_privileges": config["agent_privileges"],
                "pre_approved_agent_privileges": config["pre_approved_agent_privileges"],
                "allow_agent_to_request_user": True}
        return self.request("POST", "/ai/duo_workflows/workflows", body)[0]

    def sessions(self, session_id, marker):
        query = """query($project: ProjectID!, $id: AiDuoWorkflowsWorkflowID, $search: String, $after: String) {
          duoWorkflowWorkflows(projectId: $project, workflowId: $id, search: $search, first: 100, after: $after) {
            nodes { id projectId goal statusName }
            pageInfo { hasNextPage endCursor }
          }
        }"""
        variables = {"project": f"gid://gitlab/Project/{PROJECT_ID}",
                     "id": f"gid://gitlab/Ai::DuoWorkflows::Workflow/{session_id}" if session_id else None,
                     "search": None if session_id else marker, "after": None}
        found = []
        for _ in range(20):
            result = self.request("POST", "/", {"query": query, "variables": variables}, graphql=True)[0]
            require(not result.get("errors"), "session query unavailable; no dispatch")
            connection = result["data"]["duoWorkflowWorkflows"]
            for item in connection["nodes"]:
                if not session_id and not item["goal"].startswith(marker + "\n"):
                    continue
                require(re.fullmatch(r"gid://gitlab/Ai::DuoWorkflows::Workflow/[1-9][0-9]*", item["id"]), "invalid session GID")
                require(item["projectId"] == f"gid://gitlab/Project/{PROJECT_ID}", "foreign session project GID")
                found.append({"id": int(item["id"].rsplit("/", 1)[1]), "project_id": PROJECT_ID,
                              "goal": item["goal"], "status": item["statusName"].lower()})
            if not connection["pageInfo"]["hasNextPage"]:
                return found
            cursor = connection["pageInfo"]["endCursor"]
            require(cursor and cursor != variables["after"], "invalid session pagination")
            variables["after"] = cursor
        raise ValueError("session pagination limit; no partial ownership result")

    def notes(self, source):
        values = []
        for page in range(1, 101):
            path = f"/projects/{PROJECT_ID}/issues/{source}/notes?per_page=100&page={page}&sort=desc&order_by=created_at"
            result, headers = self.request("GET", path)
            require(isinstance(result, list), "invalid notes response")
            values.extend(result)
            if not headers.get("X-Next-Page"):
                return values
        raise ValueError("note pagination limit; no partial checkpoint search")

    def note(self, source, note_id):
        return self.rest("GET", f"/issues/{source}/notes/{note_id}")

    def verify_answers(self, answers, source, reporting_authors):
        """Read provenance; the protected operator resume action is the authorization.

        Agent-written notes alone must never authorize start/resume or wider scope.
        """
        for answer in answers:
            note_id = int(answer["source_url"].rsplit("note_", 1)[1])
            note = self.note(source, note_id)
            require(note["id"] == note_id and note.get("system") is False and
                    integer(note["author"]["id"], 1, 2**63) and note["author"]["id"] not in reporting_authors,
                    "answer requires an attributed non-worker source note")
            require(all(answer[k] in note["body"] for k in ("id", "question", "answer")),
                    "source note does not contain the recorded question and answer")

    def tree_files(self, ref):
        """Read complete tree identities; compare diffs alone can omit files at server limits."""
        require(sha(ref), "tree revision must be pinned")
        files, seen = {}, set()
        for page in range(1, 101):
            query = urlencode({"ref": ref, "recursive": "true", "per_page": 100, "page": page})
            rows, headers = self.request("GET", f"/projects/{PROJECT_ID}/repository/tree?" + query)
            require(isinstance(rows, list), "invalid tree response")
            for row in rows:
                require(isinstance(row, dict) and isinstance(row.get("path"), str) and row["path"] not in seen
                        and sha(row.get("id")) and row.get("type") in {"blob", "tree", "commit"}
                        and isinstance(row.get("mode"), str), "invalid or repeated tree entry")
                seen.add(row["path"])
                if row["type"] != "tree":
                    files[row["path"]] = (row["id"], row["type"], row["mode"])
            next_page = headers.get("X-Next-Page")
            if not next_page:
                # GitLab.com may omit pagination headers: probe a full page's successor.
                if len(rows) < 100:
                    return files
            else:
                require(str(next_page) == str(page + 1), "invalid tree pagination")
        raise ValueError("tree pagination limit; no partial diff evidence")

    def verify_decision_applications(self, checkpoint, state):
        """Verify actual changed paths, saved files and report readback before acknowledging answers."""
        groups = {}
        for application in checkpoint["decision_applications"]:
            pair = (application_base(checkpoint, state, application), application["candidate_sha"])
            groups.setdefault(pair, []).append(application)
        for (old, new), applications in groups.items():
            self.verify_application_group(old, new, applications, state["request"]["source_issue_iid"])

    def verify_application_group(self, old, new, applications, source):
        comparison = self.rest("GET", "/repository/compare?" + urlencode({"from": old, "to": new, "straight": "true"}))
        diffs = comparison.get("diffs")
        require(comparison.get("compare_timeout") is False and isinstance(diffs, list) and diffs,
                "decision diff unavailable or truncated")
        require(all(not any(d.get(k) for k in ("deleted_file", "renamed_file", "collapsed", "too_large")) for d in diffs),
                "decision diff contains deletion/rename or incomplete evidence")
        paths = {p for application in applications for p in application["changed_paths"]}
        require(paths == {d["new_path"] for d in diffs}, "decision application diff differs from the scoped receipt")
        before, after = self.tree_files(old), self.tree_files(new)
        changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
        require(changed == paths and all(after.get(p, (None, None, None))[1:] == ("blob", "100644") for p in paths),
                "complete tree diff differs from scoped document receipt")
        for path in sorted(paths):
            value = self.rest("GET", "/repository/files/" + quote(path, safe="") + "?" + urlencode({"ref": new}))
            require(value.get("file_path") == path and value.get("commit_id") == new and value.get("encoding") == "base64",
                    "decision artifact readback identity mismatch")
            raw = base64.b64decode(value["content"], validate=True)
            require(hashlib_sha(raw) == value["content_sha256"], "decision artifact readback hash mismatch")
        for application in applications:
            note_id = int(application["report_url"].rsplit("note_", 1)[1])
            note = self.note(source, note_id)
            require(note["id"] == note_id and new in note["body"] and
                    all(p in note["body"] for p in application["changed_paths"]), "decision application report readback mismatch")


class GitLabStore:
    """One immutable request per epic, with optimistic concurrency on every mutation.

    The branch must deny agent writes. CI resource_group serializes controller jobs;
    last_commit_id additionally fences competing/outdated controller processes.
    """
    def __init__(self, api, epic):
        require(integer(epic, 1, 2**31), "invalid epic")
        self.api = api
        self.path = "/repository/files/" + quote(f".ctx-controller/E{epic}.json", safe="")

    def load(self):
        value = self.api.rest("GET", self.path + "?" + urlencode({"ref": STATE_BRANCH}))
        require(value["encoding"] == "base64" and sha(value["last_commit_id"]), "invalid stored state encoding")
        raw = base64.b64decode(value["content"], validate=True)
        require(len(raw) <= MAX_BYTES and hashlib_sha(raw) == value["content_sha256"], "state readback hash mismatch")
        return json.loads(raw, object_pairs_hook=unique_object), value["last_commit_id"]

    def save(self, state, revision):
        if revision is not None:
            current, observed = self.load()
            require(observed == revision, "stale controller state; no write or dispatch")
            if current == state:
                return revision  # GitLab rejects empty commits; unchanged polls are normal.
        body = {"branch": STATE_BRANCH, "content": canonical(state),
                "commit_message": "CTX controller checkpoint [skip ci]"}
        if revision is not None:
            body["last_commit_id"] = revision
        self.api.rest("PUT" if revision else "POST", self.path, body)
        saved, new_revision = self.load()
        require(saved == state, "controller state readback mismatch; do not dispatch")
        return new_revision


def hashlib_sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def authorize_execution(old, request, config):
    from ctx_execution import validate_state
    validate_state(old)
    require(old["status"] == "complete" and old["active"] is None
            and old["request"]["mode"] == "design-closure" and request["mode"] == "execute"
            and old["checkpoint"] and old["checkpoint"]["journal"] is None,
            "existing run cannot be reset; only completed design may receive new execution authorization")
    require(request["run_id"] != old["request"]["run_id"]
            and all(request[k] == old["request"][k] for k in ("project_id", "epic_issue_iid", "source_issue_iid", "branch"))
            and request["design_sha"] == old["checkpoint"]["candidate_sha"], "execution authorization changed epic/design")
    state = new_run(request)
    for key in ("checkpoint", "checkpoint_sha256", "checkpoint_note_id", "attempts", "recoveries", "answer_batches"):
        if key not in old:
            continue
        state[key] = old[key]
    state["design_authorization"] = {"request": old["request"], "request_sha256": old["request_sha256"]}
    state["config_sha256"] = digest(config)
    validate_state(state)  # Previously consumed sessions/recoveries remain consumed.
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "tick", "status", "resume"))
    parser.add_argument("--epic", required=True, type=int)
    parser.add_argument("--config", type=Path, default=Path(".gitlab/ctx/controller.json"))
    args = parser.parse_args()
    try:
        # Never expose the token to agent CI; scope it to the controller environment.
        config = json.loads(args.config.read_text(), object_pairs_hook=unique_object)
        validate_config(config)
        api = GitLab(os.environ.get("CTX_CONTROLLER_TOKEN", ""))
        api.check_state_branch()
        store = GitLabStore(api, args.epic)
        if args.action == "init":
            request = json.loads(os.environ.get("CTX_EXECUTION_REQUEST", ""), object_pairs_hook=unique_object)
            require(request["epic_issue_iid"] == args.epic, "request/epic mismatch")
            state = new_run(request)
            require(api.head(request["branch"]) == request["design_sha"], "initial design SHA moved")
            state["config_sha256"] = digest(config)
            try:
                old, revision = store.load()
            except APIError as exc:
                if exc.code != 404:
                    raise
                old, revision = None, None
            if old is not None:
                # A new, explicit execution authorization may follow completed design.
                # No reset/restart of in-flight or completed application execution.
                state = authorize_execution(old, request, config)
            store.save(state, revision)
        else:
            state, revision = store.load()
            require(state["config_sha256"] == digest(config), "controller configuration changed during run")
            if args.action == "tick":
                state = Controller(api, store, config).tick()
            elif args.action == "resume":
                answers = json.loads(os.environ.get("CTX_DECISION_ANSWERS", "[]"), object_pairs_hook=unique_object)
                session = None
                if state["active"]:
                    sessions = api.sessions(state["active"]["session_id"], state["active"]["marker"])
                    require(len(sessions) == 1, "native session status is missing or ambiguous")
                    session = sessions[0]
                resumed = resume_run(state, answers, session)
                api.verify_answers(answers, state["request"]["source_issue_iid"], config["report_author_ids"])
                state = resumed
                store.save(state, revision)
        print(json.dumps({"status": state["status"], "summary": state["summary"],
                          "objective": state["request"]["objective"], "next_action": next_step(state),
                          "sessions_used": len(state["attempts"]), "recoveries_used": state["recoveries"],
                          "checkpoint_note_id": state["checkpoint_note_id"]}))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Do not print API bodies, arbitrary model output, environment, or token-bearing URLs.
        print("CTX controller stopped safely: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
