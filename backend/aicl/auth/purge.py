"""MagicLinkPurge startup hook (aicl-experience/technical.md, owner E11-3). Not yet registered in STARTUP_HOOKS."""

from __future__ import annotations

from datetime import timedelta

from aicl.db import to_iso

NOT_IMPLEMENTED = "E11-3 behavior is not implemented (contract stub)"
PURGE_AFTER_EXPIRY_HOURS = 24


class MagicLinkPurge:
    """Deletes `magic_link` rows expired for more than 24 hours, at startup (`run_once`) and hourly."""

    def __init__(self, db: object, clock: object) -> None:
        self.db = db
        self.clock = clock

    def run_once(self) -> int:
        """Returns the number of deleted rows."""
        cutoff = to_iso(self.clock.now() - timedelta(hours=PURGE_AFTER_EXPIRY_HOURS))
        with self.db.transaction() as conn:
            return conn.execute("DELETE FROM magic_link WHERE expires_at < ?", (cutoff,)).rowcount
