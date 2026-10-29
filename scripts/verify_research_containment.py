#!/usr/bin/env python3
"""Offline kernel-isolation proof for a *candidate* research worker container.

This does not attest the running Habitat application and cannot enable its live
research capabilities. No image is pulled, no host directory is mounted, no
provider credential is inherited, and no provider request is attempted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import sys



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="python:3.12-slim-trixie",
                        help="Already cached Python image; never pulled.")
    args = parser.parse_args()
    # Inspect and execute the immutable local ID; a moved tag cannot substitute
    # another image between inspection and launch.
    inspected = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", args.image],
                               check=True, capture_output=True, text=True, timeout=15)
    image_id = inspected.stdout.strip()
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise RuntimeError("A pinned local image is required.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from aicl.network.research_worker import DockerResearchWorker
    worker = DockerResearchWorker(image_id)
    checks = worker.execute({"action": "verify"})["checks"]
    verified = bool(checks) and all(value is True for value in checks.values())
    print(json.dumps({"candidate_image": image_id, "checks": checks,
                      "candidate_verified": verified,
                      "running_application_verified": False}, sort_keys=True))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
