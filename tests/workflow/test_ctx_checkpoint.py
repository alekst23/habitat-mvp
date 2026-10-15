"""Checkpoint transfer tests use fake GitLab responses, never live credentials."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_ctx_owner import snapshot, note
import ctx_owner as owner
import ctx_checkpoint as checkpoint


class Notes:
    def __init__(self, value):
        self.items = [note(value, 101) | {"author_id": checkpoint.WRITER_ID}]
        self.posts = 0
        self.damage = None
        self.lose_response = False

    def authenticate(self):
        return checkpoint.WRITER_ID

    def notes(self, source):
        return deepcopy(self.items)

    def get(self, source, note_id):
        return deepcopy(next(n for n in self.items if n["id"] == note_id))

    def create(self, source, body):
        self.posts += 1
        item = {"id": 102, "author_id": checkpoint.WRITER_ID,
                "url": note(snapshot(), 102)["url"],
                "body": self.damage(body) if self.damage else body}
        self.items.append(item)
        if self.lose_response:
            raise checkpoint.TransportError("unknown")
        return deepcopy(item)


class CheckpointTests(unittest.TestCase):
    def test_file_assembly_cli_transfers_large_history_without_stdout_payload(self):
        value = snapshot()
        value["resources"] = [{"event": "observed", "note": "retained history " * 6000}]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, updates, output = (root / p for p in ("source.json", "updates.json", "result.json"))
            checkpoint.dev.save_json(source, value)
            checkpoint.dev.save_json(updates, {"session": value["session"] | {"delegations": 5}})
            command = [sys.executable, str(Path(checkpoint.__file__)), "assemble", str(source),
                       "--updates-file", str(updates), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(output.read_text())["resources"], value["resources"])
            self.assertEqual(json.loads(output.read_text())["session"]["delegations"], 5)
            self.assertLess(len(result.stdout), 500)
            self.assertNotIn("retained history", result.stdout)
            before = output.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(output.read_bytes(), before)

    def test_assemble_keeps_loaded_history_and_consumed_budgets(self):
        old = snapshot()
        old["resources"] = [{"note": "full history " * 6000}]
        updates = {"session": old["session"] | {"delegations": 5},
                   "resources_append": [{"event": "reserved-delegation"}]}
        result = checkpoint.assemble(old, updates=updates)
        self.assertEqual(result["resources"][:-1], old["resources"])
        self.assertEqual(result["session"]["delegations"], 5)
        self.assertEqual(result["objective"], old["objective"])
        self.assertEqual(len(old["resources"]), 1)
        for bad in ({"resources": []}, {"session": old["session"] | {"delegations": 0}},
                    {"objective": old["objective"] | {"goal": "widened"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checkpoint.assemble(old, updates=bad)

    def test_large_generated_payload_round_trip_and_repeat_do_not_retype_or_repost(self):
        old = snapshot()
        old["resources"] = [{"event": "observed", "note": "history ☃ " * 8000}]
        new = deepcopy(old)
        new["session"]["delegations"] += 1
        api = Notes(old)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            result = checkpoint.publish(api, new, "Review claim saved. No user action now.",
                                        previous_note_id=101, receipt_path=path)
            self.assertTrue(result["verified"])
            self.assertEqual(owner.parse(api.items[-1]["body"]), new)
            self.assertGreater(len(api.items[-1]["body"].encode()), 54000)
            again = checkpoint.publish(api, new, "Review claim saved. No user action now.",
                                       previous_note_id=101, receipt_path=path)
            self.assertEqual(again["note_url"], result["note_url"])
            self.assertEqual(api.posts, 1)

    def test_saved_note_must_equal_body_and_full_payload_not_just_schema(self):
        for damage in (lambda body: body.replace("history", "invented"),
                       lambda body: body[:-20],
                       lambda body: body.replace('"resources": [', '"resources": [{"invented":true},')):
            old = snapshot()
            new = deepcopy(old)
            new["resources"].append({"note": "history"})
            api = Notes(old)
            api.damage = damage
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "receipt.json"
                with self.assertRaises(ValueError):
                    checkpoint.publish(api, new, "Saved claim.", previous_note_id=101, receipt_path=path)
                self.assertNotEqual(json.loads(path.read_text())["state"], "verified")
                with self.assertRaises(ValueError):
                    checkpoint.publish(api, new, "Saved claim.", previous_note_id=101, receipt_path=path)
                self.assertEqual(api.posts, 1)

    def test_lost_post_response_reconciles_existing_note_without_another_write(self):
        old = snapshot()
        new = deepcopy(old)
        new["session"]["delegations"] += 1
        api = Notes(old)
        api.lose_response = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            with self.assertRaises(checkpoint.TransportError):
                checkpoint.publish(api, new, "Saved claim.", previous_note_id=101, receipt_path=path)
            self.assertEqual(json.loads(path.read_text())["state"], "publication_unknown")
            result = checkpoint.publish(api, new, "Saved claim.", previous_note_id=101, receipt_path=path)
            self.assertTrue(result["verified"])
            self.assertEqual(api.posts, 1)
            api.items.pop()
            with self.assertRaises(ValueError):
                checkpoint.publish(api, new, "Saved claim.", previous_note_id=101, receipt_path=path)
            self.assertEqual(api.posts, 1)

    def test_history_reset_stale_parent_and_unexpected_actor_cannot_post(self):
        old = snapshot()
        old["resources"].append({"note": "reserved work"})
        for change in ("history", "parent", "actor"):
            api = Notes(old)
            new = deepcopy(old)
            parent = 101
            if change == "history":
                new["resources"] = []
            elif change == "parent":
                parent = 99
            else:
                api.authenticate = lambda: 43066631
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    checkpoint.publish(api, new, "Saved claim.", previous_note_id=parent,
                                       receipt_path=Path(folder) / "receipt.json")
                self.assertEqual(api.posts, 0)

    def test_read_exports_original_notes_and_full_state_without_printing_payload(self):
        api = Notes(snapshot())
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "download"
            result = checkpoint.download(api, 10, "E2", output)
            self.assertEqual(json.loads((output / "handoff.json").read_text()), snapshot())
            self.assertEqual(json.loads((output / "notes.json").read_text()), api.items)
            self.assertEqual(result["source_note_id"], 101)
            self.assertNotIn("resources", result)
            with self.assertRaises(ValueError):
                checkpoint.download(api, 10, "E2", output)

    def test_runtime_credential_boundary_no_personal_fallback_and_no_redirects(self):
        base = {"CI_PROJECT_ID": "87329027", "GITLAB_TOKEN": "fixture-oauth-token"}
        for invalid in ({}, {**base, "CI_PROJECT_ID": "1"},
                        {**base, "GITLAB_BASE_URL": "https://attacker.invalid"},
                        {**base, "GITLAB_OAUTH_TOKEN": "different"},
                        {"CI_PROJECT_ID": "87329027", "PRIVATE_TOKEN": "fixture-personal"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                checkpoint.GitLabNotes.from_environment(invalid)
        api = checkpoint.GitLabNotes.from_environment(base)
        with patch.object(api, "_opener") as opener:
            opener.open.return_value.__enter__.return_value.read.return_value = b'{"id":43132375}'
            opener.open.return_value.__enter__.return_value.headers = {}
            self.assertEqual(api.authenticate(), checkpoint.WRITER_ID)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://gitlab.com/api/v4/user")
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture-oauth-token")
            self.assertIsNone(request.get_header("Private-token"))
            body = "Generated history ☃ " * 6000
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "id": 123, "body": body, "author": {"id": checkpoint.WRITER_ID}}).encode()
            self.assertEqual(api.create(10, body)["body"], body)
            sent = opener.open.call_args.args[0]
            self.assertEqual(json.loads(sent.data), {"body": body})
            self.assertNotIn("fixture-oauth-token", sent.data.decode())
        self.assertIsNone(checkpoint.NoRedirect().redirect_request(None, None, 302, "", {},
                                                                  "https://attacker.invalid"))

    def test_pagination_and_error_redaction_do_not_accept_partial_notes_or_echo_secrets(self):
        api = checkpoint.GitLabNotes("fixture-oauth-token")
        def server_note(i):
            return {"id": i, "body": "record", "author": {"id": checkpoint.WRITER_ID}}
        with patch.object(api, "_request", side_effect=[
                ([server_note(i) for i in range(1, 101)], {"X-Next-Page": "2"}),
                ([server_note(101)], {"X-Next-Page": ""})]) as request:
            self.assertEqual(len(api.notes(10)), 101)
            self.assertIn("page=2&", request.call_args.args[1])
            self.assertIn("order_by=created_at&sort=asc", request.call_args.args[1])
        with patch.object(api, "_request", return_value=([server_note(1)] * 100, {})):
            with self.assertRaisesRegex(ValueError, "pagination"):
                api.notes(10)
        with patch.object(api, "_opener") as opener:
            opener.open.side_effect = OSError("fixture-oauth-token must not be logged")
            with self.assertRaises(checkpoint.TransportError) as raised:
                api.authenticate()
            self.assertNotIn("fixture-oauth-token", str(raised.exception))
            for method, path, data in (("POST", "/user", {"body": "hi"}),
                                      ("POST", "/projects/1/issues/10/notes", {"body": "hi"}),
                                      ("DELETE", "/projects/87329027/issues/10/notes/1", None),
                                      ("POST", "/projects/87329027/issues/10/notes", {"body": "fixture-oauth-token"})):
                with self.subTest(method=method, path=path), self.assertRaises(ValueError):
                    api._request(method, path, data)
            self.assertEqual(opener.open.call_count, 1)

    def test_known_invalid_notes_are_quarantined_only_in_exact_source_and_new_damage_blocks(self):
        value = json.loads(json.dumps(snapshot()).replace('E2', 'E11').replace('epic-i2', 'epic-i11')
                           .replace('/issues/10', '/issues/11'))
        value["objective"]["source_issue_iid"] = value["closure"]["source_issue_iid"] = 11
        value["objective"]["run_id"] = "execute-e11-1"
        def row(note_id, body):
            return {"id": note_id, "author_id": checkpoint.WRITER_ID,
                    "url": checkpoint.BASE + f"/-/issues/11#note_{note_id}", "body": body}
        good = row(4019881978, owner.render(value))
        invalid_ids = [4019842621, 4019862442, 4019930708, 4020048348,
                       4020406044, 4020434941, 4020464828]
        rows = [good] + [row(i, owner.MARKER + "\nbroken") for i in invalid_ids]
        result = owner.select(rows, source_issue_iid=11, epic="E11",
                              trusted_author_ids=[checkpoint.WRITER_ID])
        self.assertEqual(result["handoff"], value)
        self.assertEqual(sorted(n["note_id"] for n in result["excluded_notes"]), sorted(invalid_ids))
        self.assertEqual(len(rows), 8)  # Exclusions never delete the evidence.
        policy = json.loads(owner.EXCLUSIONS.read_text())
        for bad in (policy | {"note_ids": [True]}, policy | {"note_ids": [1, 1]},
                    policy | {"evidence_url": "https://example.invalid"},
                    policy | {"run_id": "*"}, policy | {"ignore_all": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                owner.validate_checkpoint_exclusions(bad)
        wrong_run = deepcopy(value)
        wrong_run["objective"]["run_id"] = "reset-run"
        with self.assertRaises(ValueError):
            owner.select([row(4019881978, owner.render(wrong_run))] + rows[1:], source_issue_iid=11,
                         epic="E11", trusted_author_ids=[checkpoint.WRITER_ID])
        with self.assertRaises(ValueError):
            owner.select([good, rows[1] | {"author_id": 43066631}], source_issue_iid=11,
                         epic="E11", trusted_author_ids=[checkpoint.WRITER_ID, 43066631])
        with self.assertRaises(ValueError):
            owner.select(rows + [row(4020464829, owner.MARKER + "\nbroken")], source_issue_iid=11,
                         epic="E11", trusted_author_ids=[checkpoint.WRITER_ID])
        with self.assertRaises(ValueError):
            owner.select(rows, source_issue_iid=11, epic="E2", trusted_author_ids=[checkpoint.WRITER_ID])

    def test_summary_cannot_trigger_mentions_or_gitlab_quick_actions(self):
        for summary in ("Saved.\n/close", "Saved.\n /label ~done", "@ai-ctx-development Continue E11"):
            api = Notes(snapshot())
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, "quick actions"):
                    checkpoint.publish(api, snapshot(), summary, previous_note_id=101,
                                       receipt_path=Path(folder) / "receipt.json")
                self.assertEqual(api.posts, 0)


if __name__ == "__main__":
    unittest.main()
