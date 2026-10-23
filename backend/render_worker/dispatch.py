"""Short-lived cron dispatcher with durable AICL outbox and Render deduplication."""
from __future__ import annotations

import json
import os
import re

from render_worker.client import AICLClient, ClientConfig, MachineAPIError, identifier


def dispatch_once(client, workflows, task_slug):
    if not re.fullmatch(r"[A-Za-z0-9_-]+/habitat_agent", task_slug):
        raise ValueError("RENDER_TASK_SLUG must identify the registered habitat_agent task")
    records = client.dispatch().get("dispatches")
    if not isinstance(records, list) or len(records) > 100:
        raise MachineAPIError("AICL returned an invalid dispatch batch")
    submitted = 0
    for record in records:
        dispatch_id = identifier(record.get("id"))
        if (record.get("input") != {"dispatch_id": dispatch_id}
                or record.get("idempotency_key") != "habitat:" + dispatch_id):
            raise MachineAPIError("AICL returned an invalid dispatch envelope")
        try:
            run = workflows.start_task(task_slug, {"dispatch_id": dispatch_id},
                                       idempotency_key=record["idempotency_key"])
            client.submitted(dispatch_id, identifier(run.id))
        except Exception:
            # Timeout may mean Render accepted the launch. Keep the SAME durable
            # key and let AICL enforce the retry window; do not mint a new key.
            try:
                client.uncertain(dispatch_id)
            except MachineAPIError:
                pass
            raise MachineAPIError("Dispatch outcome is unresolved; AICL retained the original dispatch key") from None
        submitted += 1
    return {"submitted": submitted}


def main():
    from render import Render

    try:
        with AICLClient(ClientConfig.from_env("scheduler")) as client:
            task_slug = os.environ.get("RENDER_TASK_SLUG") or (
                os.environ.get("RENDER_WORKFLOW_SLUG", "") + "/habitat_agent")
            result = dispatch_once(client, Render(), task_slug)
        print(json.dumps(result), flush=True)
        return 0
    except Exception:
        # Even a provider SDK error may contain a credential-bearing URL or
        # request body. Emit only a stable error; AICL retains durable evidence.
        print(json.dumps({"error": "render_dispatch_failed", "action": "Inspect the AICL dispatch audit and service configuration."}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
