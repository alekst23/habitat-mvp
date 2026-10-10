"""Admission guard before one Duo delegation; NOT a running-worker cancellation timer."""
import argparse
import json
import time


def admission(started_at, now):
    elapsed = now - started_at
    if elapsed < 0:
        raise ValueError("session start is in the future")
    # 10m coordinator preparation + 20m worker target + 15m publication/headroom.
    return {"delegate": elapsed < 600, "elapsed_seconds": int(elapsed),
            "save_by": started_at + 1800, "reason": "admitted" if elapsed < 600 else "checkpoint now"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--started-at", type=int, required=True)
    args = parser.parse_args()
    try:
        result = admission(args.started_at, time.time())
        print(json.dumps(result))
        raise SystemExit(0 if result["delegate"] else 2)
    except ValueError:
        print(json.dumps({"delegate": False, "reason": "invalid start time"}))
        raise SystemExit(2)
