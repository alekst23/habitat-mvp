"""Compact, untrusted source overviews for the private writing phase.

This only projects already saved evidence. It cannot authorize or request any
network operation. Whole sources remain available through scoped retrieval.
"""
from __future__ import annotations

from copy import deepcopy

from aicl.network.research_projection import public_search_candidate_is_disclosable
from aicl.workflow.openai_inference import _contains_secret


def public_page_text(source):
    """Use the same text coordinates in overview excerpts and scoped reads."""
    return " ".join(str(source.get("text", "")).split())


def public_source_preview(source):
    """Omit whole credential-shaped discovery candidates, never rewrite URLs.

    This is a view of untrusted public evidence, not a sanitization of private
    context or a relaxation of the model adapter's final credential guard.
    """
    result = deepcopy(source)
    if type(result) is dict and type(result.get("links")) is list:
        original = result["links"]
        result["links"] = [link for link in original if not _contains_secret(link, "")]
        omitted = len(original) - len(result["links"])
        if omitted:
            result["links_omitted_for_disclosure"] = omitted
    if (type(result) is dict and result.get("source_kind") == "public_search"
            and type(result.get("sources")) is list):
        original = result["sources"]
        result["sources"] = [candidate for candidate in original if type(candidate) is not dict
                             or public_search_candidate_is_disclosable(candidate)]
        omitted = len(original) - len(result["sources"])
        if omitted:
            result["sources_omitted_for_disclosure"] = omitted
    return result


def public_evidence_preview(value):
    """Return a public view and the number of omitted discovery candidates.

    The caller must separately establish that its scoped reference belongs to
    actual public research; this shape check does not grant that authority.
    """
    def source(entry):
        if (type(entry) is dict and set(entry) == {"evidence_index", "omitted", "evidence_ref", "instruction_authority"}
                and entry["omitted"] is True and type(entry["evidence_index"]) is int
                and 0 <= entry["evidence_index"] <= 29 and type(entry["evidence_ref"]) is str
                and 0 < len(entry["evidence_ref"]) <= 240
                and entry["instruction_authority"] == "untrusted_evidence"):
            # Oversized receipts retain complete scoped source references.
            # This metadata contains no discovery candidates to project.
            return deepcopy(entry), 0
        if (type(entry) is not dict or entry.get("source_kind") not in {"public_page", "public_search"}
                or entry.get("instruction_authority") != "untrusted_evidence"):
            raise ValueError("Expected saved public research evidence")
        preview = public_source_preview(entry)
        removed = len(entry.get("links", [])) - len(preview.get("links", []))
        if entry["source_kind"] == "public_search":
            removed += len(entry.get("sources", [])) - len(preview.get("sources", []))
        return preview, removed

    if type(value) is dict and (value.get("source_kind") in {"public_page", "public_search"} or value.get("omitted") is True):
        return source(value)
    if (type(value) is not dict or "error" not in value or value["error"] is not None
            or type(value.get("evidence")) is not list):
        raise ValueError("Expected a saved public research receipt")
    result, omitted = deepcopy(value), 0
    result["evidence"] = []
    for entry in value["evidence"]:
        preview, removed = source(entry)
        result["evidence"].append(preview)
        omitted += removed
    return result, omitted


def source_overview(sources, *, text_chars):
    """Keep every source identity visible before spending space on page bodies.

    `sources` contains (evidence, saved reference, optional receipt index). Links
    are candidates, not fetched evidence. Source-reported dates stay untrusted.
    """
    entries = []
    for source, ref, index in sources:
        if type(source) is not dict:
            continue
        source = public_source_preview(source)
        entry = {key: deepcopy(source[key]) for key in
                 ("source_kind", "url", "title", "unavailable", "reason", "date_candidates",
                  "links_omitted_for_disclosure", "sources_omitted_for_disclosure") if key in source}
        entry.update(instruction_authority="untrusted_evidence", evidence_ref=ref)
        arguments = {"ref": ref, "offset": 0, "max_chars": 4000, "public_preview": True}
        if index is not None:
            arguments["source_index"] = index
        entry["retrieval"] = {"tool": "artifact.read", "arguments": arguments}
        if source.get("source_kind") == "public_search":
            entry["sources"] = []
            for result in source.get("sources", []):
                if type(result) is not dict:
                    continue
                item = {key: deepcopy(result[key]) for key in ("url", "title", "date_candidates") if key in result}
                snippet = " ".join(str(result.get("text", "")).split())
                limit = min(240, text_chars)
                item.update(text=snippet[:limit], truncated=len(snippet) > limit,
                            authorized_to_fetch=False)
                entry["sources"].append(item)
        else:
            text = public_page_text(source)
            entry.update(text=text[:text_chars],
                         truncated=bool(source.get("truncated")) or len(text) > text_chars)
            if source.get("source_kind") == "public_page" and not source.get("unavailable"):
                # These offsets address the body alone, not the JSON link list.
                arguments.update(field="text", offset=min(len(text), text_chars))
            # Page bodies and dates matter more than dozens of outgoing links
            # in this phase. All original links remain in the saved source.
            entry["links"] = deepcopy(source.get("links", [])[:3])
            entry["links_truncated"] = len(source.get("links", [])) > 3 or bool(source.get("links_omitted_for_disclosure"))
        entries.append(entry)
    return {"error": None, "evidence": entries, "public_evidence_truncated": True,
            "projection": "source_overview"}
