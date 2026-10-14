"""pytest plugin for the reviewed verify adapter: explicit test -> AC mapping.

A test names the criteria it proves with
``@pytest.mark.ac("E11-1.AC1", ..., code="path/to/file.py:symbol")``; ``code`` (no
whitespace, a tracked repository file plus optional ``:symbol``) names the implementation
the test exercises and is required, because every AC row needs a code reference. The plugin copies those declarations into the JUnit XML as test properties,
so the writer reads the mapping from the executed run, never from a separate list.
Malformed declarations abort collection; the plugin runs nothing else.
"""

import re

import pytest

AC_ID = re.compile(r"E[1-9][0-9]*-[1-9][0-9]*\.AC[1-9][0-9]*")
PROPERTY = "ctx_ac"


def pytest_configure(config):
    config.addinivalue_line("markers", "ac(*ids, code): acceptance criteria proved by this test and the code it exercises")


def pytest_collection_modifyitems(items):
    for item in items:
        for mark in item.iter_markers("ac"):
            code = mark.kwargs.get("code")
            valid = (mark.args and set(mark.kwargs) <= {"code"} and
                     all(isinstance(a, str) and AC_ID.fullmatch(a) for a in mark.args) and
                     isinstance(code, str) and code and not re.search(r"\s", code))
            if not valid:
                raise pytest.UsageError(f"invalid ac marker on {item.nodeid}: use ac('E1-1.AC1', ..., code='path:symbol') (code is required)")
            for ac_id in mark.args:
                item.user_properties.append((PROPERTY, f"{ac_id} {code}"))
