"""Disclosure checks for untrusted public search candidates, without I/O."""
from aicl.workflow.openai_inference import _contains_secret


def public_search_candidate_is_disclosable(candidate, api_key=""):
    """Check candidate metadata without changing a URL or granting access.

    Callers establish public-search provenance and validate shape separately.
    This does not sanitize page bodies, owner inputs, or private context.
    """
    return not _contains_secret({key: candidate[key] for key in ("url", "title", "text")
                                 if key in candidate}, api_key)
