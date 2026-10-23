"""Render Workflow entry point: PYTHONPATH=backend python -m render_worker.main."""
from __future__ import annotations

import json

from render import Retry, TaskContext, Workflows

from render_worker.client import AICLClient, ClientConfig
from render_worker.runner import execute


app = Workflows()


@app.task(name="habitat_agent", timeout_seconds=180, plan="flex",
          retry=Retry(max_retries=1, wait_duration_ms=2000, backoff_scaling=2))
def habitat_agent(ctx: TaskContext, dispatch_id: str) -> dict:
    # Load credentials inside execution, not during task registration. Never put
    # credentials, owner goals, or generated content in task arguments/results.
    with AICLClient(ClientConfig.from_env("worker")) as client:
        return execute(client, dispatch_id, ctx.metadata.task_run_id,
                       emit=lambda event: print(json.dumps(event), flush=True))


if __name__ == "__main__":
    app.start()
