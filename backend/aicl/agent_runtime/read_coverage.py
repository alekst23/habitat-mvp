"""Pure coverage of successful, already authorized immutable artifact reads.

Callers establish run/owner scope before passing receipts here. Coverage is
neither authority nor a cache: it can suppress redundant proposals, but cannot
authorize a read, disclose data, or create new evidence.
"""
from aicl.agent_runtime.contracts import canonical_json


def read_selector(request):
    selector = {"ref": request["ref"]}
    for key in ("source_index", "field"):
        if request.get(key) is not None:
            selector[key] = request[key]
    if request.get("public_preview") is True:
        selector["public_preview"] = True
    return selector


def read_span(request, result):
    """Describe actual returned characters, not the requested maximum."""
    if (type(result) is not dict or result.get("error") is not None or "error" not in result
            or type(result.get("text")) is not str or type(result.get("total_chars")) is not int
            or result["total_chars"] < 0 or result.get("ref") != request.get("ref")
            or result.get("source_index") != request.get("source_index")):
        return None
    start = request.get("offset", 0)
    if type(start) is not int or start < 0:
        return None
    text, total = result["text"], result["total_chars"]
    if start <= total and start + len(text) > total:
        return None
    if start > total and text:
        return None
    selector = read_selector(request)
    if result.get("reader_version") == "artifact-v5" and result.get("projection") in {
            "public_evidence_preview", "public_page_text"}:
        # The brokered reader enforces this representation even when the
        # proposal omits the old optional hint. Never treat these as raw offsets.
        selector["public_preview"] = True
    return {"key": canonical_json(selector), "selector": selector, "start": min(start, total),
            "end": min(start + len(text), total), "total_chars": total, "text": text}


def merged_ranges(spans):
    ranges = []
    for span in sorted(spans, key=lambda item: (item["start"], item["end"])):
        start, end = span["start"], span["end"]
        if end <= start:
            continue
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    return ranges


def request_covered(request, spans):
    """True only for a requested range entirely observed in this representation."""
    key = canonical_json(read_selector(request))
    matching = [span for span in spans if span is not None and span["key"] == key]
    if not matching:
        return False
    totals = {span["total_chars"] for span in matching}
    if len(totals) != 1:
        return False
    total = totals.pop()
    start = request.get("offset", 0)
    end = min(total, start + request.get("max_chars", 4000))
    if start >= total:
        return True
    return any(low <= start and high >= end for low, high in merged_ranges(matching))
