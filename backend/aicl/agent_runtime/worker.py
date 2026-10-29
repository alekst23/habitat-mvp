"""Local worker drains durable wakeups while the application is running.

Wakeups and leases survive the worker. Restart discovers due queued runs and
expired ownership; it never infers that a lost provider request was free.
"""
from __future__ import annotations

from datetime import timedelta
import logging
import threading
import uuid

from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.db import to_iso


class LocalRuntimeWorker:
    def __init__(self, runtime, *, interval=1):
        self.runtime, self.interval = runtime, interval
        self.worker_id = "local-runtime-" + uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread = None

    def tick(self):
        runtime = self.runtime
        # Scheduled and manual workspace work share this same durable runner.
        # Admission never dispatches and retains blocked due occurrences.
        from aicl.agent_workspace.execution import admit_scheduled_runs
        admit_scheduled_runs(runtime, self.worker_id)
        now = runtime.clock.now()
        with runtime.db.reader() as conn:
            rows = conn.execute(
                "SELECT r.id,r.tenant_id,r.owner_id FROM agent_run r LEFT JOIN agent_wakeup w ON w.run_id=r.id "
                "WHERE (r.status='queued' AND w.available_at<=? AND (r.lease_until IS NULL OR r.lease_until<=?)) "
                "OR (r.status='running' AND r.lease_until<=?) ORDER BY r.updated_at LIMIT 8",
                (to_iso(now), to_iso(now), to_iso(now))).fetchall()
        advanced = 0
        for row in rows:
            if self._stop.is_set():
                break
            # Trusted server execution identity is reconstructed from the owned
            # run, not supplied by a client or included in model context.
            auth = AuthContext(row["owner_id"], row["tenant_id"], self.worker_id,
                               runtime.clock.now() + timedelta(minutes=10))
            try:
                runtime.advance_slice(auth, row["id"], worker_id=self.worker_id, max_operations=8, max_seconds=120)
                advanced += 1
            except AiclError:
                # Fencing/control races leave persisted work for its current
                # owner. Never include content or provider exception text in logs.
                continue
            except Exception:
                logging.getLogger(__name__).error("Durable session worker interrupted; saved state will be recovered.")
        return advanced

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    logging.getLogger(__name__).error("Durable wakeup scan unavailable; retrying the saved queue.")
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=loop, name=self.worker_id, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
