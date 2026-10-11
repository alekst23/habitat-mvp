"""Admission guard before one Duo delegation; NOT a running-worker cancellation timer."""
import argparse
import json
import math
import time


def admission(started_at, now, *, mode="native", delegations=0):
    if mode not in ("native", "controller"):
        raise ValueError("unknown execution mode")
    if type(delegations) is not int or delegations < 0:
        raise ValueError("invalid delegation count")
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (started_at, now)):
        raise ValueError("invalid session time")
    elapsed = now - started_at
    if elapsed < 0:
        raise ValueError("session start is in the future")
    # Native: admit until 40m, target incremental saves within 15m and by 50m.
    # Controller compatibility: one unit, 10m admission / 30m save target.
    # These are soft admission targets, not worker cancellation or spend limits.
    limit = 64 if mode == "native" else 1
    cutoff = 2400 if mode == "native" else 600
    save_by = min(now + 900, started_at + 3000) if mode == "native" else started_at + 1800
    allowed = elapsed < cutoff and delegations < limit
    reason = "admitted" if allowed else (
        "delegation limit; checkpoint now" if delegations >= limit else "time limit; checkpoint now")
    return {"delegate": allowed, "mode": mode, "elapsed_seconds": int(elapsed),
            "save_by": save_by, "reason": reason}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--started-at", type=int, required=True)
    parser.add_argument("--mode", choices=("native", "controller"))
    parser.add_argument("--delegations", type=int,
                        help="All already reserved delegations in this session, including failures")
    args = parser.parse_args()
    try:
        # Preserve the published v1.6.0 started-at-only CLI during coordinated rollout.
        # It has an engine cap of one; never silently give that caller native limits.
        mode, count = args.mode, args.delegations
        if mode is None and count is None:
            mode, count = "controller", 0
        elif mode is None or count is None:
            raise ValueError("mode and delegation count must be supplied together")
        result = admission(args.started_at, time.time(), mode=mode, delegations=count)
        print(json.dumps(result))
        raise SystemExit(0 if result["delegate"] else 2)
    except ValueError:
        print(json.dumps({"delegate": False, "reason": "invalid session budget"}))
        raise SystemExit(2)
